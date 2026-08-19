# Implementation Plan: Archive + Dedup + Serve-Then-Delete + Fallback Purge + Session Isolation + Hard Link Sharing

## Overview

Transform the download system from a "storage" model (files accumulate forever) to a "delivery" model (files exist only long enough for the user to download them, then are deleted). Add session isolation so each browser session only sees and can access its own downloads. Use hard links so multiple sessions sharing the same video each get their own independent file handle without re-downloading from the source.

## Goals

1. Prevent duplicate downloads of the same video (archive + dedup)
2. Free disk space automatically after the user downloads a file (serve-then-delete)
3. Safety net for files never claimed by the user (fallback time-based purge, 3 hours)
4. Stay within the 19GB volume limit
5. Session isolation -- each browser session only sees its own files (no cross-user leakage)
6. Multi-session sharing -- if two users download the same video, each gets their own file via hard link, deleted independently, no re-download from source

## Testing

Every new function and endpoint must be accompanied by test cases.

**Backend tests** (existing frameworks, no new dependencies):
- pytest -- test runner
- unittest.mock -- mocking (MagicMock, patch)
- FastAPI TestClient (httpx) -- API endpoint testing
- All tests run without external deps (Redis, network, Docker) -- everything mocked

**Frontend tests** (existing frameworks, no new dependencies):
- Vitest -- test runner
- @testing-library/react -- component testing
- @testing-library/user-event -- user interaction simulation
- vi.mock -- mocking API calls

---

## Part 1: Download Archive (yt-dlp native)

### What it does
yt-dlp maintains a text file recording all downloaded video IDs. If a video ID is already in the archive, yt-dlp skips the download entirely (no network request, no re-download). The job finishes instantly and returns the existing filename.

### Changes

**File: `backend/app/core/config.py`**
- Add `ARCHIVE_FILE = os.environ.get("ARCHIVE_FILE", "/app/downloads/.ytdlp-archive.txt")`

**File: `backend/app/core/yt_dlp_service.py`**
- Add `"download_archive": ARCHIVE_FILE` to `_BASE_YDL_OPTS` (applies to both extract_info and download_video)
- import ARCHIVE_FILE from config

**File: `backend/app/core/yt_dlp_service.py` -- new function: `remove_from_archive(video_id: str) -> None`**
- Read the archive file line by line
- Filter out lines containing the video_id
- Write the remaining lines back
- Handle missing file gracefully (no-op)

### Tests
- `test_download_video_includes_archive_opt` -- verify `download_archive` is in ydl_opts
- `test_extract_info_includes_archive_opt` -- verify `download_archive` is in ydl_opts for info too
- `test_remove_from_archive_removes_matching_entry` -- create temp archive, remove one ID, verify it's gone
- `test_remove_from_archive_handles_missing_file` -- no crash when archive doesn't exist
- `test_remove_from_archive_preserves_other_entries` -- only the matching ID is removed
- `test_remove_from_archive_no_op_when_id_not_found` -- ID not in archive -> file unchanged

---

## Part 2: Dedup Check (Redis URL-to-job mapping)

### What it does
Before enqueuing a download job, check Redis for an active job with the same URL. If one exists, return the existing job_id instead of creating a duplicate.

Uses MD5 hash of the full URL as the Redis key. Different URL formats for the same video (youtube.com/watch?v=X vs youtu.be/X) hash differently, but the download archive (Part 1) prevents the actual re-download from the source. The dedup only prevents redundant job enqueuing.

### Changes

**File: `backend/app/core/config.py`**
- Add `DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "3600"))` (1 hour TTL)

**File: `backend/app/core/queue.py` -- new functions:**
- `def _url_hash(url: str) -> str`
  - Hash the URL using hashlib.md5 for a short, deterministic key
  - Return hex digest
- `def get_active_job_for_url(url: str) -> str | None`
  - Redis key: `ytdlp:active:{md5_hash}`
  - Return the stored job_id if it exists, None otherwise
- `def set_active_job_for_url(url: str, job_id: str) -> None`
  - SET `ytdlp:active:{md5_hash}` = job_id with TTL (DEDUP_TTL_SECONDS)
- `def clear_active_job_for_url(url: str) -> None`
  - DEL `ytdlp:active:{md5_hash}`

**File: `backend/app/api/download.py` -- update `start_download()`:**
- Before enqueuing: call `get_active_job_for_url(url)`
- If active job exists:
  - Fetch the job via `Job.fetch(job_id, connection=...)`
  - If job is queued or started -> return existing job_id with status "already_queued"
  - If job is finished or failed -> clear the mapping and proceed with new download
- If no active job: enqueue, then `set_active_job_for_url(url, job.id)`
- Return job_id as before

**File: `backend/app/api/download.py` -- update `get_job_status()`:**
- After fetching job status, if status is finished or failed:
  - Get the URL from job.kwargs
  - Call `clear_active_job_for_url(url)` to allow re-downloads
- This cleans up the mapping without needing RQ callbacks

### Tests
- `test_url_hash_is_deterministic` -- same URL always produces same hash
- `test_url_hash_is_different_for_different_urls` -- different URLs produce different hashes
- `test_get_active_job_for_url_returns_none_when_empty` -- no mapping exists
- `test_set_then_get_active_job_for_url` -- set mapping, verify it returns
- `test_clear_active_job_for_url` -- set mapping, clear, verify gone
- `test_set_active_job_for_url_sets_ttl` -- verify TTL is applied to the Redis key
- `test_start_download_dedup_returns_existing_job` -- submit same URL twice, second call returns first job_id
- `test_start_download_dedup_returns_already_queued_status` -- second submission returns status "already_queued"
- `test_start_download_creates_new_job_after_completion` -- after job is finished, new submission creates new job
- `test_start_download_creates_new_job_after_failure` -- after job is failed, new submission creates new job
- `test_start_download_sets_dedup_mapping_after_enqueue` -- verify set_active_job_for_url is called
- `test_get_job_status_clears_dedup_on_completion` -- polling a finished job clears the mapping
- `test_get_job_status_clears_dedup_on_failure` -- polling a failed job clears the mapping
- `test_get_job_status_does_not_clear_dedup_while_in_progress` -- polling a started job does NOT clear mapping

---

## Part 3: Serve-Then-Delete (cleanup after user downloads file)

### What it does
When the user clicks the download link and the file is served, the session's file is deleted immediately after the response completes, and the archive entry is removed only if the underlying file has no remaining hard links (i.e., no other session is still waiting to download it).

### Hard Link Model

When a video file is downloaded by yt-dlp, it lands on disk once. When a second session needs the same video (either via dedup returning the same job_id, or via archive skip returning the existing filename), the backend creates a hard link to the original file with a session-specific name. Each session has its own directory entry pointing to the same inode. When a session downloads and deletes its file, the underlying data stays until the last link is removed (the filesystem handles this automatically via inode link count).

File naming convention:
- Original download: `Title [video_id].mp4` (as produced by yt-dlp)
- Session A's copy: `.session/{session_id_a}/Title [video_id].mp4` (hard link to original)
- Session B's copy: `.session/{session_id_b}/Title [video_id].mp4` (hard link to original)

The original file stays until all session links + the original are deleted.

### Changes

**File: `backend/app/core/config.py`**
- Add `SESSION_DIR = os.environ.get("SESSION_DIR", "/app/downloads/.session")`

**File: `backend/app/core/yt_dlp_service.py` -- new function: `parse_video_id(filename: str) -> str | None`:**
- Extract the video ID from a filename matching the pattern `Title [video_id].ext`
- Regex: `\[([^\]]+)\]` -- captures the content inside the last `[...]`
- Return None if no match (file might have a custom output template)

**File: `backend/app/core/files_service.py` -- new module for file management:**
- `def get_original_filename(filename: str) -> str`
  - Returns the basename without any session directory prefix
- `def get_session_file_path(session_id: str, filename: str) -> str`
  - Returns: `{SESSION_DIR}/{session_id}/{filename}`
  - Validates session_id is a safe UUID (no path traversal)
- `def create_session_link(session_id: str, filename: str) -> str`
  - Create the session directory if it doesn't exist: `{SESSION_DIR}/{session_id}/`
  - Create a hard link: `os.link(original_path, session_path)`
  - Return the session file path
  - Handle case where original file doesn't exist (already deleted) -> return None
- `def delete_session_file(session_id: str, filename: str) -> dict`
  - Delete the session's hard link from disk
  - Check if the original file still exists and has remaining hard links (os.stat().st_nlink)
  - If st_nlink == 1 (only the original remains): delete original, remove from archive
  - Return: `{"deleted": filename, "original_removed": bool, "video_id": str | None}`
- `def file_exists_for_session(session_id: str, filename: str) -> bool`
  - Check if the session-specific hard link exists on disk
- `def get_file_size(session_id: str, filename: str) -> int | None`
  - Return file size in bytes, None if file doesn't exist

**File: `backend/app/api/files.py` -- update `download_file()`:**
- Accept `background_tasks: BackgroundTasks` parameter
- Accept `X-Session-ID` header
- Verify file belongs to session (via Redis mapping -- see Part 5)
- Verify session file exists on disk (hard link)
- Serve the session-specific file path
- Schedule background task to:
  - Delete the session's hard link
  - Call `delete_session_file(session_id, filename)`
  - If original was removed: parse video_id, remove from archive, clear dedup mapping
  - Clear session-to-file mapping in Redis
- The background task runs after the response is fully sent to the client

### Tests
- `test_parse_video_id_extracts_from_filename` -- "My Video [abc123].mp4" -> "abc123"
- `test_parse_video_id_returns_none_for_no_brackets` -- "video.mp4" -> None
- `test_parse_video_id_returns_none_for_empty_string` -- "" -> None
- `test_parse_video_id_extracts_from_audio_file` -- "Song [xyz789].webm" -> "xyz789"
- `test_get_session_file_path_returns_safe_path` -- session_id + filename -> correct path
- `test_get_session_file_path_rejects_bad_session_id` -- session_id with / or .. -> raises
- `test_create_session_link_creates_hard_link` -- create link, verify it exists and points to same inode
- `test_create_session_link_returns_none_when_original_missing` -- original deleted -> None
- `test_delete_session_file_removes_link_only` -- 2 links exist, delete one, original stays
- `test_delete_session_file_removes_original_when_last_link` -- 1 link left, delete, original also gone
- `test_delete_session_file_removes_archive_when_original_removed` -- verify archive cleanup
- `test_file_exists_for_session_returns_true` -- link exists -> True
- `test_file_exists_for_session_returns_false` -- link doesn't exist -> False
- `test_get_file_size_returns_bytes` -- file exists -> returns size
- `test_get_file_size_returns_none_when_missing` -- file gone -> None
- `test_download_file_schedules_cleanup` -- verify background task is registered
- `test_download_file_cleanup_deletes_session_link` -- after response, session link gone
- `test_download_file_cleanup_keeps_original_if_other_links` -- other sessions still have links
- `test_download_file_cleanup_removes_original_if_last_link` -- last session downloads -> original gone
- `test_download_file_returns_404_for_nonexistent_file` -- unchanged, still works
- `test_download_file_rejects_path_traversal` -- unchanged, still works

---

## Part 4: Fallback Purge (safety net for unclaimed files)

### What it does
If a user downloads a video but never clicks the download link, the file sits in downloads/ forever. This endpoint purges files older than a configurable max age (default: 3 hours). Also cleans up the corresponding archive entries and session links.

### Changes

**File: `backend/app/core/config.py`**
- Add `PURGE_MAX_AGE_HOURS = int(os.environ.get("PURGE_MAX_AGE_HOURS", "3"))`

**File: `backend/app/core/files_service.py` -- new function: `_purge_old_files(session_id: str, max_age_hours: int, delete: bool = True) -> dict`:**
- Core purge logic shared by purge and preview endpoints
- Get list of files for the session from Redis (Part 5)
- For each file:
  - Check the session file's mtime
  - If older than max_age_hours:
    - If `delete=True`: call `delete_session_file(session_id, filename)`, clear session mapping
    - Record: filename, video_id, size_bytes, age_hours
- Also scan the original downloads directory for orphaned original files (files with no remaining session links):
  - Check `os.stat(filepath).st_nlink == 1` (only the original, no session links)
  - If older than max_age_hours: delete, remove from archive, clear dedup
- Skip: `.ytdlp-archive.txt`, `.gitkeep`, `.session/` directory, and any hidden files
- Return: `{"purged": [...], "skipped": N, "freed_bytes": N}`

**File: `backend/app/api/files.py` -- new endpoint: `POST /api/purge`:**
- Accept `X-Session-ID` header
- Call `_purge_old_files(session_id, PURGE_MAX_AGE_HOURS, delete=True)`
- Return the purge summary

**File: `backend/app/api/files.py` -- new endpoint: `GET /api/purge/preview`:**
- Accept `X-Session-ID` header
- Call `_purge_old_files(session_id, PURGE_MAX_AGE_HOURS, delete=False)`
- Same response shape but files are NOT deleted
- Useful for checking what would be purged before actually running it

### Tests
- `test_purge_deletes_old_session_files` -- create old session links, purge, verify deleted
- `test_purge_preserves_recent_files` -- create fresh files, purge, verify kept
- `test_purge_skips_archive_file` -- .ytdlp-archive.txt is never purged
- `test_purge_skips_gitkeep` -- .gitkeep is never purged
- `test_purge_skips_session_dir` -- .session/ directory is never purged directly
- `test_purge_skips_hidden_files` -- any file starting with . is skipped
- `test_purge_removes_archive_entries` -- old file with video ID -> archive entry also removed
- `test_purge_removes_orphaned_originals` -- original with no session links, old -> deleted
- `test_purge_keeps_originals_with_active_links` -- original with session links -> kept
- `test_purge_returns_summary` -- response includes list of purged files, skipped count, freed bytes
- `test_purge_preview_does_not_delete` -- preview endpoint returns info but files remain
- `test_purge_preview_returns_same_shape` -- preview response has same fields as purge
- `test_purge_empty_dir_returns_empty_list` -- no files -> empty purged list
- `test_purge_handles_file_without_video_id` -- file with no ID bracket -> deleted, no archive change
- `test_purge_only_purges_session_files` -- session A purge does not delete session B's files
- `test_purge_preview_only_previews_session_files` -- same isolation for preview
- `test_purge_endpoint_registered` -- POST /api/purge and GET /api/purge/preview resolve

---

## Part 5: Session Isolation (frontend-managed sessions)

### What it does
The frontend generates a session ID (UUID) on first visit, stores it in localStorage, and sends it as an `X-Session-ID` header with every API request. The backend uses this opaque string as a namespace key to isolate files per session. The backend does NOT manage users, login, or session lifecycle -- it just sees and stores the string.

### Changes

**File: `frontend/src/lib/api.ts` -- add session management:**
- New function: `getOrCreateSessionId(): string`
  - Check localStorage for `ytdlp-session-id`
  - If not found, generate `crypto.randomUUID()`, store in localStorage
  - Return the session ID
- Update all fetch calls (fetchVideoInfo, startDownload, getJobStatus, listFiles) to include `X-Session-ID` header
- The session ID is generated once and persisted across page reloads

**File: `frontend/src/lib/api.ts` -- new function: `listFiles(): Promise<FileInfo[]>`:**
- GET /api/files with X-Session-ID header
- Returns only the current session's files

**File: `backend/app/core/queue.py` -- new functions for session-to-file mapping:**
- `def _session_file_key(session_id: str) -> str`
  - Returns Redis key: `ytdlp:session:{session_id}:files`
- `def register_file_for_session(session_id: str, filename: str) -> None`
  - SADD the filename to the session's file set in Redis
  - No TTL -- cleared when file is served or purged
- `def get_files_for_session(session_id: str) -> list[str]`
  - SMEMBERS of the session's file set
  - Return list of filenames
- `def clear_file_for_session(session_id: str, filename: str) -> None`
  - SREM the filename from the session's file set
- `def clear_all_files_for_session(session_id: str) -> None`
  - DEL the session's file set key

**File: `backend/app/api/download.py` -- update `start_download()`:**
- Accept `x_session_id: str | None = Header(None)` parameter
- If no session_id: return 400 "X-Session-ID header required"
- Pass `session_id` to `download_video()` as a new parameter
- Store session_id in job kwargs (RQ stores kwargs, retrievable via job.kwargs)

**File: `backend/app/core/yt_dlp_service.py` -- update `download_video()`:**
- Accept new parameter: `session_id: str | None = None`
- After download completes, if session_id is provided:
  - For each captured filename:
    - Register to session: `register_file_for_session(session_id, filename)`
    - Create session hard link: `files_service.create_session_link(session_id, filename)`
- Return session_id in result dict for traceability

**File: `backend/app/api/files.py` -- update all endpoints:**
- `GET /api/files` -- accept `X-Session-ID` header, filter by session
  - If no header: return 400 "X-Session-ID header required"
  - Call `get_files_for_session(session_id)` to get filenames
  - Return file info (name, size) for only those files, reading from session links
- `GET /api/files/{filename}` -- accept `X-Session-ID` header, verify ownership
  - Check filename is in `get_files_for_session(session_id)`
  - If not: return 403 "File does not belong to this session"
  - Verify session file exists on disk (hard link)
  - Serve the session-specific file path
  - Serve-then-delete cleanup as described in Part 3
- `POST /api/purge` -- accept `X-Session-ID` header, only purge that session's files
- `GET /api/purge/preview` -- accept `X-Session-ID` header, only preview that session's files

### Multi-Session Sharing Flow (hard links)

When User B submits the same URL as User A:

1. User A submits URL -> job enqueued -> yt-dlp downloads -> file `Title [X].mp4` created
   - `register_file_for_session(session_a, "Title [X].mp4")`
   - `create_session_link(session_a, "Title [X].mp4")` -> hard link at `.session/{session_a}/Title [X].mp4`
   - Dedup mapping set, archive entry added

2. User B submits same URL -> dedup check finds active mapping -> returns User A's job_id
   - User B polls job -> sees "finished" with files list
   - Frontend shows download link for User B
   - User B clicks download -> `GET /api/files/Title [X].mp4` with User B's session
   - Backend: file is NOT in User B's session mapping -> need to register it
   - `register_file_for_session(session_b, "Title [X].mp4")`
   - `create_session_link(session_b, "Title [X].mp4")` -> hard link at `.session/{session_b}/Title [X].mp4`
   - Serve User B's hard link, then delete it
   - Original file stays (User A's link still exists)

3. User A clicks download -> serves User A's hard link, deletes it
   - Original file: st_nlink was 2 (original + no one, since both session links deleted)
   - Actually: original + session_a link + session_b link = 3 links
   - After session_b link deleted: 2 links remain (original + session_a)
   - After session_a link deleted: 1 link remains (original only)
   - st_nlink == 1 -> delete original, remove from archive, clear dedup

Edge case: User B clicks download before User A's link is created (job still running):
- User B's poll returns "started" (job not finished yet)
- User B waits for job to finish, then clicks download
- At that point, both session links are created (User A's at job completion, User B's at download time)

Edge case: User B clicks download after User A already downloaded and original was deleted:
- `create_session_link` returns None (original doesn't exist)
- Return 404 "File no longer available, please re-download"
- User B re-submits the URL -> new download from YouTube (archive was cleaned up)

### Tests -- Backend
- `test_get_or_create_session_id_generates_uuid` -- first call generates a UUID
- `test_get_or_create_session_id_persists` -- second call returns same UUID
- `test_register_file_for_session_adds_to_set` -- file is in session's file list
- `test_get_files_for_session_returns_registered_files` -- register files, verify list
- `test_get_files_for_session_returns_empty_for_unknown_session` -- no files registered
- `test_clear_file_for_session_removes_one_file` -- SREM removes specific file
- `test_clear_all_files_for_session_removes_all` -- DEL clears the set
- `test_start_download_passes_session_id_to_job` -- verify session_id is in job kwargs
- `test_start_download_returns_400_without_session_header` -- missing X-Session-ID -> 400
- `test_download_video_registers_files_for_session` -- after download, files are registered to session
- `test_download_video_creates_session_links` -- after download, hard links exist on disk
- `test_list_files_filters_by_session` -- two sessions, each only sees own files
- `test_list_files_returns_400_without_session_header` -- missing X-Session-ID -> 400
- `test_download_file_creates_link_for_second_session` -- User B download creates hard link
- `test_download_file_returns_403_for_wrong_session` -- file belongs to session A, session B without registration -> 403
- `test_download_file_returns_404_when_original_deleted` -- original gone, can't create link -> 404
- `test_download_file_cleanup_clears_session_mapping` -- after serve-then-delete, file removed from session set
- `test_download_file_cleanup_keeps_original_if_other_links` -- other sessions still have links
- `test_download_file_cleanup_removes_original_if_last_link` -- last session downloads -> original gone
- `test_purge_only_purges_session_files` -- session A purge does not delete session B's files
- `test_purge_preview_only_previews_session_files` -- same isolation for preview
- `test_multi_session_sharing_both_users_get_file` -- full flow: A downloads, B downloads, both served
- `test_multi_session_first_download_does_not_delete_for_second` -- A downloads first, B's file still exists
- `test_multi_session_last_download_cleans_up_original` -- both download, original cleaned up

### Tests -- Frontend
- `test_api_client_sends_session_header` -- verify fetch calls include X-Session-ID
- `test_session_id_persisted_in_localStorage` -- verify localStorage is set
- `test_session_id_reused_across_calls` -- multiple API calls use same session ID
- `test_list_files_calls_correct_endpoint` -- GET /api/files with session header

---

## Part 6: Update Existing Tests

### Files that need test updates

**`backend/tests/conftest.py`:**
- Update `fake_job` to include `kwargs` attribute with `url` and `session_id` (needed for dedup cleanup in get_job_status)
- Add fixture: `fake_redis_for_dedup` -- a MagicMock with get/set/delete/expire methods
- Add fixture: `fake_redis_for_session` -- a MagicMock with sadd/smembers/srem/del methods
- Add fixture: `fake_session_id` -- returns a fixed UUID string for testing
- Add fixture: `temp_downloads_dir` -- creates a temp directory simulating downloads/ with .session/ subdirectory

**`backend/tests/test_yt_dlp_service.py`:**
- Update existing tests that check ydl_opts to account for new `download_archive` key
- Update `test_download_video_calls_yt_dlp_download` to pass session_id parameter
- Add tests for `parse_video_id` and `remove_from_archive`
- Add tests for session registration and hard link creation in download_video

**`backend/tests/test_files_service.py` -- new test file:**
- All hard link, session path, delete logic tests (see Part 3 tests)

**`backend/tests/test_download_api.py`:**
- Update `test_start_download_enqueues_job` to verify dedup mapping is set and session_id is passed
- Add dedup-specific tests (see Part 2)
- Add session header tests (see Part 5)

**`backend/tests/test_files_api.py`:**
- Update existing tests to include X-Session-ID header
- Add cleanup and purge tests (see Parts 3 and 4)
- Add session isolation tests (see Part 5)
- Add multi-session sharing tests (see Part 5)

**`backend/tests/test_main.py`:**
- Add test for purge endpoint registration

**`backend/tests/test_queue.py`:**
- Add tests for dedup helpers (_url_hash, get/set/clear active job)
- Add tests for session file mapping helpers

**`frontend/tests/api.test.ts`:**
- Add tests for session ID generation and header injection
- Add test for listFiles() function

**`frontend/tests/JobStatusCard.test.tsx`:**
- No changes needed -- the UI already shows download links, the backend cleanup is transparent

**`frontend/tests/App.test.tsx`:**
- No changes needed -- session management is in api.ts, transparent to components

---

## Part 7: Config & Docker Updates

**File: `backend/app/core/config.py`** (summary of all new config):
```python
ARCHIVE_FILE = os.environ.get("ARCHIVE_FILE", "/app/downloads/.ytdlp-archive.txt")
DEDUP_TTL_SECONDS = int(os.environ.get("DEDUP_TTL_SECONDS", "3600"))
PURGE_MAX_AGE_HOURS = int(os.environ.get("PURGE_MAX_AGE_HOURS", "3"))
SESSION_DIR = os.environ.get("SESSION_DIR", "/app/downloads/.session")
```

**File: `docker-compose.yml`** -- add env vars to backend and worker:
```yaml
environment:
  - ARCHIVE_FILE=/app/downloads/.ytdlp-archive.txt
  - DEDUP_TTL_SECONDS=3600
  - PURGE_MAX_AGE_HOURS=3
  - SESSION_DIR=/app/downloads/.session
```

---

## Part 8: README Updates

- Add `POST /api/purge` and `GET /api/purge/preview` to API endpoints
- Add `X-Session-ID` header to API documentation
- Update Notes section: explain serve-then-delete model, archive, dedup, session isolation, hard link sharing
- Update test counts
- Add archive file, dedup mapping, session mapping, and .session/ directory to architecture notes

---

## Implementation Order

1. config.py -- add all new config values (ARCHIVE_FILE, DEDUP_TTL_SECONDS, PURGE_MAX_AGE_HOURS, SESSION_DIR)
2. yt_dlp_service.py -- add archive opt, parse_video_id, remove_from_archive, session_id param in download_video
3. files_service.py -- new module: get_session_file_path, create_session_link, delete_session_file, file_exists_for_session, get_file_size
4. queue.py -- add dedup helpers (_url_hash, get/set/clear active job for URL) + session file mapping helpers
5. download.py -- add dedup check, X-Session-ID header, cleanup in get_job_status, pass session_id to download_video
6. files.py -- add session filtering, serve-then-delete with hard link cleanup, purge endpoint, purge preview endpoint
7. frontend/src/lib/api.ts -- add session management, X-Session-ID header, listFiles()
8. tests -- update existing + add new (all mocked, no external deps)
9. docker-compose.yml -- add env vars
10. README.md -- update docs
11. Run all tests, verify everything passes

---

## File Change Summary

| File | Change |
|------|--------|
| backend/app/core/config.py | +4 config values |
| backend/app/core/yt_dlp_service.py | +download_archive opt, +parse_video_id(), +remove_from_archive(), +session_id param in download_video() |
| backend/app/core/files_service.py | NEW: +get_session_file_path(), +create_session_link(), +delete_session_file(), +file_exists_for_session(), +get_file_size() |
| backend/app/core/queue.py | +_url_hash(), +get/set/clear_active_job_for_url(), +_session_file_key(), +register/get/clear_file_for_session() |
| backend/app/api/download.py | dedup check, X-Session-ID header, cleanup in get_job_status(), session_id passthrough |
| backend/app/api/files.py | session filtering, serve-then-delete with hard link cleanup, +POST /api/purge, +GET /api/purge/preview |
| frontend/src/lib/api.ts | +getOrCreateSessionId(), X-Session-ID header on all calls, +listFiles() |
| docker-compose.yml | +4 env vars on backend + worker |
| README.md | update endpoints, notes, test counts |
| backend/tests/*.py | ~55 new tests, ~10 updated tests |
| frontend/tests/*.ts(x) | ~4 new tests |

---

## Hard Link Data Flow Diagram

```
User A submits URL -> yt-dlp downloads -> downloads/Title [X].mp4 (original, inode=123)
                                      -> .session/{A}/Title [X].mp4 (hard link, inode=123)
                                      -> Redis: session A has "Title [X].mp4"
                                      -> Redis: dedup mapping set
                                      -> archive: youtube X added

User B submits same URL -> dedup returns job A -> frontend shows download link
  User B clicks download -> GET /api/files/Title [X].mp4 (X-Session-ID: B)
    -> backend: file not in session B's set -> register it
    -> .session/{B}/Title [X].mp4 (hard link, inode=123)
    -> Redis: session B has "Title [X].mp4"
    -> serve file, then delete .session/{B}/Title [X].mp4
    -> st_nlink: original(1) + A(1) = 2 -> original stays
    -> Redis: session B file removed

  User A clicks download -> GET /api/files/Title [X].mp4 (X-Session-ID: A)
    -> backend: file in session A's set -> serve
    -> serve file, then delete .session/{A}/Title [X].mp4
    -> st_nlink: original(1) = 1 -> delete original too
    -> archive: youtube X removed
    -> Redis: dedup mapping cleared
    -> Redis: session A file removed
```