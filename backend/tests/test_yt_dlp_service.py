"""
Tests for app.core.yt_dlp_service — extract_info, download_video, get_version, update_yt_dlp,
parse_video_id, remove_from_archive.

Mocks yt-dlp's YoutubeDL so no network calls are made.
yt-dlp uses YoutubeDL as a context manager (`with ... as ydl:`),
so we configure __enter__ to return the mock itself.
"""

import os
import tempfile
from unittest.mock import patch, MagicMock, call


def _make_fake_ydl(extract_info_return=None, fire_hook=True):
    """Create a MagicMock that works as a context manager.

    By default, the download mock fires a progress hook so that download_video
    captures a file and does NOT enter the _recover_files_from_disk fallback.
    Set fire_hook=False to simulate an archive skip (no hooks fired).
    """
    ydl = MagicMock()
    ydl.__enter__.return_value = ydl
    ydl.__exit__.return_value = None
    if extract_info_return is not None:
        ydl.extract_info.return_value = extract_info_return

    if fire_hook:
        def fake_download(urls):
            # Fire the progress hook so download_video captures a file
            # and doesn't fall into _recover_files_from_disk.
            # The hook is in the opts passed to YoutubeDL(), accessible
            # via the mock's constructor call args.
            import app.core.yt_dlp_service as svc
            # Find the download opts (they have progress_hooks)
            for call in svc.yt_dlp.YoutubeDL.call_args_list:
                opts = call[0][0]
                if isinstance(opts, dict) and "progress_hooks" in opts:
                    hook = opts["progress_hooks"][0]
                    hook({"status": "finished",
                          "filepath": "/app/downloads/Test [abc123].mp4"})
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


def test_extract_info_does_not_include_archive_opt():
    """extract_info should NOT include download_archive (only download_video needs it)."""
    fake_ydl = _make_fake_ydl(extract_info_return={})

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import extract_info
        extract_info("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "download_archive" not in opts


# --- download_video ---

def test_download_video_calls_yt_dlp_download():
    """download_video should call YoutubeDL.download with the URL."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video", session_id="test-session-123")

    fake_ydl.download.assert_called_once_with(["https://example.com/video"])
    assert result["status"] == "completed"
    assert result["url"] == "https://example.com/video"
    assert "files" in result
    assert isinstance(result["files"], list)


def test_download_video_uses_default_format():
    """download_video should use DEFAULT_FORMAT when no format_str given."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == "bestvideo+bestaudio/best"


def test_download_video_audio_only_overrides_format():
    """audio_only=True should use AUDIO_FORMAT regardless of format_str."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", format_str="137+251", audio_only=True)

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == "bestaudio/best"


def test_download_video_custom_format():
    """Custom format_str should be used when audio_only is False."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", format_str="137+140")

    opts = mock_cls.call_args[0][0]
    assert opts["format"] == "137+140"


def test_download_video_custom_output_template():
    """Custom output_template should be appended to DOWNLOAD_DIR."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
         patch("app.core.yt_dlp_service.DOWNLOAD_DIR", "/app/downloads"):
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video", output_template="%(uploader)s/%(title)s.%(ext)s")

    opts = mock_cls.call_args[0][0]
    assert opts["outtmpl"] == "/app/downloads/%(uploader)s/%(title)s.%(ext)s"


def test_download_video_default_output_template():
    """No output_template should use DEFAULT_OUTPUT_TEMPLATE."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls, \
         patch("app.core.yt_dlp_service.DOWNLOAD_DIR", "/app/downloads"):
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert opts["outtmpl"] == "/app/downloads/%(title)s [%(id)s].%(ext)s"


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


def test_download_video_includes_archive_opt():
    """download_video should include download_archive in ydl_opts."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "download_archive" in opts


def test_download_video_includes_progress_hooks():
    """download_video should register progress_hooks and postprocessor_hooks to capture filenames."""
    fake_ydl = _make_fake_ydl()

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        download_video("https://example.com/video")

    opts = mock_cls.call_args[0][0]
    assert "progress_hooks" in opts
    assert "postprocessor_hooks" in opts
    assert isinstance(opts["progress_hooks"], list)
    assert isinstance(opts["postprocessor_hooks"], list)
    assert len(opts["progress_hooks"]) == 1
    assert len(opts["postprocessor_hooks"]) == 1
    # Both hooks should be callable
    assert callable(opts["progress_hooks"][0])
    assert callable(opts["postprocessor_hooks"][0])


def test_download_video_captures_finished_file():
    """progress_hooks hook should capture filepath when status is finished."""
    fake_ydl = _make_fake_ydl(fire_hook=False)

    def fake_download(urls):
        opts = mock_cls.call_args[0][0]
        progress_hook = opts["progress_hooks"][0]
        progress_hook({"status": "finished", "filepath": "/app/downloads/Test Video [abc123].mp4"})

    fake_ydl.download.side_effect = fake_download

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    assert result["files"] == ["Test Video [abc123].mp4"]


def test_download_video_captures_multiple_files():
    """hooks should capture multiple files (e.g. video + audio merge)."""
    fake_ydl = _make_fake_ydl(fire_hook=False)

    def fake_download(urls):
        opts = mock_cls.call_args[0][0]
        progress_hook = opts["progress_hooks"][0]
        postprocessor_hook = opts["postprocessor_hooks"][0]
        # progress hooks fire for intermediate downloads
        progress_hook({"status": "finished", "filepath": "/app/downloads/video.mp4"})
        progress_hook({"status": "finished", "filepath": "/app/downloads/audio.webm"})
        # postprocessor hook fires for the final merged file
        postprocessor_hook({"status": "finished", "filepath": "/app/downloads/Test Video [abc123].mp4"})

    fake_ydl.download.side_effect = fake_download

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl) as mock_cls:
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    # Should capture all files (intermediate + final), deduplicated
    assert len(result["files"]) == 3
    assert "video.mp4" in result["files"]
    assert "audio.webm" in result["files"]
    assert "Test Video [abc123].mp4" in result["files"]


def test_download_video_no_files_when_hook_not_called():
    """files should be empty list when no finished hooks are fired."""
    fake_ydl = _make_fake_ydl(fire_hook=False)

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.yt_dlp_service._recover_files_from_disk", return_value=[]):
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    assert result["files"] == []


# --- _recover_files_from_disk ---

def test_recover_files_from_disk_finds_matching_file():
    """_recover_files_from_disk should find a file matching * [video_id].* on disk."""
    from app.core.yt_dlp_service import _recover_files_from_disk

    tmpdir = tempfile.mkdtemp()
    try:
        # Create a file matching the pattern
        filepath = os.path.join(tmpdir, "My Video [abc123].mp4")
        with open(filepath, "w") as f:
            f.write("fake")

        fake_ydl = _make_fake_ydl(extract_info_return={"id": "abc123", "title": "My Video"})

        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
             patch("app.core.yt_dlp_service.DOWNLOAD_DIR", tmpdir):
            result = _recover_files_from_disk("https://example.com/video")

        assert result == ["My Video [abc123].mp4"]
    finally:
        import shutil
        shutil.rmtree(tmpdir)


def test_recover_files_from_disk_returns_empty_when_no_file():
    """_recover_files_from_disk should return [] when no matching file exists."""
    from app.core.yt_dlp_service import _recover_files_from_disk

    tmpdir = tempfile.mkdtemp()
    try:
        fake_ydl = _make_fake_ydl(extract_info_return={"id": "abc123", "title": "My Video"})

        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
             patch("app.core.yt_dlp_service.DOWNLOAD_DIR", tmpdir):
            result = _recover_files_from_disk("https://example.com/video")

        assert result == []
    finally:
        import shutil
        shutil.rmtree(tmpdir)


def test_recover_files_from_disk_skips_hidden_files():
    """_recover_files_from_disk should skip hidden files like .ytdlp-archive.txt."""
    from app.core.yt_dlp_service import _recover_files_from_disk

    tmpdir = tempfile.mkdtemp()
    try:
        # Create a hidden file with the video ID pattern (should be skipped)
        open(os.path.join(tmpdir, ".ytdlp-archive.txt"), "w").close()
        # Create the actual video file
        filepath = os.path.join(tmpdir, "My Video [abc123].mp4")
        with open(filepath, "w") as f:
            f.write("fake")

        fake_ydl = _make_fake_ydl(extract_info_return={"id": "abc123", "title": "My Video"})

        with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
             patch("app.core.yt_dlp_service.DOWNLOAD_DIR", tmpdir):
            result = _recover_files_from_disk("https://example.com/video")

        assert result == ["My Video [abc123].mp4"]
        assert len(result) == 1
    finally:
        import shutil
        shutil.rmtree(tmpdir)


def test_recover_files_from_disk_returns_empty_when_extract_info_fails():
    """_recover_files_from_disk should return [] when extract_info raises."""
    from app.core.yt_dlp_service import _recover_files_from_disk

    fake_ydl = _make_fake_ydl()
    fake_ydl.extract_info.side_effect = Exception("Network error")

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        result = _recover_files_from_disk("https://example.com/video")

    assert result == []


def test_recover_files_from_disk_returns_empty_when_no_video_id():
    """_recover_files_from_disk should return [] when info has no 'id' field."""
    from app.core.yt_dlp_service import _recover_files_from_disk

    fake_ydl = _make_fake_ydl(extract_info_return={"title": "No ID Video"})

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl):
        result = _recover_files_from_disk("https://example.com/video")

    assert result == []


def test_download_video_recovers_files_on_archive_skip():
    """download_video should recover files from disk when hooks don't fire (archive skip)."""
    fake_ydl = _make_fake_ydl(fire_hook=False)

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.yt_dlp_service._recover_files_from_disk",
               return_value=["Test Video [abc123].mp4"]) as mock_recover:
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    assert result["files"] == ["Test Video [abc123].mp4"]
    mock_recover.assert_called_once_with("https://example.com/video")


def test_download_video_does_not_recover_when_hooks_fired():
    """download_video should NOT call _recover_files_from_disk when hooks captured files."""
    fake_ydl = _make_fake_ydl(fire_hook=True)

    with patch("app.core.yt_dlp_service.yt_dlp.YoutubeDL", return_value=fake_ydl), \
         patch("app.core.yt_dlp_service._recover_files_from_disk",
               return_value=["should not be used"]) as mock_recover:
        from app.core.yt_dlp_service import download_video
        result = download_video("https://example.com/video")

    # The hook fired and captured "Test [abc123].mp4"
    assert result["files"] == ["Test [abc123].mp4"]
    mock_recover.assert_not_called()


# --- get_version ---

def test_get_version_returns_string():
    """get_version should return a non-empty string."""
    with patch("app.core.yt_dlp_service.yt_dlp.version.__version__", "2026.07.04"):
        from app.core.yt_dlp_service import get_version
        result = get_version()
    assert isinstance(result, str)
    assert result == "2026.07.04"


# --- update_yt_dlp ---

def test_update_yt_dlp_success():
    """update_yt_dlp should return success with old and new version on pip success."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "Successfully installed yt-dlp-2026.07.04"
    fake_result.stderr = ""

    with patch("app.core.yt_dlp_service.subprocess.run", return_value=fake_result) as mock_run, \
         patch("app.core.yt_dlp_service.get_version", side_effect=["2026.06.09", "2026.07.04"]), \
         patch("app.core.yt_dlp_service.importlib.reload"):
        from app.core.yt_dlp_service import update_yt_dlp
        result = update_yt_dlp()

    assert result["status"] == "success"
    assert result["old_version"] == "2026.06.09"
    assert result["new_version"] == "2026.07.04"
    assert "Successfully installed" in result["stdout"]
    # Verify pip was called with the right command
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "pip" in cmd
    assert "install" in cmd
    assert "--upgrade" in cmd
    assert "yt-dlp[default,curl-cffi]" in cmd


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


def test_update_yt_dlp_uses_sys_executable():
    """update_yt_dlp should use sys.executable for pip invocation."""
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "up to date"
    fake_result.stderr = ""

    with patch("app.core.yt_dlp_service.subprocess.run", return_value=fake_result) as mock_run, \
         patch("app.core.yt_dlp_service.get_version", return_value="2026.07.04"), \
         patch("app.core.yt_dlp_service.importlib.reload"):
        from app.core.yt_dlp_service import update_yt_dlp
        update_yt_dlp()

    cmd = mock_run.call_args[0][0]
    # First element should be sys.executable (the python binary path)
    assert cmd[0] == "python3" or cmd[0].endswith("python") or cmd[0].endswith("python3")


# --- parse_video_id ---

def test_parse_video_id_extracts_from_filename():
    """parse_video_id should extract the ID from 'My Video [abc123].mp4'."""
    from app.core.yt_dlp_service import parse_video_id
    assert parse_video_id("My Video [abc123].mp4") == "abc123"


def test_parse_video_id_returns_none_for_no_brackets():
    """parse_video_id should return None when no brackets in filename."""
    from app.core.yt_dlp_service import parse_video_id
    assert parse_video_id("video.mp4") is None


def test_parse_video_id_returns_none_for_empty_string():
    """parse_video_id should return None for empty string."""
    from app.core.yt_dlp_service import parse_video_id
    assert parse_video_id("") is None


def test_parse_video_id_extracts_from_audio_file():
    """parse_video_id should extract the ID from 'Song [xyz789].webm'."""
    from app.core.yt_dlp_service import parse_video_id
    assert parse_video_id("Song [xyz789].webm") == "xyz789"


# --- remove_from_archive ---

def test_remove_from_archive_removes_matching_entry():
    """remove_from_archive should remove lines containing the video_id."""
    from app.core.yt_dlp_service import remove_from_archive

    tmpdir = tempfile.mkdtemp()
    archive_path = os.path.join(tmpdir, "archive.txt")
    with open(archive_path, "w") as f:
        f.write("youtube abc123\n")
        f.write("youtube def456\n")
        f.write("youtube ghi789\n")

    with patch("app.core.yt_dlp_service.ARCHIVE_FILE", archive_path):
        remove_from_archive("def456")

    with open(archive_path, "r") as f:
        lines = f.readlines()

    os.unlink(archive_path)
    os.rmdir(tmpdir)

    assert len(lines) == 2
    assert "abc123" in lines[0]
    assert "ghi789" in lines[1]
    assert not any("def456" in line for line in lines)


def test_remove_from_archive_handles_missing_file():
    """remove_from_archive should not crash when archive file doesn't exist."""
    from app.core.yt_dlp_service import remove_from_archive

    with patch("app.core.yt_dlp_service.ARCHIVE_FILE", "/nonexistent/path/archive.txt"):
        # Should not raise
        remove_from_archive("abc123")


def test_remove_from_archive_preserves_other_entries():
    """remove_from_archive should only remove matching IDs, preserving others."""
    from app.core.yt_dlp_service import remove_from_archive

    tmpdir = tempfile.mkdtemp()
    archive_path = os.path.join(tmpdir, "archive.txt")
    with open(archive_path, "w") as f:
        f.write("youtube abc123\n")
        f.write("youtube def456\n")
        f.write("youtube ghi789\n")

    with patch("app.core.yt_dlp_service.ARCHIVE_FILE", archive_path):
        remove_from_archive("abc123")

    with open(archive_path, "r") as f:
        lines = f.readlines()

    os.unlink(archive_path)
    os.rmdir(tmpdir)

    assert len(lines) == 2
    assert not any("abc123" in line for line in lines)
    assert any("def456" in line for line in lines)
    assert any("ghi789" in line for line in lines)


def test_remove_from_archive_no_op_when_id_not_found():
    """remove_from_archive should leave file unchanged when ID not in archive."""
    from app.core.yt_dlp_service import remove_from_archive

    tmpdir = tempfile.mkdtemp()
    archive_path = os.path.join(tmpdir, "archive.txt")
    original_content = "youtube abc123\nyoutube def456\n"
    with open(archive_path, "w") as f:
        f.write(original_content)

    with patch("app.core.yt_dlp_service.ARCHIVE_FILE", archive_path):
        remove_from_archive("not_in_archive")

    with open(archive_path, "r") as f:
        content = f.read()

    os.unlink(archive_path)
    os.rmdir(tmpdir)

    assert content == original_content