# JARVIS 0.5.0 — semantic voice pipeline report

## Architecture

`audio → local STT → TranscriptionQualityGate → SemanticPlanner (local Ollama JSON schema) → PlanValidator → established deterministic resolver/executor → verified result → response`

The semantic planner is enabled by default. If the local planner is unavailable or returns invalid JSON, JARVIS logs the failure and falls back to the legacy router. When planning succeeds, the legacy semantic regex router is bypassed. Existing BookShell UUID resolution, conservative matching, idempotency, tool schemas, verification, and no-false-success behavior remain unchanged.

## Real cases

- Reminder create: planner returned title `hacer deberes de alemán`, date `tomorrow`, time `null`; validator requests a time clarification rather than executing.
- Reminder delete: planner returned title `otro recordatorio`, scope `tomorrow`.
- Checklist name: `Proyecto Jarvis` was preserved.
- Pending repair: with a pending append to `Mejoras`, “no, me refería a Mejoras Dos” produced target `Mejoras Dos` while preserving item `probar actualizaciones`.
- Context continuation “añade también mejorar transcripción” did not resolve reliably with the current `llama3.1:8b` prompt in the six-case live run. It safely became conversation rather than a mutation. This remains a measured model/prompt limitation.

## Planner evaluation

One local run against `llama3.1:8b`, six hand-written real-case regressions:

- Legacy router intent accuracy: 4/6 (66.7%).
- Semantic planner intent accuracy: 5/6 (83.3%).
- Semantic planner full expected-entity case accuracy: 5/6 (83.3%).

This dataset is intentionally small and is a regression smoke set, not a statistically robust benchmark. The live model initially chose an arbitrary date/time until the prompt was hardened to preserve relative dates and force bare-hour ambiguity. Schema validation and deterministic required-field checks still prevent incomplete execution.

## STT quality and turn-taking

- Quality states: `ACCEPT`, `LOW_CONFIDENCE`, `REJECT`.
- Signals: average log probability, no-speech probability, compression ratio, decoded/VAD duration, token count, repetition/phrase loops, and contextual hallucination-style endings.
- `REJECT` yields no transcript to the planner. `LOW_CONFIDENCE` may be conversational, but mutation/open operations require confirmation.
- Recent TTS similarity is rejected during the echo window; the separate interruption listener still recognizes intentional interruption.
- The persistent microphone stream remains reused. Logs now include `tts_audio_end_timestamp`, `listener_armed_timestamp`, `first_audio_frame_timestamp`, `vad_speech_start_timestamp`, and computed `tts_end_to_listener_armed_ms`.
- No production browser sample was available during this implementation, so an honest before/after millisecond result is not claimed.

## STT benchmark status

Detected environment:

- CPU: AMD Ryzen 7 3700X, 8 cores / 16 logical processors.
- GPU: NVIDIA GeForce GTX 1660 SUPER, 6 GiB VRAM.
- Driver: 595.95; reported CUDA capability: 13.2.
- Ollama: `llama3.1:8b`, 5.6 GB allocation, 75% GPU / 25% CPU, context 4096.
- Snapshot VRAM: 5620 MiB / 6144 MiB used (about 524 MiB free).
- Historical audio corpus in the repository: none found.

GPU Whisper candidates were not loaded because available headroom was unsafe and repeated OOM is explicitly forbidden. `scripts/benchmark_stt.py` provides an isolated manifest-driven harness, GPU-headroom abort, load/latency/RTF metrics, segment confidence signals, and before/after GPU snapshots. No accuracy or winner is invented without a real local corpus.

## Verification

- Core: 165 passed.
- Backend: 11 passed.
- Web: 29 passed.
- Web production build: passed.
- Web lint: passed.
- Python compile check: passed.

