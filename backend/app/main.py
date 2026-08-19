"""
Application entry point.

FastAPI app with routes for video info extraction, download queuing (RQ),
and yt-dlp self-updating.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import download, info, update, files

app = FastAPI(
    title="yt-dlp Web",
    description="Web interface for yt-dlp — submit URLs and download videos.",
    version="0.1.0",
)

# Allow requests from the Vite dev server and nginx in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(info.router, prefix="/api", tags=["info"])
app.include_router(download.router, prefix="/api", tags=["download"])
app.include_router(update.router, prefix="/api", tags=["update"])
app.include_router(files.router, prefix="/api", tags=["files"])


@app.get("/")
def health():
    return {"status": "ok", "service": "yt-dlp-web backend"}