# Refactor Plan: Per-Session Downloads (No Archive, No Hard Links)

## Overview

Replace the current global download model (shared originals + hard links + yt-dlp archive) with a fully per-session model. Each session downloads into its own directory. No yt-dlp archive, no hard links, no shared originals. Dedup is handled via Redis on a per-session + URL + format basis.

## Goals

1. Per-session isolation — each session has its own downloads folder, fully self-contained
2. No yt-dlp archive — every download runs fresh, no archive file, no skip behavior
3. No hard links — each session gets its own copy of the file
4. Dedup within a session — same URL + same quality = reuse existing job, no re-download
5. Different quality = new job — user picks 720p vs 1080p, each gets its own download
6. Serve-then-delete — file is deleted after the user downloads it
7. Fallback purge — files never claimed by the user are purged after 3 hours

## What Gets Removed

- `ARCHIVE_FILE` config and the `.ytdlp-archive.txt` file
- `download_archive` option in yt-dlp `ydl_opts`
- `remove_from_archive()` function
- `parse_video_id()` function (only used for archive cleanup)
- `_recover_files_from_disk()` function (only needed for archive skips)
- `create_session_link()` function (no hard links)
- `get_original_path()` function (no shared originals)
- Hard link reference counting logic in `delete_session_file()`
- Orphaned original file scanning in `_purge_old_files()`
- `_SKIP_FILES` set (archive file no longer exists)

## What Gets Changed

### 1. config.py

- Remove `ARCHIVE_FILE` and `DEDUP_TTL_SECONDS` (dedup moves to session-scoped)
- Keep: `DOWNLOAD_DIR`, `SESSION_DIR`, `PURGE_MAX_AGE_HOURS`, `DEFAULT_FORMAT`, `AUDIO_FORMAT`, `DEFAULT_OUTPUT_TEMPLATE`
- `DOWNLOAD_DIR` is now just the parent of `.session/` — no originals land there directly

### 2. yt_dlp_service.py

**`download_video()` changes:**
- Remove `download_archive` from `ydl_opts`
- Change `outtmpl` to output directly into the session directory with quality suffix:
  ```python
  if audio_only:
      suffix = "audio"
  else:
      suffix = quality  # "1080p", "720p", "480p", "360p"
  outtmpl = f"{SESSION_DIR}/{session_id}/%(title)s [%(id)s]_{suffix}.%(ext)s"
  ```
  The suffix prevents collisions when the same video is downloaded at different qualities, and distinguishes audio from video files.
- Add FFmpeg MP3 postprocessor when `audio_only=True`:
  ```python
  if audio_only:
      ydl_opts["postprocessors"] = [{
          "key": "FFmpegExtractAudio",
          "preferredcodec": "mp3",
          "preferredquality": "192",
      }]
  ```
  This converts the audio stream to MP3 after download. FFmpeg must be installed in the worker container (it already is — used for video+audio merge).
  The final file will have `.mp3` extension: `Title [ID]_audio.mp3`
- Remove hard link creation (`create_session_link` calls) — the file is already in the session dir
- Remove `register_file_for_session` call (file registration moves to the API layer, or is done here with the session-relative filename)
- Keep progress/postprocessor hooks for capturing filenames (job result still needs them)
  - Note: the postprocessor hook fires AFTER the MP3 conversion, so the captured filename will be the final `.mp3` file
- The returned `files` list contains basenames only (the filename within the session dir)

**Remove these functions entirely:**
- `_recover_files_from_disk()` — no archive skips, hooks always fire
- `remove_from_archive()` — no archive
- `parse_video_id()` — no archive cleanup needed
- Remove `import glob`, `import re` if no longer used

### 3. queue.py

**Dedup — change from URL-only to URL + format + session:**
- Remove: `_url_hash()`, `_dedup_key()`, `get_active_job_for_url()`, `set_active_job_for_url()`, `clear_active_job_for_url()`
- Add: session-scoped dedup using Redis SETs:
  - `_session_dedup_key(session_id)` -> `ytdlp:dedup:{session_id}` (a Redis SET)
  - `get_active_job_for_session(session_id, url, format_str) -> str | None`
    - Build a composite key: `{url}|{format_str}`
    - Check if this composite key is in the session's dedup SET
    - If yes, return the stored job_id
    - If no, return None
  - `set_active_job_for_session(session_id, url, format_str, job_id) -> None`
    - SADD the composite key + job_id mapping to the session's dedup SET
    - Store as a Redis hash: `HSET ytdlp:dedup:{session_id} {url}|{format_str} {job_id}`
  - `clear_active_job_for_session(session_id, url, format_str) -> None`
    - HDEL the composite key from the session's dedup hash
  - `clear_all_dedup_for_session(session_id) -> None`
    - DEL the entire dedup hash (used when session is cleaned up)

**Session-to-file mapping — keep as-is:**
- `_session_file_key()`, `register_file_for_session()`, `get_files_for_session()`, `clear_file_for_session()`, `clear_all_files_for_session()`, `file_belongs_to_session()` — all unchanged

### 4. download.py

**`start_download()` changes:**
- Dedup check now uses `(session_id, url, format_str)`:
  ```python
  existing_job_id = get_active_job_for_session(x_session_id, url, format_str)
  if existing_job_id:
      # check if job is still active...
      # if active: return existing job_id
      # if finished/failed: clear mapping, proceed
  ```
- After enqueuing: `set_active_job_for_session(x_session_id, url, format_str, job.id)`
- Store `format_str` in job kwargs (already passed as `format_str=req.format`)

**`get_job_status()` changes:**
- After fetching status, if terminal (finished/failed):
  - Get `url` and `format_str` from `job.kwargs`
  - Get `session_id` from `job.kwargs`
  - Call `clear_active_job_for_session(session_id, url, format_str)`

### 5. files_service.py

**Simplify — no hard links:**
- Remove: `create_session_link()`, `get_original_path()`
- Keep: `_validate_session_id()`, `get_session_dir()`, `cleanup_session_dir()`
- Change `get_session_file_path(session_id, filename)`:
  - Returns `{SESSION_DIR}/{session_id}/{filename}` — the actual file path, not a hard link
- Change `delete_session_file(session_id, filename)`:
  - Simply `os.remove()` the file from the session directory
  - No `st_nlink` check, no original deletion, no archive removal
  - Clean up empty session directory if no files remain
  - Return: `{"deleted": filename, "session_dir_empty": bool}`
- Keep `file_exists_for_session(session_id, filename)`:
  - Check if file exists at `get_session_file_path()` — same logic, just no hard link
- Keep `get_file_size(session_id, filename)`:
  - Same — reads size from the session file path

### 6. files.py

**`download_file()` changes:**
- Remove: hard link creation block (`create_session_link`, `register_file_for_session`)
- The file is already in the session directory from `download_video()`
- Serve directly from `get_session_file_path(session_id, basename)`
- Background cleanup: `os.remove()` the file, `clear_file_for_session()`
- Remove: `remove_from_archive` import, `parse_video_id` import

**`list_files()` changes:**
- Unchanged — already reads from session-scoped Redis SET and `get_file_size()`

**`_purge_old_files()` changes:**
- Remove: orphaned original scanning (no originals in DOWNLOAD_DIR anymore)
- Keep: session file scanning — scan `.session/{session_id}/` for old files
- Remove: `remove_from_archive()` call, `parse_video_id()` call
- Remove: `_SKIP_FILES` set (no archive file to skip)
- The purge only scans the requesting session's directory

### 7. Frontend — Quality Pills (VideoInfoCard)

Replace the format text input with pill-style buttons:

**Quality options (video):**
- 1080p -> `bestvideo[height<=1080]+bestaudio/best`
- 720p -> `bestvideo[height<=720]+bestaudio/best`
- 480p -> `bestvideo[height<=480]+bestaudio/best`
- 360p -> `bestvideo[height<=360]+bestaudio/best`

**Audio option:**
- Audio only -> sends `audio_only: true`, quality `audio`
- Backend uses format `bestaudio/best` + FFmpeg MP3 postprocessor
- Final file: `Title [ID]_audio.mp3`

**UI:**
- Pills rendered as inline buttons in a row
- Selected pill is highlighted (green bg), others are slate
- Audio only is a separate pill (toggles audio mode)
- When audio is selected, video quality pills are hidden
- The format string is never shown to the user — pills map to quality strings internally
- Default selection: 1080p (or highest available)

**Types:**
- `DownloadOptions` changes from `{ format: string, audio_only: boolean }` to `{ quality: string, audio_only: boolean }`
- `quality` is one of: `"1080p" | "720p" | "480p" | "360p" | "audio"`
- When `audio_only: true`, quality is `"audio"`

**api.ts:**
- `startDownload()` takes `quality` and `audio_only`, sends to backend
- Backend maps quality -> format string via `QUALITY_MAP`

### 8. Schemas (schemas.py)

**Backend maps quality to format (recommended)**
- `DownloadRequest` changes:
  ```python
  class DownloadRequest(BaseModel):
      url: HttpUrl
      quality: str = "1080p"  # "1080p", "720p", "480p", "360p", "audio"
      audio_only: bool = False
  ```
- Backend has a mapping dict:
  ```python
  QUALITY_MAP = {
      "1080p": "bestvideo[height<=1080]+bestaudio/best",
      "720p":  "bestvideo[height<=720]+bestaudio/best",
      "480p":  "bestvideo[height<=480]+bestaudio/best",
      "360p":  "bestvideo[height<=360]+bestaudio/best",
      "audio": "bestaudio/best",
  }
  ```
- `download_video()` receives `quality` and looks up the format string
- When `quality == "audio"`, adds the FFmpeg MP3 postprocessor
- Dedup uses `quality` (not raw format string) — cleaner Redis keys
- Filename suffix uses `quality`: `Title [ID]_720p.mp4`, `Title [ID]_audio.mp3`

## Directory Structure (After Refactor)

```
downloads/
  .session/
    8aa6d3ce-35b7-4dc0-9dd8-f62fffe4350a/    <- session A
      Tropical Storm Lala [HayoTif9k5Q]_720p.mp4
      Tropical Storm Lala [HayoTif9k5Q]_1080p.mp4
      Tropical Storm Lala [HayoTif9k5Q]_audio.mp3
      Another Video [abc123]_480p.webm
    f3b2a1c4-9876-4abc-def0-1234567890ab/    <- session B
      Tropical Storm Lala [HayoTif9k5Q]_720p.mp4   <- same video, own copy
  .gitkeep
```

- No `.ytdlp-archive.txt`
- No originals in `downloads/` root (only `.session/` and `.gitkeep`)
- Each session folder is self-contained
- Quality suffix in filename prevents collisions (720p, 1080p, audio)
- Audio files are MP3 (FFmpeg postprocessor converts from source codec)
- Empty session folders are removed by `delete_session_file()` and `_purge_old_files()`

## Data Flow

### Download flow (new)
```
User selects 720p + clicks Download
  -> POST /api/download { url, quality: "720p", audio_only: false }
  -> Backend: check dedup for (session_id, url, "720p")
     -> If active job exists: return existing job_id
     -> If no active job: enqueue job with (url, quality="720p", session_id)
        -> set_active_job_for_session(session_id, url, "720p", job.id)
  -> RQ worker: download_video(url, quality="720p", session_id)
     -> outtmpl = {SESSION_DIR}/{session_id}/%(title)s [%(id)s]_720p.%(ext)s
     -> format = QUALITY_MAP["720p"] = "bestvideo[height<=720]+bestaudio/best"
     -> yt-dlp downloads directly into session folder
     -> hooks capture filename(s) — final file: "Title [ID]_720p.mp4"
     -> register_file_for_session(session_id, filename)
     -> return { files: [filename], ... }
  -> Frontend polls until finished
  -> JobStatusCard shows download button

User selects Audio only + clicks Download
  -> POST /api/download { url, quality: "audio", audio_only: true }
  -> Backend: check dedup for (session_id, url, "audio")
     -> If active job exists: return existing job_id
     -> If no active job: enqueue job
  -> RQ worker: download_video(url, quality="audio", audio_only=True, session_id)
     -> outtmpl = {SESSION_DIR}/{session_id}/%(title)s [%(id)s]_audio.%(ext)s
     -> format = QUALITY_MAP["audio"] = "bestaudio/best"
     -> postprocessors = [{ key: "FFmpegExtractAudio", preferredcodec: "mp3", preferredquality: "192" }]
     -> yt-dlp downloads audio stream, FFmpeg converts to MP3
     -> hooks capture filename — final file: "Title [ID]_audio.mp3"
     -> register_file_for_session(session_id, filename)
     -> return { files: [filename], ... }
```

### Serve-then-delete flow (new)
```
User clicks filename in JobStatusCard
  -> GET /api/files/{filename} (X-Session-ID header)
  -> Backend: verify file belongs to session
  -> Serve file from {SESSION_DIR}/{session_id}/{filename}
  -> Background task: os.remove(file), clear_file_for_session()
  -> Clean up empty session dir if no files remain
```

### Dedup flow (new)
```
Session A: download video X at 720p
  -> dedup: HSET ytdlp:dedup:{A} "https://...|720p" {job_id}
  -> job runs, file created in .session/{A}/: Title [ID]_720p.mp4

Session A: download video X at 720p again (while job active)
  -> dedup: HGET ytdlp:dedup:{A} "https://...|720p" -> returns job_id
  -> job is active -> return existing job_id (no new download)

Session A: download video X at 1080p
  -> dedup: HGET ytdlp:dedup:{A} "https://...|1080p" -> None
  -> new job enqueued, new file: Title [ID]_1080p.mp4

Session A: download video X as audio (MP3)
  -> dedup: HGET ytdlp:dedup:{A} "https://...|audio" -> None
  -> new job enqueued, new file: Title [ID]_audio.mp3

Session B: download video X at 720p
  -> dedup: HGET ytdlp:dedup:{B} "https://...|720p" -> None (different session)
  -> new job enqueued, new file in .session/{B}/: Title [ID]_720p.mp4
```

### Purge flow (new)
```
POST /api/purge (X-Session-ID header)
  -> Scan .session/{session_id}/ for files older than 3 hours
  -> Delete old files, clear Redis mappings
  -> Remove empty session directory
  -> No orphaned original scanning (no originals in downloads/ root)
```

## Implementation Order

1. **config.py** — remove `ARCHIVE_FILE`, `DEDUP_TTL_SECONDS`; keep the rest
2. **schemas.py** — change `DownloadRequest` to use `quality` instead of `format`; add `QUALITY_MAP`
3. **queue.py** — replace URL-only dedup with session-scoped dedup; keep session-file mapping
4. **yt_dlp_service.py** — remove archive, remove hard links, output to session dir; remove `parse_video_id`, `remove_from_archive`, `_recover_files_from_disk`
5. **files_service.py** — simplify: no hard links, no original path, simple delete
6. **download.py** — update dedup calls, pass `quality` to job kwargs
7. **files.py** — remove hard link creation, remove archive cleanup, simplify purge
8. **Frontend types.ts** — change `DownloadOptions` to use `quality`
9. **Frontend api.ts** — update `startDownload` to send `quality`
10. **Frontend VideoInfoCard.tsx** — replace text input with quality pills
11. **Frontend App.tsx** — update `handleDownload` for new `quality` param
12. **Frontend tests** — update for quality pills, remove format string tests
13. **Backend tests** — remove archive/hard-link tests, update dedup tests, add quality tests
14. **docker-compose.yml** — remove `ARCHIVE_FILE`, `DEDUP_TTL_SECONDS` env vars
15. **Run all tests, verify everything passes**

## Test Changes

### Remove entirely
- `test_*_archive_*` — archive tests
- `test_parse_video_id_*` — parse_video_id tests
- `test_remove_from_archive_*` — remove_from_archive tests
- `test_recover_files_from_disk_*` — recovery tests
- `test_download_video_includes_archive_opt` — archive opt test
- `test_extract_info_does_not_include_archive_opt` — archive opt test
- Hard link specific tests in `test_files_service.py` (link count, st_nlink, shared inode)

### Update
- `test_download_video_*` — no archive opt, no hard link creation, output to session dir
- `test_*_dedup_*` — use session_id + url + quality, not just url
- `test_files_api.py` — no hard link creation in download_file, simple serve-then-delete
- `test_files_service.py` — simple delete (no st_nlink logic)
- `test_download_api.py` — pass `quality` instead of `format`, dedup by quality
- Frontend `VideoInfoCard.test.tsx` — quality pills instead of format input
- Frontend `App.test.tsx` — send `quality` in download request

### Add
- `test_download_video_outputs_to_session_dir` — verify outtmpl includes session path
- `test_download_video_quality_map` — verify quality -> format mapping
- `test_download_video_filename_includes_quality_suffix` — verify `_720p` in filename
- `test_download_video_audio_adds_mp3_postprocessor` — verify FFmpegExtractAudio postprocessor when audio_only
- `test_download_video_audio_filename_has_mp3_extension` — verify final filename is `.mp3`
- `test_dedup_different_quality_different_job` — same URL, different quality = new job
- `test_dedup_same_quality_returns_existing_job` — same URL + quality = existing job
- `test_dedup_different_session_different_job` — same URL + quality, different session = new job
- `test_dedup_audio_separate_from_video` — same URL, audio vs 720p = different jobs
- `test_purge_scans_session_dir_only` — no orphaned original scanning
- Frontend: `test_quality_pills_render` — verify pills are shown
- Frontend: `test_quality_pill_selection` — verify selection sends correct quality
- Frontend: `test_audio_only_hides_quality_pills` — audio mode hides video pills
- Frontend: `test_audio_pill_sends_audio_quality` — audio pill sends `quality: "audio"`