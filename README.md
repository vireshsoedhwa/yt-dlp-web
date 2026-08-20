# yt-dlp Web

A Docker Compose web app wrapping [yt-dlp](https://github.com/yt-dlp/yt-dlp) with a FastAPI backend, React + Vite frontend, and RQ job queue.

Features session-based file isolation, per-session rate limiting, API key authentication for the self-update endpoint, and a background purger for automatic cleanup of stale downloads.

## Quick Start

### Development (HMR, hot reload, exposed ports)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

- Frontend (Vite HMR): http://localhost:3000
- Backend API: http://localhost:8000
- Redis: localhost:6379

### Production (built assets, Caddy TLS, nginx API proxy)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

- App: https://neckflix.top (Caddy with auto Let's Encrypt)

## Architecture

### Dev mode

```
docker-compose.yml (base) + docker-compose.dev.yml (overrides)
├── redis        :6379  — RQ broker
├── backend      :8000  — FastAPI + uvicorn --reload (source mounted)
├── worker       —      — RQ worker (source mounted)
└── frontend    :3000  — Vite dev server with HMR (source mounted)
                       — node_modules in named volume (survives restarts)
```

### Production mode

```
docker-compose.yml (base) + docker-compose.prod.yml (overrides)
├── redis        —      — RQ broker
├── backend      —      — FastAPI + uvicorn (internal only, not exposed)
├── worker       —      — RQ worker
├── frontend     :3000  — nginx serving built Vite assets + reverse-proxy /api/* to backend
└── caddy        :80/:443 — TLS termination, proxies everything to frontend
```

## Structure

```
yt-dlp-web/
├── docker-compose.yml              # Base: redis, backend, worker
├── docker-compose.dev.yml          # Dev: Vite HMR, source mounts, exposed ports
├── docker-compose.prod.yml         # Prod: caddy, built assets, no mounts
├── caddy/
│   └── Caddyfile                  # TLS termination + reverse proxy to frontend
├── backend/
│   ├── Dockerfile                  # Python 3.12 + ffmpeg + yt-dlp
│   ├── requirements.txt            # yt-dlp + FastAPI + RQ + Redis
│   ├── requirements-dev.txt        # + pytest, httpx
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── worker.py               # RQ worker entry point
│   │   ├── api/
│   │   │   ├── info.py             # POST /api/info — extract metadata (sync)
│   │   │   ├── download.py         # POST /api/download — enqueue job (dedup + session-aware)
│   │   │   ├── update.py           # GET/POST /api/update — check/upgrade yt-dlp version
│   │   │   └── files.py            # GET /api/files, POST /api/purge, GET /api/purge/preview
│   │   ├── core/
│   │   │   ├── config.py           # Settings (download dir, Redis URL, queue, session, rate limits, API key)
│   │   │   ├── queue.py            # Redis + Queue + dedup + session-to-file mapping + rate limiting
│   │   │   ├── files_service.py    # Session file paths, filename validation, serve-then-delete cleanup
│   │   │   └── yt_dlp_service.py   # yt-dlp wrapper + session validation + metadata capture + self-update
│   │   └── models/
│   │       └── schemas.py          # Pydantic request/response models
│   └── tests/                      # 125 tests (pytest, all mocked)
├── frontend/
│   ├── Dockerfile                  # Multi-stage: dev target (Vite HMR) / prod target (nginx)
│   ├── nginx-frontend.conf         # nginx config for frontend container (prod)
│   ├── package.json
│   ├── vite.config.ts              # Vite + tailwind plugin + proxy /api
│   ├── vitest.config.ts            # Vitest + jsdom + Testing Library
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx                # React entry point
│   │   ├── App.tsx                 # Main app: URL -> info -> download -> job status
│   │   ├── types.ts                # Shared TypeScript types
│   │   ├── index.css               # Tailwind 4 + dark theme
│   │   ├── lib/
│   │   │   ├── api.ts              # API client (fetchVideoInfo, startDownload, getJobStatus)
│   │   │   └── constants.ts        # Shared constants (POLL_INTERVAL_MS, CARD_TTL_MS)
│   │   └── components/
│   │       ├── UrlInput.tsx        # URL text input + submit button
│   │       ├── VideoInfoCard.tsx   # Metadata display + download controls
│   │       ├── JobStatusCard.tsx   # Polling job status with badge
│   │       └── ErrorMessage.tsx    # Inline error banner
│   └── tests/                      # 71 tests (Vitest + Testing Library, all mocked)
├── caddy/
│   └── Caddyfile                  # TLS termination + reverse proxy to frontend
└── downloads/                      # Shared volume for downloaded videos
```

## Services

| Service  | Dev Port | Prod Port | Purpose                              |
|----------|----------|-----------|--------------------------------------|
| redis    | 6379     | —         | Redis — RQ broker + job persistence  |
| backend  | 8000     | —         | FastAPI — API server (internal only) |
| worker   | —        | —         | RQ worker — runs yt-dlp downloads    |
| frontend | 3000     | 3000      | Dev: Vite HMR / Prod: nginx + API proxy |
| caddy    | —        | 80/443    | TLS termination (prod entry point)   |

## Running Tests

### Backend (125 tests)

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -v
```

### Frontend (71 tests)

```bash
cd frontend
npm install
npx vitest run
```

## API Endpoints

- `GET  /`                      — health check
- `POST /api/info`              — `{ "url": "..." }` -> video metadata (synchronous, rate-limited)
- `POST /api/download`         — `{ "url": "...", "format": "...", "audio_only": false }` -> `{ "job_id": "...", "status": "queued" }` (requires `X-Session-ID`, rate-limited)
- `GET  /api/download/{job_id}` — check download status (queued/started/finished/failed + result)
- `GET  /api/update`            — return currently installed yt-dlp version
- `POST /api/update`            — self-upgrade yt-dlp to latest PyPI version (requires `X-API-Key` header if `UPDATE_API_KEY` is set)
- `GET  /api/files`             — list downloaded files for the current session (requires `X-Session-ID` header)
- `GET  /api/files/{filename}`  — download a file, deleted after serving (requires `X-Session-ID` header)
- `POST /api/purge`             — delete files older than 3 hours for the current session
- `GET  /api/purge/preview`     — preview which files would be purged

**Session isolation:** `POST /api/download`, `GET /api/files`, `GET /api/files/{filename}`, `POST /api/purge`, and `GET /api/purge/preview` require an `X-Session-ID` header.

**Rate limiting:** `POST /api/info` and `POST /api/download` are rate-limited per session (or per client IP if no session ID). Defaults: 20 info requests / 10 download requests per 60 seconds. Configurable via `RATE_LIMIT_INFO`, `RATE_LIMIT_DOWNLOADS`, and `RATE_LIMIT_WINDOW_SECONDS` environment variables.

**API key auth:** `POST /api/update` requires an `X-API-Key` header matching `UPDATE_API_KEY` when that environment variable is set. If unset, the endpoint is open (useful for dev).

## Tech Stack

**Backend:** Python 3.12, FastAPI, RQ (Redis Queue), yt-dlp, ffmpeg, Pydantic
**Frontend:** React 19, TypeScript, Vite 7, Tailwind CSS 4, Vitest, Testing Library
**Infra:** Docker Compose, Redis 7, nginx

## Notes

- ffmpeg is installed in the backend container for format merging (shared by worker since same image)
- The `downloads/` directory is a shared volume across backend, worker, and nginx
- In dev, `node_modules` lives in a named Docker volume so it survives container restarts
- yt-dlp is pinned to `>=2026.07.04` in requirements.txt. When YouTube changes anti-bot measures and downloads start failing with 403, use `POST /api/update` to self-upgrade yt-dlp inside the running container without rebuilding
- yt-dlp uses the `android` player client (with `web` fallback) and a realistic User-Agent header to avoid 403 Forbidden errors
- Download archive: yt-dlp maintains a `.ytdlp-archive.txt` file recording video IDs to skip re-downloads
- Dedup: Redis URL-to-job mapping prevents duplicate concurrent downloads of the same URL (MD5 hash, 1h TTL)
- Session isolation: frontend generates a UUID stored in localStorage, sent as `X-Session-ID` header. Backend validates the session ID (alphanumeric + hyphens only) and uses it as a namespace key to isolate files per session, preventing path traversal
- Rate limiting: per-session Redis-based rate limiting on `/api/info` and `/api/download` endpoints (sliding window via `INCR` + `EXPIRE`)
- API key auth: `POST /api/update` requires `X-API-Key` header when `UPDATE_API_KEY` env var is set
- Serve-then-delete: files are deleted after the user downloads them. Hard links allow multiple sessions to share the same downloaded video -- each gets their own file handle, deleted independently. The original is cleaned up when the last session link is removed (via inode link count)
- Fallback purge: files not claimed within 3 hours are purged via `POST /api/purge` (also cleans up orphaned originals and archive entries). A background purger in the worker also runs on a configurable interval
- yt-dlp's "No AI / No LLM" policy applies to upstream contributions — this project wraps yt-dlp as a dependency, not a fork