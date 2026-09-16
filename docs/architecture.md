# Arquitectura de JARVIS

## Límites de confianza

| Zona | Ejecuta | No ejecuta |
|---|---|---|
| Navegador | UI, micrófono, VAD, reproducción | Modelos, secretos internos, memoria |
| Hetzner | PWA, gateway, relay, estado | Ollama, Whisper, TTS, base de datos personal |
| PC Windows | Ollama, Whisper, TTS, SQLite | Servicios publicados directamente a Internet |

El Caddy compartido termina TLS y aplica Authelia a la experiencia web. El gateway escucha solo dentro de Docker; el contenedor web publica `127.0.0.1:8088`. Ollama permanece en `127.0.0.1:11434` en Windows.

## Canal Core → gateway

El Core abre `wss://jarvis.charlydob.com/internal/core/ws` con `Authorization: Bearer <JARVIS_CORE_TOKEN>`. El token se compara en tiempo constante. La conexión es saliente desde Windows y se mantiene con heartbeats.

El gateway multiplexa solicitudes con identificadores UUID:

```text
gateway → {type: request, id, action, payload}
core    → {type: result, id, ok, result|error}
```

Solo se admite un Core activo; una conexión nueva reemplaza a la anterior. Si se corta, las solicitudes pendientes fallan, `/api/status` pasa a `offline` y la UI entra en `sleeping`.

Acciones actuales: `chat`, `audio`, `tts`, `history`, `memories` y `feedback`. El audio viaja en base64 y tiene un límite configurable de 25 MiB. Las respuestas del Core se correlacionan sin exponer el token al navegador.

## Flujo de voz

```text
permiso de micrófono
  → escucha continua
  → energía supera el umbral VAD
  → 3 s de silencio
  → POST /api/audio
  → Whisper en Windows
  → POST /api/chat
  → Ollama en Windows
  → POST /api/tts
  → TTS en Windows
  → reproducción en navegador
  → vuelve a escuchar
```

Mientras JARVIS piensa o habla, el navegador cierra el micrófono para evitar realimentar su propia voz. El mute también cierra las pistas de audio; no es solo un cambio visual.

## Persistencia

SQLite usa WAL y tres tablas:

- `messages`: turnos de usuario y asistente por conversación;
- `feedback`: valoración, corrección esperada y fecha;
- `memories`: contrato para hechos explícitos futuros.

El gateway no persiste conversaciones. Apagar o reconstruir Hetzner no borra la memoria que reside en el PC.

## Seguridad operativa

- No publicar `11434`, el gateway ni los puertos del Core.
- Generar tokens de al menos 256 bits y rotarlos en ambos `.env`.
- Excluir únicamente `/internal/core/ws` de Authelia; el gateway sigue exigiendo el token.
- Mantener `/api/*`, `/ws` y la PWA detrás de Authelia y HTTPS.
- Limitar CORS al dominio de producción; el WebSocket de navegador valida `Origin`.
- Usar una clave SSH de deploy dedicada, host key fijada y usuario sin permisos sobre otros servicios.
- Hacer backup cifrado de `%USERPROFILE%\.jarvis\memory.db` si su contenido importa.

## Despliegue sin interferir con otros servicios

El Compose de este repositorio no publica 80/443 y no levanta un Caddy de host. La automatización solo nombra `gateway` y `web`, conserva cambios locales y no ejecuta `docker compose down`, `--remove-orphans`, `git reset --hard` ni limpieza global de imágenes.
