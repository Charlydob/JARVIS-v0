# REFERENCE REVIEW — JARVIS 0.5.0

Reviewed 2026-09-21 before implementation. Repository snapshots were cloned only for inspection.

## Couvbat/Jarvis

**USE:** The bounded `Audio → VAD → STT → Ollama agent → policy/registry → tool → TTS` loop; strict separation between model-selected calls, policy, and execution; compact per-turn tool selection; local tool-calling evaluation; sentence-streamed TTS and explicit barge-in design.

**REJECT:** Linux-specific audio/Piper setup, unrestricted agent loops, and direct source copying. The inspected `main` snapshot contains no `LICENSE` file, despite external descriptions calling the project MIT, so its code is not treated as licensed for direct reuse.

## kubikhavran/JARVIS-AGI

**USE:** Windows-oriented lazy Faster-Whisper loading, CUDA-to-CPU fallback, isolated STT/hotword/audio modules, intent routing separated from skill execution, cancellable TTS, bounded memory, and Task Scheduler patterns.

**REJECT:** Gemini/cloud fallback, its broad skill auto-discovery surface for this iteration, and direct source copying. The inspected snapshot contains no `LICENSE` file.

## JohnTwenty/Computer

**USE:** Architectural ideas only: one persistent audio loop, wake-word gating, debounced silence endpointing, GPU Faster-Whisper configuration, Piper playback, and explicit listen/transcribe/think/speak/listen transitions.

**REJECT:** Direct source reuse and wholesale replacement of the existing browser capture pipeline. No `LICENSE` file is present in the inspected snapshot, so no code may be copied.

## OHF-Voice/wyoming-faster-whisper

**USE:** The service boundary and lifecycle (`AudioStart`, chunks, `AudioStop`, transcript/error); resettable endpoint detector; normalized 16 kHz mono input; bounded command/silence segmentation; reconnectable STT process; model/cache separation.

**REJECT:** Adopting the Wyoming protocol in 0.5.0. JARVIS already has an HTTP/WebM transport and changing it would enlarge risk without being required for the semantic planner or quality gate.

License: MIT, verified in `LICENSE.md` in the inspected repository. No literal source is presently copied.

## ep-ipc/home-assistant-voice-stack

**USE:** Keep Ollama native and warm; keep STT/TTS separable; cap context for limited VRAM; benchmark CPU STT against GPU residency rather than assuming coexistence; expose only a compact capability catalog.

**REJECT:** Home Assistant as orchestrator, Docker-only production STT, English-only defaults, and direct source copying. The inspected repository contains no `LICENSE` file and is primarily an operational guide.

## ARCHITECTURAL DECISIONS BORROWED

- The LLM interprets a compact semantic request and emits schema-constrained JSON; it never executes tools.
- A deterministic validator resolves real entities, enforces required fields, confirmations, allowlists, and action limits.
- The existing verified executor remains the only mutation path; model prose can never establish success.
- Pending state stores the semantic plan and is amended by follow-ups or explicit repairs.
- STT is treated as a separable stage with a multi-signal quality decision before planning.
- Voice capture uses one persistent media stream and explicit state transitions, including a separate interruption mode during playback.
- Planner and STT candidates are measured locally; model size alone does not select the winner.

## CODE TO REUSE DIRECTLY

None planned. This iteration reuses JARVIS's existing internal BookShell executors and verification paths, not third-party code.

## SOURCE + LICENSE

- `OHF-Voice/wyoming-faster-whisper`: MIT (`LICENSE.md` verified); patterns only.
- `Couvbat/Jarvis`: no license file in inspected snapshot; patterns only.
- `kubikhavran/JARVIS-AGI`: no license file in inspected snapshot; patterns only.
- `JohnTwenty/Computer`: no license file in inspected snapshot; patterns only.
- `ep-ipc/home-assistant-voice-stack`: no license file in inspected snapshot; patterns/documentation only.

## CODE TO REIMPLEMENT LOCALLY

- `SemanticPlanner`, schema types, validation, pending-plan merge/repair, and planner evaluation.
- Multi-signal `TranscriptionQualityGate` and own-TTS similarity suppression.
- Turn timing instrumentation and explicit voice-state additions needed by the existing web client.
- Isolated, opt-in STT benchmark harness and local corpus manifest support.

