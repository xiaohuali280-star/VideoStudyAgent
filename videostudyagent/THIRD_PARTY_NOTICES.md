# Third-party notices

BiliNote, Copyright (c) 2024 Jeffery Huang, MIT. Fixed commit: 90940fde4d224d0f69ad99674f4af0a1ea52d3c4. License retained in third_party/licenses/BiliNote-MIT.txt. The ASR adapter is derived from backend/app/transcriber/whisper.py and substantially modified to remove application coupling, deletion/download behavior and exception swallowing; it preserves configured faster-whisper construction and segment conversion. See docs/UPSTREAM_SOURCES.json for source and local hashes.

Installed package licenses remain included in their distributions. FFmpeg binaries and model weights are local runtime prerequisites, excluded from this repository; this repository does not redistribute their binaries or weights.

BiliNote's request_chunker.py is vendored unchanged; its tests are modified only for module location. Selected note prompt clauses are adapted to versioned JSON and source coverage. MIT license above applies.

DeepTutor, Copyright 2025 Data Intelligence Lab, The University of Hong Kong, Apache-2.0. Fixed commit: 6cf793bd868ba5ecbe64722936d4be8fab5a01df. License: third_party/licenses/DeepTutor-Apache-2.0.txt. json_output.py is vendored unchanged; its tests change import location and attribution header. The grounding adapter is modified for per-segment evidence, strict count and numeric/sign preservation. Modified files carry notices. The upstream third-party notices were reviewed and retained in third_party/licenses/DeepTutor-UPSTREAM-NOTICES.md; their OAuth, bot-registration and thinking-orbs components are not included here.

AI Tutor, Copyright (c) 2026 Advaith Arun Kashyap, MIT. Fixed commit: 438e3aa42af58dcba61fa993dd1519ade55aafcc. License: third_party/licenses/AI-Tutor-MIT.txt. Three difficulty descriptions are adapted in prompts/study.py; the RAG/Groq/MCQ generation chain is not included.
