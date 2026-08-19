"""
Tests for app.core.yt_dlp_service — extract_info, download_video, get_version, update_yt_dlp.

Mocks yt-dlp's YoutubeDL so no network calls are made.
yt-dlp uses YoutubeDL as a context manager (`with ... as ydl:`),
so we configure __enter__ to return the mock itself.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock, call

from app.core.config import QUALITY_MAP, AUDIO_FORMAT, DEFAULT_OUTPUT_TEMPLATE


def _make_fake_ydl(extract_info_return=None, fire_hook=True):
    """Create a MagicMock that works as a context manager.

    By default, the download mock fires a progress hook so that download_video
    captures a file. Set fire_hook=False to simulate a no-hook scenario.
    """
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.__exit__.return_value = None
    if extract_info_return is not None:
        ydl.extract_info.return_value = extract_info_return

    if fire_hook:
        def fake_download(urls):
            import app.core.yt_dlp_service as svc
            for call_obj in svc.yt_dlp.YoutubeDL.call_args_list:
                opts = call_obj[0][0]
                if isinstance(opts, dict) and "progress_hooks" in opts:
                    hook = opts["progress_hooks"][0]
                    hook({"status": "finished",
                          "filepath": "/app/downloads/.session/test-session/Test [abc123]_1080p.mp4"})
                    break
        ydl.download.side_effect = fake_download

    return ydl


# --- extract_info ---

def test_extract_info_returns_expected_fields(fake_yt_info):
    """extract_info should return title, uploader, duration, thumbnail, formats."""
    fake_ydl = _make_fake_ydl(extract_info_return=fake_yt_info)

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        from app.core.yt_dlp_service import extract_info
        result = extract_info("https://example.com/video")

    assert result["title"] == "Test Video"
    assert result["uploader"] == "Test Channel"
    assert result["duration"] == 120
    assert result["thumbnail"] == "https://example.com/thumb.jpg"
    assert len(result["formats"]) == 2
    # Verify download=False was passed
    fake_ydl.extract_info.assert_called_once_with("https://example.com/video", download=False)


def test_extract_info_handles_missing_fields():
    """extract_info should use defaults for missing metadata fields."""
    fake_ydl = _make_fake_ydl(extract_info_return={})

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        from app.core.yt_dlp_service import extract_info
        result = extract_info("https://example.com/video")

    assert result["title"] == "Unknown"
    assert result["uploader"] is None
    assert result["duration"] is None
    assert result["thumbnail"] is None
    assert result["formats"] == []


def test_extract_info_uses_quiet_opts():
    """extract_info should pass quiet/no_warnings/skip_download to YoutubeDL."""
    fake_ydl = _make_fake_ydl(extract_info_return={})

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import extract_info
        extract_info("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert opts["quiet"] is True
    assert opts["no_warnings"] is True
    assert opts["skip_download"] is True


def test_extract_info_includes_anti_403_opts():
    """extract_info should include extractor_args and http_headers for anti-bot robustness."""
    fake_ydl = _make_fake_ydl(extract_info_return={})

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import extract_info
        extract_info("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "extractor_args" in opts
    assert "youtube" in opts["extractor_args"]
    assert "player_client" in opts["extractor_args"]["youtube"]
    assert "http_headers" in opts
    assert "User-Agent" in opts["http_headers"]


# --- download_video ---

def test_download_video_calls_yt_dlp_download():
    """download_video should call YoutubeDL.download with the URL."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.queue.register_file_for_session"), \
         patch("os.path.isfile", return_value=True):
        from app.core.yt_dlp_service import download_video
        result = download_video(
            "https://example.com/video",
            quality="1080p",
            session_id="test-session-123",
        )

    fake_ydl.download.assert_called_once_with(["https://example.com/video"])
    assert result["status"] == "completed"
    assert result["url"] == "https://example.com/video"
    assert "files" in result
    assert isinstance(result["files"], list)


def test_download_video_uses_default_format():
    """download_video with quality='1080p' should map to QUALITY_MAP['1080p']."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="1080p")

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == QUALITY_MAP["1080p"]


def test_download_video_audio_only_uses_audio_format():
    """audio_only=True should use AUDIO_FORMAT regardless of quality."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="1080p", audio_only=True)

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == AUDIO_FORMAT


def test_download_video_quality_map():
    """quality='720p' should map to QUALITY_MAP['720p']."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="720p")

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == QUALITY_MAP["720p"]


def test_download_video_default_output_template():
    """outtmpl should include SESSION_DIR and session_id when session_id is given."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
         patch("app.core.yt_dlp_service.SESSION_DIR", "/app/downloads/.session"), \
         patch("app.core.queue.register_file_for_session"):
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="1080p", session_id="test-session-123")

    opts = mock_cls.call_args[0][0]
    assert "/app/downloads/.session" in opts["outtmpl"]
    assert "test-session-123" in opts["outtmpl"]


def test_download_video_includes_anti_403_opts():
    """download_video should include extractor_args and http_headers for anti-bot robustness."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "extractor_args" in opts
    assert "youtube" in opts["extractor_args"]
    assert "player_client" in opts["extractor_args"]["youtube"]
    assert "http_headers" in opts
    assert "User-Agent" in opts["http_headers"]


def test_download_video_includes_progress_hooks():
    """download_video should register progress_hooks and post_hooks to capture filenames."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "progress_hooks" in opts
    assert "post_hooks" in opts
    assert isinstance(opts["progress_hooks"], list)
    assert isinstance(opts["post_hooks"], list)
    assert len(opts["progress_hooks"]) == 1
    assert len(opts["post_hooks"]) == 1
    # Both hooks should be callable
    assert callable(opts["progress_hooks"][0])
    assert callable(opts["post_hooks"][0])


def test_download_video_captures_finished_file():
    """progress_hooks hook should capture filepath when status is finished."""
    tmpdir = tempfile.mkdtemp()
    session_dir = os.path.join(tmpdir, "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    # Create the file on disk so the existence filter passes
    filepath = os.path.join(session_dir, "Test Video [abc123]_1080p.mp4")
    with open(filepath, "w") as f:
        f.write("fake")

    fake_ydl = _make_fake_ydl(fire_hook=False)

    def fake_download(urls):
        opts = mock_cls.call_args[0][0]
        progress_hook = opts["progress_hooks"][0]
        progress_hook({"status": "finished", "filepath": filepath})

    fake_ydl.download.side_effect = fake_download

    try:
        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
             patch("app.core.yt_dlp_service.SESSION_DIR", tmpdir), \
             patch("app.core.queue.register_file_for_session"):
            from app.core.yt_dlp_service import download_video
            result = download_video("https://example.com/video", quality="1080p", session_id="test-session-123")

        assert result["files"] == ["Test Video [abc123]_1080p.mp4"]
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_download_video_captures_multiple_files():
    """hooks should capture multiple files (e.g. video + audio merge)."""
    tmpdir = tempfile.mkdtemp()
    session_dir = os.path.join(tmpdir, "test-session-123")
    os.makedirs(session_dir, exist_ok=True)
    # Create files on disk so the existence filter passes
    for name in ["video.mp4", "audio.webm", "Test Video [abc123]_1080p.mp4"]:
        with open(os.path.join(session_dir, name), "w") as f:
            f.write("fake")

    fake_ydl = _make_fake_ydl(fire_hook=False)

    def fake_download(urls):
        opts = mock_cls.call_args[0][0]
        progress_hook = opts["progress_hooks"][0]
        post_hook = opts["post_hooks"][0]
        # progress hooks fire for intermediate downloads
        progress_hook({"status": "finished", "filepath": os.path.join(session_dir, "video.mp4")})
        progress_hook({"status": "finished", "filepath": os.path.join(session_dir, "audio.webm")})
        # post hook fires for the final merged file
        post_hook(os.path.join(session_dir, "Test Video [abc123]_1080p.mp4"))

    fake_ydl.download.side_effect = fake_download

    try:
        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
             patch("app.core.yt_dlp_service.SESSION_DIR", tmpdir), \
             patch("app.core.queue.register_file_for_session"):
            from app.core.yt_dlp_service import download_video
            result = download_video("https://example.com/video", quality="1080p", session_id="test-session-123")

        # Should capture all files (intermediate + final), deduplicated
        assert len(result["files"]) == 3
        assert "video.mp4" in result["files"]
        assert "audio.webm" in result["files"]
        assert "Test Video [abc123]_1080p.mp4" in result["files"]
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_download_video_no_files_when_hook_not_called():
    """files should be empty list when no finished hooks are fired."""
    fake_ydl = _make_fake_ydl(fire_hook=False)

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    assert result["files"] == []


def test_download_video_filename_includes_quality_suffix():
    """outtmpl should include the quality suffix (replacing %(quality)s)."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
         patch("app.core.queue.register_file_for_session"), \
         patch("os.path.isfile", return_value=True):
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="720p", session_id="sess-1")

    opts = mock_cls.call_args[0][0]
    # The %(quality)s placeholder should have been replaced with "720p"
    assert "%(quality)s" not in opts["outtmpl"]
    assert "_720p" in opts["outtmpl"]


def test_download_video_audio_adds_mp3_postprocessor():
    """audio_only=True should add FFmpegExtractAudio postprocessor."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="audio", audio_only=True)

    opts = mock_cls.call_args[0][0]
    assert "postprocessors" in opts
    assert len(opts["postprocessors"]) == 1
    pp = opts["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio"
    assert pp["preferredcodec"] == "mp3"
    assert pp["preferredquality"] == "192"


def test_download_video_no_postprocessor_when_not_audio():
    """audio_only=False should NOT add any postprocessors."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="1080p", audio_only=False)

    opts = mock_cls.call_args[0][0]
    assert "postprocessors" not in opts


def test_download_video_registers_files_for_session():
    """download_video should call register_file_for_session for each downloaded file."""
    tmpdir = tempfile.mkdtemp()
    session_dir = os.path.join(tmpdir, "sess-1")
    os.makedirs(session_dir, exist_ok=True)
    filepath = os.path.join(session_dir, "Test [abc123]_1080p.mp4")
    with open(filepath, "w") as f:
        f.write("fake")

    fake_ydl = _make_fake_ydl(fire_hook=False)

    def fake_download(urls):
        opts = mock_cls.call_args[0][0]
        progress_hook = opts["progress_hooks"][0]
        progress_hook({"status": "finished", "filepath": filepath})

    fake_ydl.download.side_effect = fake_download

    try:
        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
             patch("app.core.yt_dlp_service.SESSION_DIR", tmpdir), \
             patch("app.core.queue.register_file_for_session") as mock_register:
            from app.core.yt_dlp_service import download_video
            result = download_video("https://example.com/video", quality="1080p", session_id="sess-1")

        mock_register.assert_called_once_with("sess-1", "Test [abc123]_1080p.mp4")
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_download_video_does_not_register_files_without_session():
    """download_video should NOT call register_file_for_session when session_id is None."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.queue.register_file_for_session") as mock_register:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", quality="1080p")

    mock_register.assert_not_called()


def test_download_video_result_includes_quality_and_format():
    """download_video result should include quality and format."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.queue.register_file_for_session"), \
         patch("os.path.isfile", return_value=True):
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video", quality="720p", session_id="sess-1")

    assert result["quality"] == "720p"
    assert result["format"] == QUALITY_MAP["720p"]
    assert result["session_id"] == "sess-1"


# --- get_version ---

def test_get_version_returns_string():
    """get_version should return the yt-dlp version string."""
    with patch("app.core.yt_dlp_service.yt_dlp.version.__version__", "2026.07.04"):
        from app.core.yt_dlp_service import get_version
        result = get_version()
    assert result == "2026.07.04"


# --- update_yt_dlp ---

def test_update_yt_dlp_success():
    """update_yt_dlp should return success with old/new versions on successful upgrade."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "Successfully installed yt-dlp-2026.07.04"
    fake_result.stderr = ""

    with patch("app.core.yt_dlp_service.subprocess.run", return_value=fake_result), \
         patch("app.core.yt_dlp_service.importlib.reload"), \
         patch("app.core.yt_dlp_service.get_version", side_effect=["2026.06.09", "2026.07.04"]):
        from app.core.yt_dlp_service import update_yt_dlp
        result = update_yt_dlp()

    assert result["status"] == "success"
    assert result["old_version"] == "2026.06.09"
    assert result["new_version"] == "2026.07.04"
    assert "Successfully" in result["stdout"]


def test_update_yt_dlp_pip_failure():
    """update_yt_dlp should return failed status when pip exits non-zero."""
    fake_result = MagicMock()
    fake_result.returncode = 1
    fake_result.stdout = ""
    fake_result.stderr = "ERROR: Could not install yt-dlp"

    with patch("app.core.yt_dlp_service.subprocess.run", return_value=fake_result), \
         patch("app.core.yt_dlp_service.get_version", return_value="2026.06.09"):
        from app.core.yt_dlp_service import update_yt_dlp
        result = update_yt_dlp()

    assert result["status"] == "failed"
    assert result["old_version"] == "2026.06.09"
    assert "Could not install" in result["error"]
    assert result["returncode"] == 1