# Arquitectura

```text
Navegador / PWA
  │ HTTP + WebSocket
  ▼
Caddy ─────► React (archivos estáticos)
  │
  └────────► FastAPI
               ├── LLMProvider ─────► Mock / Ollama
               ├── SpeechToTextProvider ─► Mock / futuro motor STT
               ├── TextToSpeechProvider ─► Mock / futuro motor TTS
               ├── MemoryProvider ──► memoria temporal / futura base de datos
               └── ToolProvider ────► futuras herramientas
```

## Principios

- La máquina de estados visual reside en `web/src/state/machine.ts` y no depende de React.
- FastAPI depende de contratos abstractos, no de Ollama. `build_providers` es el punto de composición.
- Ollama se configura por URL; puede estar en el host local, en otra máquina o en otra red Docker.
- Cámara, domótica, wake word, visión y robótica quedan fuera de esta primera versión. Se añadirán como adaptadores o herramientas, sin alterar el núcleo conversacional.
- El almacenamiento de memoria actual es volátil y sirve como contrato inicial, no como persistencia de producción.

## Flujo de conversación

La interfaz transita por `idle → listening → thinking → speaking → idle`. Cualquier fallo mueve el sistema a `error`; el reposo se puede solicitar desde cualquier estado activo. El endpoint HTTP soporta la experiencia actual y `/ws` deja preparado un canal bidireccional para streaming futuro.
