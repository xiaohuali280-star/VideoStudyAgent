"""Explicit real-media/ASR smoke test; LLM is always a loopback HTTP fixture.

Run from backend: python scripts/smoke_local.py --video FILE.mp4 --model-path DIR
No cloud key is read, saved or needed. Outputs stay in ignored .cache/.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import PROJECT_ROOT  # noqa: E402
from app.worker import kill_attempt  # noqa: E402


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--model-path", required=True, type=Path)
    args = parser.parse_args()
    if not args.video.is_file() or not (args.model_path / "model.bin").is_file():
        parser.error("An existing MP4 and prepared local Whisper model are required")
    root = PROJECT_ROOT / ".cache" / f"smoke-final-{uuid4().hex[:12]}"
    root.mkdir(parents=True)
    model_port, api_port = free_port(), free_port()
    environment = {key: value for key, value in os.environ.items() if not key.startswith("VSA_")}
    environment.update(
        {
            "VSA_ENVIRONMENT": "test",
            "VSA_DATA_DIR": str(root),
            "VSA_HTTP_FIXTURE": "1",
            "VSA_LLM_API_KEY": uuid4().hex,
            "VSA_LLM_BASE_URL": f"http://127.0.0.1:{model_port}",
            "VSA_ASR_MODEL_PATH": str(args.model_path.resolve()),
            "VSA_ASR_DEVICE": "cpu",
            "VSA_ASR_COMPUTE_TYPE": "int8",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        }
    )
    processes = []

    def start(arguments):
        process = subprocess.Popen(
            [sys.executable, *arguments],
            env=environment,
            cwd=PROJECT_ROOT / "backend",
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        processes.append(process)
        return process

    def wait_ready(client, url, process):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Local test server exited")
            try:
                if client.get(url).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError("Local test server startup timed out")

    api_args = ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)]
    try:
        model = start(
            [
                "-m",
                "uvicorn",
                "tests.http_model_server:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(model_port),
            ]
        )
        api = start(api_args)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{api_port}", timeout=30, trust_env=False
        ) as client:
            wait_ready(client, f"http://127.0.0.1:{model_port}/metrics", model)
            wait_ready(client, "/api/health", api)
            report = {"cloud_llm_calls": 0, "real_asr": True, "tasks": []}
            subtitle = "1\n00:00:00,000 --> 00:00:02,500\nGradient descent reduces the loss.\n"
            vtt = "WEBVTT\n\n00:00.000 --> 00:02.500\nGradient descent reduces the loss.\n"
            for mode, count, difficulty in [
                ("video", 5, "medium"),
                ("vtt", 5, "easy"),
                ("both", 5, "medium"),
                ("vtt_cached", 5, "easy"),
            ]:
                with args.video.open("rb") as video:
                    files = (
                        {"video": ("lesson.mp4", video, "video/mp4")}
                        if mode in {"video", "both"}
                        else {}
                    )
                    if mode != "video":
                        is_vtt = mode.startswith("vtt")
                        files["subtitle"] = (
                            "lesson.vtt" if is_vtt else "lesson.srt",
                            vtt if is_vtt else subtitle,
                            "text/plain",
                        )
                    response = client.post(
                        "/api/tasks",
                        files=files,
                        data={
                            "title": "Local smoke lesson",
                            "options": json.dumps(
                                {
                                    "question_count": count,
                                    "difficulty": difficulty,
                                    "transcript_language": "en-US",
                                }
                            ),
                        },
                    )
                assert response.status_code == 202
                task_id = response.json()["id"]
                worker = start(["-m", "app.worker", "--once"])
                worker.wait(timeout=180)
                assert worker.returncode == 0
                detail = client.get(f"/api/tasks/{task_id}").json()
                assert detail["task"]["status"] == "succeeded", detail["task"].get("error")
                result = client.get(f"/api/tasks/{task_id}/result").json()
                assert result["quiz"]["question_count"] == count
                assert result["quiz"]["difficulty"] == difficulty
                steps = detail["steps"]
                assert ("transcribe_audio" in [step["tool_name"] for step in steps]) == (
                    mode == "video"
                )
                if mode == "video":
                    assert result["transcript"]["source"] == "asr"
                    assert len(result["transcript"]["segments"]) > 0
                if mode == "vtt_cached":
                    assert any(
                        step["cache_hit"] for step in steps if step["tool_name"] != "generate_quiz"
                    )
                    assert not any(
                        step["cache_hit"] for step in steps if step["tool_name"] == "generate_quiz"
                    )
                for format in (
                    "notes.md",
                    "quiz.md",
                    "quiz.json",
                    "transcript.json",
                    "transcript.srt",
                ):
                    exported = client.get(f"/api/tasks/{task_id}/exports/{format}")
                    assert exported.status_code == 200 and exported.content
                    if format.endswith(".json"):
                        assert exported.json() == result[format.split(".")[0]]
                kill_attempt(api)
                api = start(api_args)
                wait_ready(client, "/api/health", api)
                assert client.get(f"/api/tasks/{task_id}/result").json() == result
                report["tasks"].append(
                    {
                        "mode": mode,
                        "question_count": count,
                        "difficulty": difficulty,
                        "source": result["transcript"]["source"],
                        "duration_ms": result["transcript"]["duration_ms"],
                        "segments": len(result["transcript"]["segments"]),
                        "exports": 5,
                        "api_restart": True,
                        "cache_hits": sum(step["cache_hit"] for step in steps),
                    }
                )
            report["http_model"] = client.get(f"http://127.0.0.1:{model_port}/metrics").json()
            (root / "smoke-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            print("Report: " + str(root / "smoke-report.json"))
    finally:
        for process in reversed(processes):
            kill_attempt(process)


if __name__ == "__main__":
    main()
