import subprocess
import wave
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import StudyError
from app.providers.asr import LocalWhisper, ProcessASR, model_fingerprint
from app.schemas.study import Transcript
from app.services.media import media_binary, probe_video, run_media
from app.services.storage import ArtifactStore
from app.services.subtitles import parse_subtitles
from app.services.transcription import TranscriptService
from tests.test_upload_persistence import SRT, upload


@pytest.mark.parametrize(
    ("extension", "text"),
    [
        ("srt", "1\n00:00:01,234 --> 00:00:02,567\n学习率 -0.1\n"),
        ("vtt", "WEBVTT\n\ncue1\n00:01.234 --> 00:02.567 align:start\n学习率 -0.1\n"),
    ],
)
def test_millisecond_subtitles_and_encoding(tmp_path, extension, text):
    path = tmp_path / f"course.{extension}"
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        path.write_bytes(text.encode(encoding))
        result = parse_subtitles(path, "zh", 10000)
        assert result.segments[0].start_ms == 1234
        assert result.segments[0].end_ms == 2567
        assert "-0.1" in result.segments[0].text


@pytest.mark.parametrize(
    "text",
    [
        "1\n00:00:03,000 --> 00:00:02,000\nbackwards\n",
        "1\n00:99:01,000 --> 00:99:02,000\ninvalid minutes\n",
        "1\n00:00:01,000 --> missing\ninvalid end\n",
        "not a subtitle",
    ],
)
def test_invalid_subtitle_timing_is_not_guessed(tmp_path, text):
    path = tmp_path / "course.srt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(StudyError):
        parse_subtitles(path, "en", 10000)


def test_overlap_sorting_and_duration_limit(tmp_path):
    path = tmp_path / "course.srt"
    path.write_text(
        "2\n00:00:02,000 --> 00:00:04,000\nsecond\n\n1\n00:00:00,000 --> 00:00:03,000\nfirst\n",
        encoding="utf-8",
    )
    result = parse_subtitles(path, "en", 5000)
    assert [s.start_ms for s in result.segments] == [0, 2000]
    with pytest.raises(StudyError, match="DURATION_EXCEEDED"):
        parse_subtitles(path, "en", 3000)


def test_subtitle_cache_is_independent_and_corruption_recomputes(application):
    first = application.state.settings
    task = upload(application).json()
    repo = application.state.repository
    service = TranscriptService(first, repo)
    artifact = service.load_subtitles(repo.get(task["id"]))
    entry = repo.get_cache(artifact.cache_key)
    assert entry.storage_key.startswith("cache/")
    service.store.path(entry.storage_key).write_bytes(b"broken json")
    second_task = repo.get(upload(application).json()["id"])
    result = service.load_subtitles(second_task)
    assert service.store.read_json(result, Transcript).segments[0].end_ms == 2000
    assert service.store.verify(repo.get_cache(result.cache_key)).is_file()


def test_subtitle_priority_blocks_asr(application):
    task = upload(application).json()
    service = TranscriptService(application.state.settings, application.state.repository)
    loaded = application.state.repository.get(task["id"])
    service.load_subtitles(loaded)
    for action in (service.extract_audio, service.transcribe_audio):
        with pytest.raises(StudyError, match="TOOL_PRECONDITION"):
            action(loaded)


def test_b2_forwards_configuration_and_preserves_timestamps(tmp_path):
    model = tmp_path / "tiny"
    model.mkdir()
    (model / "model.bin").write_bytes(b"test-model")
    settings = Settings(_env_file=None, asr_model_path=model, asr_model="tiny", asr_cpu_threads=2)
    received = {}

    def factory(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(
            transcribe=lambda path, **options: (
                iter([SimpleNamespace(start=0.123, end=1.456, text=" course ")]),
                SimpleNamespace(language="en", duration=2.0),
            )
        )

    result = LocalWhisper(settings, factory).transcribe(tmp_path / "audio.wav", "en")
    assert received == {
        "model_size_or_path": str(model.resolve()),
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": 2,
        "local_files_only": True,
    }
    assert result.segments[0].start_ms == 123 and result.segments[0].end_ms == 1456
    before = model_fingerprint(settings)
    (model / "model.bin").write_bytes(b"changed-model")
    assert before != model_fingerprint(settings)


def test_no_speech_and_asr_exceptions_propagate(tmp_path):
    (tmp_path / "model.bin").write_bytes(b"test-model")
    settings = Settings(_env_file=None, asr_model_path=tmp_path)
    model = LocalWhisper(
        settings,
        lambda **_: SimpleNamespace(
            transcribe=lambda *a, **k: (
                [],
                SimpleNamespace(language="en", duration=1.0),
            )
        ),
    )
    with pytest.raises(StudyError, match="EMPTY_TRANSCRIPT"):
        model.transcribe(tmp_path / "audio.wav")

    def fail(*args, **kwargs):
        raise RuntimeError("private-provider-detail")

    model.model.transcribe = fail
    with pytest.raises(StudyError, match="ASR_FAILED") as error:
        model.transcribe(tmp_path / "audio.wav")
    assert "private-provider-detail" not in str(error.value)


def test_asr_child_timeout_is_controlled(tmp_path, monkeypatch):
    (tmp_path / "model.bin").write_bytes(b"test-model")
    settings = Settings(_env_file=None, asr_model_path=tmp_path, asr_timeout=1)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("private path", 1)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(StudyError, match="ASR_TIMEOUT"):
        ProcessASR(settings).transcribe(tmp_path / "audio.wav")


@pytest.fixture
def real_video(tmp_path):
    try:
        media_binary("ffmpeg")
        media_binary("ffprobe")
    except StudyError:
        pytest.skip("FFmpeg/FFprobe not installed; real media integration is unavailable")
    path = tmp_path / "course.mp4"
    run_media(
        "ffmpeg",
        [
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x64:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=500:duration=2",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        30,
    )
    return path


def test_real_media_extracts_normalized_audio(application, real_video):
    task = upload(application, {"video": ("course.mp4", real_video.read_bytes())}).json()
    repo = application.state.repository
    service = TranscriptService(application.state.settings, repo)
    artifact = service.extract_audio(repo.get(task["id"]))
    with wave.open(str(service.store.verify(artifact))) as audio:
        assert audio.getnchannels() == 1 and audio.getframerate() == 16000
        assert audio.getsampwidth() == 2 and audio.getnframes() > 0


def test_video_subtitle_range_and_missing_audio(application, real_video, tmp_path):
    settings = application.state.settings
    task = upload(
        application,
        {"video": ("course.mp4", real_video.read_bytes()), "subtitle": ("course.srt", SRT)},
    ).json()
    service = TranscriptService(settings, application.state.repository)
    assert service.load_subtitles(application.state.repository.get(task["id"]))
    silent = tmp_path / "silent.mp4"
    run_media(
        "ffmpeg",
        ["-v", "error", "-y", "-i", str(real_video), "-an", "-c:v", "copy", str(silent)],
        30,
    )
    with pytest.raises(StudyError, match="NO_AUDIO_TRACK"):
        probe_video(silent, settings)
    assert probe_video(silent, settings, False) == 2000


def test_storage_detects_tampering_and_rejects_traversal(application):
    task = upload(application).json()
    store = ArtifactStore(application.state.settings.data_dir, application.state.repository)
    with pytest.raises(ValueError):
        store.path("../outside")
    asset = application.state.repository.assets(task["id"])[0]
    store.path(asset.storage_key).write_bytes(b"tampered")
    with pytest.raises(StudyError, match="STORAGE_ERROR"):
        store.verify(asset)


def test_installed_whisper_can_decode_audio(application, real_video):
    decoder = pytest.importorskip("faster_whisper.audio")
    task = upload(application, {"video": ("course.mp4", real_video.read_bytes())}).json()
    repo = application.state.repository
    service = TranscriptService(application.state.settings, repo)
    artifact = service.extract_audio(repo.get(task["id"]))
    decoded = decoder.decode_audio(str(service.store.verify(artifact)))
    assert decoded.ndim == 1 and len(decoded) > 16000
