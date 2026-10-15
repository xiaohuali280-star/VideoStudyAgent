import subprocess
from types import SimpleNamespace

import pytest

from app.core.errors import StudyError
from app.providers.ocr import TesseractOCR


def test_missing_engine_never_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr("app.providers.ocr.shutil.which", lambda _: None)
    with pytest.raises(StudyError, match="OCR_UNAVAILABLE"):
        TesseractOCR().recognize(tmp_path / "frame.png")


def test_tsv_negative_formula_and_separate_stderr(monkeypatch, tmp_path):
    monkeypatch.setattr("app.providers.ocr.shutil.which", lambda _: "tesseract")

    def local(args, **kwargs):
        assert isinstance(args, list) and "shell" not in kwargs
        assert kwargs["capture_output"] and kwargs["timeout"] == 30
        return SimpleNamespace(
            returncode=0,
            stderr=b"secret-diagnostic",
            stdout=(b"level\tleft\ttop\twidth\theight\tconf\ttext\n5\t1\t2\t10\t20\t96\t-0.1\n"),
        )

    monkeypatch.setattr("app.providers.ocr.subprocess.run", local)
    result = TesseractOCR().recognize(tmp_path / "frame.png")
    assert result == [dict(raw_text="-0.1", bbox=(1, 2, 10, 20), confidence=96)]


@pytest.mark.parametrize("timeout", [False, True])
def test_timeout_language_error_sanitized(monkeypatch, tmp_path, timeout):
    monkeypatch.setattr("app.providers.ocr.shutil.which", lambda _: "tesseract")

    def local(args, **kwargs):
        if timeout:
            raise subprocess.TimeoutExpired(args, 30)
        return SimpleNamespace(returncode=1, stdout=b"", stderr=b"never expose this")

    monkeypatch.setattr("app.providers.ocr.subprocess.run", local)
    with pytest.raises(StudyError) as result:
        TesseractOCR().recognize(tmp_path / "frame.png")
    assert result.value.code == ("OCR_TIMEOUT" if timeout else "OCR_FAILED")
    assert "never expose" not in result.value.message


def test_actual_ffmpeg_frames_keep_pts(tmp_path):
    from uuid import uuid4

    from app.core.config import Settings
    from app.db.repository import now
    from app.schemas.study import StudyOptions
    from app.schemas.tasks import InputAsset, Task
    from app.services.media import run_media
    from app.services.storage import ArtifactStore, file_hash
    from app.services.vision import extract_frames

    settings = Settings(_env_file=None, data_dir=tmp_path, ocr_gap_seconds=1)
    task = Task(
        id=uuid4(), title="自建纯色视频", options=StudyOptions(enable_ocr=True), created_at=now()
    )
    key = f"tasks/{task.id}/inputs/video.mp4"
    path = ArtifactStore(tmp_path, None).path(key)
    path.parent.mkdir(parents=True)
    run_media(
        settings.ffmpeg_binary,
        [
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=white:s=64x48:r=10:d=3",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        30,
    )
    asset = InputAsset(
        id=uuid4(),
        task_id=task.id,
        kind="video",
        original_name="fixture.mp4",
        storage_key=key,
        sha256=file_hash(path),
        size_bytes=path.stat().st_size,
    )
    frames = extract_frames(task, asset, settings)
    assert [f.timestamp_ms for f in frames] == [0, 1000, 2000]
    assert all((f.width, f.height) == (64, 48) for f in frames)


def test_tesseract_version_and_tsv_lines_preserve_raw_symbols(monkeypatch, tmp_path):
    monkeypatch.setattr("app.providers.ocr.shutil.which", lambda _: "tesseract")

    def local(args, **kwargs):
        if "--version" in args:
            return SimpleNamespace(returncode=0, stdout=b"tesseract 5.4.1\n", stderr=b"")
        return SimpleNamespace(
            returncode=0,
            stderr=b"",
            stdout=(
                b"level\tpage_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n"
                b"5\t1\t1\t1\t1\t0\t0\t10\t10\t90\trate\n"
                b"5\t1\t1\t1\t1\t20\t0\t20\t10\t80\t-0.1\n"
            ),
        )

    monkeypatch.setattr("app.providers.ocr.subprocess.run", local)
    provider = TesseractOCR()
    assert provider.version == "tesseract-5.4.1/tsv-v1"
    assert provider.recognize(tmp_path / "f.png") == [
        dict(raw_text="rate -0.1", bbox=(0, 0, 40, 10), confidence=85)
    ]
