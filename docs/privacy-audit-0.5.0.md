# Privacy audit — JARVIS 0.5.0

## LOCAL

- Ollama planner/chat: prompts, compact recent context, and capability schema stay on the configured local Ollama endpoint by default.
- Faster-Whisper STT: microphone audio is decoded and transcribed locally; temporary input files are deleted after transcription.
- Memory: SQLite in `JARVIS_DATA_DIR`.
- Optional captured benchmark corpus: disabled by default (`JARVIS_STT_CORPUS_CAPTURE_LIMIT=0`), bounded when enabled, local only, and intended to be deletable.

## EXTERNAL-ON-DEMAND

- BookShell: sends the arguments required by an explicitly selected BookShell tool to the configured BookShell API/gateway (currently Hetzner in production configuration). This can include reminder, note, checklist, book, finance, habit, recipe, gym, or agenda content.
- Tavily: sends the user's web-search query when a web search is requested and configured.
- Open-Meteo: receives coordinates and forecast parameters for weather requests.
- Nominatim: receives coordinates for reverse-geocoding/location requests.
- PC URL opening: sends no request from Core, but opening a URL causes the browser to contact that site.
- Edge TTS: **text to be spoken leaves the PC and is sent to Microsoft's online speech service.** It is not local TTS. No TTS provider change is made in 0.5.0.

## EXTERNAL-ALWAYS

- The deployed web client and Core maintain their configured gateway connection; operational metadata and relayed request payloads traverse that gateway.
- No new external service, telemetry, cloud LLM, or paid STT service is introduced by 0.5.0.

## Controls

- Semantic planning uses only Ollama; no cloud-reasoning fallback exists.
- Clearly rejected STT text never reaches the planner.
- Low-confidence STT cannot directly trigger a mutating/open action.
- The planner is forbidden by schema validation from supplying IDs, UUIDs, verification flags, or results.
