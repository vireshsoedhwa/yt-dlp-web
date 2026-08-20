# Session Job Restoration — Persist Job Cards Across Page Refreshes

## Overview

Currently, job cards live in React state (App.tsx) and vanish on page refresh. When a user downloads a video but hasn't yet saved the file to their computer, a refresh loses the job card and the download link. This plan adds backend tracking of jobs per session so the frontend can restore the job list on page load.

Each session sees only its own jobs. Other users see their own lists.

## Goals

1. Job cards persist across page refreshes — restoring from the backend using the session ID
2. Each session only sees its own jobs (isolation)
3. Jobs are removed from the session when:
   - The user downloads the file (serve-then-delete clears the job)
   - The user manually dismisses the job card
   - The job is purged (3-hour fallback)
4. No changes to the existing download, dedup, or file-serving flows

## Architecture

### New Redis key: `ytdlp:session:{session_id}:jobs`

A Redis hash (not a SET) that maps `job_id` -> `url` for the session. This is separate from the dedup hash (`ytdlp:dedup:{session_id}`) which gets cleaned up when jobs finish. The jobs hash persists until the job's file is downloaded or the user dismisses it.

Using a hash (not a SET) so we can store the URL alongside the job_id — the frontend needs the URL to display in the JobStatusCard.

### Why not reuse the dedup hash?

The dedup hash (`ytdlp:dedup:{session_id}`) maps `{url}|{quality}` -> `job_id` and is cleared when the job reaches a terminal state (finished/failed). If we reused it, finished jobs would disappear from the dedup hash before the user has a chance to download the file. The jobs hash is intentionally separate and persists longer.

## Backend Changes

### 1. queue.py — new session-jobs helpers

```python
def _session_jobs_key(session_id: str) -> str:
    return f"ytdlp:session:{session_id}:jobs"

def register_job_for_session(session_id: str, job_id: str, url: str) -> None:
    get_redis().hset(_session_jobs_key(session_id), job_id, url)

def get_jobs_for_session(session_id: str) -> list[dict]:
    """Return list of {job_id, url} for all jobs in the session."""
    raw = get_redis().hgetall(_session_jobs_key(session_id))
    return [
        {"job_id": k.decode() if isinstance(k, bytes) else k,
         "url": v.decode() if isinstance(v, bytes) else v}
        for k, v in raw.items()
    ]

def clear_job_for_session(session_id: str, job_id: str) -> None:
    get_redis().hdel(_session_jobs_key(session_id), job_id)

def clear_all_jobs_for_session(session_id: str) -> None:
    get_redis().delete(_session_jobs_key(session_id))
```

### 2. download.py — register job on enqueue

In `start_download()`, after enqueuing and setting the dedup mapping, also register the job in the session jobs hash:

```python
from app.core.queue import register_job_for_session

# After: set_active_job_for_session(x_session_id, url, quality, job.id)
register_job_for_session(x_session_id, job.id, url)
```

When dedup returns an existing active job, also register it (in case it was cleared):
```python
# In the "already_queued" return path
register_job_for_session(x_session_id, existing_job_id, url)
```

### 3. download.py — new endpoint: GET /api/jobs

```python
@router.get("/jobs")
def list_jobs(x_session_id: str | None = Header(None)):
    """List all jobs for the current session with their status."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")

    jobs = get_jobs_for_session(x_session_id)
    result = []
    for job_info in jobs:
        job_id = job_info["job_id"]
        try:
            job = Job.fetch(job_id, connection=get_redis())
            status = job.get_status()
            result.append({
                "job_id": job_id,
                "url": job_info["url"],
                "status": status,
                "result": job.result,
                "error": str(job.exc_info) if job.exc_info else None,
            })
        except NoSuchJobError:
            # Job expired from Redis — clear from session and skip
            clear_job_for_session(x_session_id, job_id)
    return {"jobs": result}
```

### 4. download.py — new endpoint: DELETE /api/jobs/{job_id}

```python
@router.delete("/jobs/{job_id}")
def dismiss_job(job_id: str, x_session_id: str | None = Header(None)):
    """Dismiss a job from the session's job list."""
    if not x_session_id:
        raise HTTPException(status_code=400, detail="X-Session-ID header required")
    clear_job_for_session(x_session_id, job_id)
    return {"deleted": job_id}
```

### 5. files.py — clear job on serve-then-delete

In `download_file()`'s `_cleanup()` function, after deleting the file and clearing the file mapping, also clear the job from the session jobs hash. But we don't have the job_id in the file download context — we need to look it up.

Option A: Store job_id -> filename mapping in Redis when the job completes.
Option B (simpler): After serve-then-delete, clear ALL jobs from the session that have no remaining files. Since a job can produce multiple files, check if the session has any files left; if not, clear all jobs.

Actually, the simplest approach: don't auto-clear jobs from the session on file download. Instead, the frontend auto-dismisses the JobStatusCard after the file is downloaded (it already does this — 3-second timeout). The frontend calls `DELETE /api/jobs/{job_id}` when dismissing.

This keeps the backend simple — no reverse lookup from filename to job_id.

### 6. files.py — clear jobs on purge

In `_purge_old_files()`, when purging a session's files, also clear the jobs hash for that session if all files are purged:

```python
from app.core.queue import clear_all_jobs_for_session

# At the end of _purge_old_files, if all files were purged:
if delete and not get_files_for_session(session_id):
    clear_all_jobs_for_session(session_id)
```

## Frontend Changes

### 7. api.ts — new functions

```typescript
/** GET /api/jobs — list all jobs for the current session. */
export async function getJobs(): Promise<SessionJob[]> {
  const res = await fetch(`${API_BASE}/api/jobs`, {
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
  const data = await res.json() as { jobs: SessionJob[] };
  return data.jobs;
}

/** DELETE /api/jobs/{job_id} — dismiss a job from the session. */
export async function dismissJob(jobId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/jobs/${jobId}`, {
    method: "DELETE",
    headers: _headers(),
  });
  if (!res.ok) {
    const detail = await extractError(res);
    throw new ApiError(res.status, detail);
  }
}
```

### 8. types.ts — new type

```typescript
export type JobStatus = "queued" | "started" | "finished" | "failed";

export interface SessionJob {
  job_id: string;
  url: string;
  status: JobStatus;
  result: JobResult | null;
  error: string | null;
}
```

### 9. App.tsx — restore jobs on mount

```typescript
import { fetchVideoInfo, startDownload, getJobStatus, getJobs, dismissJob, ApiError } from "./lib/api";

// On mount, restore jobs from the backend
useEffect(() => {
  getJobs()
    .then((restoredJobs) => {
      setJobs(restoredJobs.map((j) => ({ jobId: j.job_id, url: j.url })));
    })
    .catch(() => {
      // Silently fail — jobs just won't be restored
    });
}, []);
```

### 10. App.tsx — update handleDismissJob to call backend

```typescript
const handleDismissJob = useCallback(async (jobId: string) => {
  setJobs((prev) => prev.filter((j) => j.jobId !== jobId));
  try {
    await dismissJob(jobId);
  } catch {
    // Silently fail — job is already removed from UI
  }
}, []);
```

### 11. JobStatusCard.tsx — auto-dismiss calls backend

When the file is downloaded and the card auto-dismisses after 3 seconds, it calls `onDismiss(jobId)` which now triggers the backend `DELETE /api/jobs/{job_id}`. This removes the job from the session so it doesn't reappear on refresh.

No changes needed to JobStatusCard itself — it already calls `onDismiss(jobId)`. The parent App.tsx handles the backend call.

## Data Flow

### Page load / refresh
```
User loads page
  -> App mounts
  -> GET /api/jobs (X-Session-ID header)
  -> Backend: HGETALL ytdlp:session:{session_id}:jobs
  -> For each job: Job.fetch(job_id) -> get status
  -> Return [{job_id, url, status, result}, ...]
  -> App sets jobs state -> JobStatusCards render
  -> Each JobStatusCard polls as normal (existing behavior)
```

### New download
```
User clicks Download
  -> POST /api/download
  -> Backend: enqueue job, set dedup, register_job_for_session(session_id, job.id, url)
  -> Return job_id
  -> App adds job to state
  -> JobStatusCard renders and polls
```

### File download + auto-dismiss
```
User clicks filename in JobStatusCard
  -> GET /api/files/{filename} -> file served + deleted (existing)
  -> JobStatusCard shows "downloaded" checkmark
  -> 3-second timeout -> onDismiss(jobId)
  -> App removes job from state
  -> DELETE /api/jobs/{job_id} -> backend clears from session hash
  -> On refresh, job is gone (file already downloaded and deleted)
```

### Manual dismiss
```
User clicks X on JobStatusCard
  -> onDismiss(jobId)
  -> App removes job from state
  -> DELETE /api/jobs/{job_id} -> backend clears from session hash
```

### Purge
```
POST /api/purge
  -> Purge old files from session dir
  -> If session has no files remaining: clear_all_jobs_for_session(session_id)
  -> On refresh, purged jobs are gone
```

### Cross-session isolation
```
Session A has jobs [job1, job2]
Session B has jobs [job3]
  -> GET /api/jobs with X-Session-ID: A -> returns [job1, job2]
  -> GET /api/jobs with X-Session-ID: B -> returns [job3]
  -> Session A cannot see Session B's jobs (different Redis hash key)
```

## Implementation Order

1. **queue.py** — add session-jobs helpers (`register_job_for_session`, `get_jobs_for_session`, `clear_job_for_session`, `clear_all_jobs_for_session`)
2. **download.py** — call `register_job_for_session` in `start_download()` (both new job and dedup paths)
3. **download.py** — add `GET /api/jobs` endpoint
4. **download.py** — add `DELETE /api/jobs/{job_id}` endpoint
5. **files.py** — clear jobs on purge when session has no files remaining
6. **Frontend types.ts** — add `SessionJob` type
7. **Frontend api.ts** — add `getJobs()` and `dismissJob()` functions
8. **Frontend App.tsx** — restore jobs on mount, update `handleDismissJob` to call backend
9. **Backend tests** — tests for new queue helpers, GET /api/jobs, DELETE /api/jobs/{job_id}
10. **Frontend tests** — tests for `getJobs()`, `dismissJob()`, job restoration on mount
11. **Run all tests, verify, git commit**

## Test Changes

### Backend — Add

**queue.py tests:**
- `test_register_job_for_session_adds_to_hash`
- `test_get_jobs_for_session_returns_registered_jobs`
- `test_get_jobs_for_session_returns_empty_for_unknown_session`
- `test_clear_job_for_session_removes_one_job`
- `test_clear_all_jobs_for_session_removes_all`
- `test_get_jobs_for_session_decodes_bytes`

**download.py tests:**
- `test_start_download_registers_job_for_session` — verify `register_job_for_session` is called
- `test_start_download_dedup_registers_existing_job` — dedup path also registers
- `test_list_jobs_returns_session_jobs` — GET /api/jobs returns jobs with status
- `test_list_jobs_returns_400_without_session_header`
- `test_list_jobs_clears_expired_jobs` — jobs that throw NoSuchJobError are removed from session
- `test_dismiss_job_removes_from_session` — DELETE /api/jobs/{job_id} clears the hash entry
- `test_dismiss_job_returns_400_without_session_header`
- `test_dismiss_job_returns_404_for_unknown_job` — job not in session, return 404 or just 200

**files.py tests:**
- `test_purge_clears_jobs_when_no_files_remaining`

### Frontend — Add

**api.test.ts:**
- `test_getJobs_calls_correct_endpoint`
- `test_getJobs_sends_session_header`
- `test_dismissJob_calls_delete_endpoint`
- `test_dismissJob_sends_session_header`

**App.test.tsx:**
- `test_restores_jobs_on_mount` — mock `getJobs` returns jobs, verify they render
- `test_dismiss_job_calls_backend` — clicking X calls `dismissJob`
- `test_restored_jobs_show_correct_url` — restored job cards display the URL

### Backend — Update
- `test_start_download_enqueues_job` — verify `register_job_for_session` is also called
- `test_start_download_dedup_returns_existing_job` — verify `register_job_for_session` is called on dedup path

## Edge Cases

1. **Job expired from RQ but still in session hash:** `GET /api/jobs` catches `NoSuchJobError`, clears the stale entry from the hash, and skips it in the response. The frontend never sees it.

2. **User refreshes during active download:** Job is in session hash. `GET /api/jobs` returns it with status "started". JobStatusCard resumes polling. When the job finishes, the download link appears.

3. **User downloads file then refreshes before auto-dismiss:** The file is already deleted (serve-then-delete). The job is still in the session hash. On refresh, `GET /api/jobs` returns the job with status "finished" but the file is gone. When the user clicks the download link, the backend returns 404 "File not found". The user can dismiss the card manually. To handle this more gracefully, the `GET /api/jobs` endpoint could check if the files still exist and include a `files_available` flag — but this is optional for v1.

4. **Multiple jobs for the same video at different qualities:** Each is a separate job_id in the session hash. Both appear as separate JobStatusCards.

5. **Session hash grows unbounded:** Jobs are cleared on dismiss, file download (via frontend auto-dismiss), and purge. The 3-hour purge is the safety net. No TTL needed on the jobs hash since it's actively managed.

## File Change Summary

| File | Change |
|------|--------|
| backend/app/core/queue.py | +`_session_jobs_key()`, +`register_job_for_session()`, +`get_jobs_for_session()`, +`clear_job_for_session()`, +`clear_all_jobs_for_session()` |
| backend/app/api/download.py | +`register_job_for_session` call in `start_download()`, +`GET /api/jobs`, +`DELETE /api/jobs/{job_id}` |
| backend/app/api/files.py | +`clear_all_jobs_for_session` call in `_purge_old_files()` when session is empty |
| frontend/src/types.ts | +`SessionJob` interface |
| frontend/src/lib/api.ts | +`getJobs()`, +`dismissJob()` |
| frontend/src/App.tsx | +`useEffect` to restore jobs on mount, update `handleDismissJob` to call `dismissJob()` |
| backend/tests/test_queue.py | +6 tests for session-jobs helpers |
| backend/tests/test_download_api.py | +8 tests for GET /api/jobs and DELETE /api/jobs/{job_id} |
| backend/tests/test_files_api.py | +1 test for purge clearing jobs |
| frontend/tests/api.test.ts | +4 tests for getJobs and dismissJob |
| frontend/tests/App.test.tsx | +3 tests for job restoration |