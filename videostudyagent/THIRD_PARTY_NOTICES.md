# Third-party notices

BiliNote, Copyright (c) 2024 Jeffery Huang, MIT. Fixed commit: 90940fde4d224d0f69ad99674f4af0a1ea52d3c4. License retained in third_party/licenses/BiliNote-MIT.txt. The ASR adapter is derived from backend/app/transcriber/whisper.py and substantially modified to remove application coupling, deletion/download behavior and exception swallowing; it preserves configured faster-whisper construction and segment conversion. See docs/UPSTREAM_SOURCES.json for source and local hashes.

Installed package licenses remain included in their distributions. FFmpeg binaries and model weights are local runtime prerequisites, excluded from this repository; this repository does not redistribute their binaries or weights.
