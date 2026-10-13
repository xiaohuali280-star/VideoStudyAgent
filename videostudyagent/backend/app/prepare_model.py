"""Explicit public model download; never called by API or Worker."""

import argparse
import json

from app.core.config import Settings


def main():
    parser = argparse.ArgumentParser(description="Explicitly prepare a local faster-whisper model")
    parser.add_argument("model", choices=["tiny", "base", "small", "medium", "large-v3"])
    args = parser.parse_args()
    from huggingface_hub import HfApi, snapshot_download

    repository = f"Systran/faster-whisper-{args.model}"
    revision = HfApi(token=False).model_info(repository).sha
    target = Settings().data_dir / "models" / args.model
    snapshot_download(
        repo_id=repository,
        revision=revision,
        token=False,
        local_dir=target,
        allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*"],
    )
    (target / "source.json").write_text(
        json.dumps({"repository": repository, "revision": revision}), encoding="utf-8"
    )
    print(f"Prepared {args.model} at fixed revision {revision}.")


if __name__ == "__main__":
    main()
