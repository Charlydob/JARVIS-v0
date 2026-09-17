# JARVIS v0.2

JARVIS es una PWA de voz cuyo cerebro permanece en el PC. Hetzner solo sirve la interfaz y mantiene un relay ligero; no ejecuta Ollama, Whisper ni TTS.

## Qué funciona

- Cara minimalista sobre negro con ojos, pupilas, cejas y boca animadas para `idle`, `listening`, `thinking`, `speaking`, `sleeping`, `muted` y `error`.
- Clic en la cara para alternar escucha y mute; menú hamburguesa discreto.
- Escucha continua con captura real del micrófono, detección de actividad de voz y cierre de turno tras 3 segundos de silencio.
- STT con `faster-whisper`, respuesta con Ollama y TTS ejecutados desde el Core de Windows.
- Dashboard con historial persistente, entrada manual y feedback correcto/incorrecto. Una valoración incorrecta exige y guarda la respuesta esperada.
- SQLite en `%USERPROFILE%\.jarvis\memory.db` para historial y feedback.
- Estado offline real: si el Core no mantiene su conexión, la web muestra a JARVIS dormido y los endpoints conversacionales devuelven `503`.
- PWA instalable, API REST y WebSocket conservados.

## Arquitectura segura

```text
Navegador / PWA
        │ HTTPS + Authelia
        ▼
jarvis.charlydob.com (Caddy del host)
        │ 127.0.0.1:8088
        ▼
Web + Gateway (Docker, Hetzner)
        ▲
        │ WSS saliente + token interno
        │
JARVIS Core (Windows)
  ├─ Ollama 127.0.0.1:11434
  ├─ faster-whisper
  ├─ edge-tts
  └─ SQLite
```

El PC inicia la conexión. No necesita puertos entrantes, NAT, port-forwarding ni publicar `11434`. El endpoint interno usa un secreto independiente; el tráfico viaja cifrado por Caddy. Consulta [docs/architecture.md](docs/architecture.md) para los límites y el protocolo.

## Arrancar el Core en Windows

Requisitos:

- Python 3.11 o 3.12 de 64 bits, disponible como `py -3.11`.
- Ollama iniciado y el modelo descargado: `ollama pull llama3.1:8b`.
- Acceso saliente HTTPS a `jarvis.charlydob.com`.

1. Copia `.env.example` a `.env` en la raíz.
2. Pon en `JARVIS_CORE_TOKEN` exactamente el mismo secreto aleatorio que existe en `/opt/jarvis/.env`.
3. Revisa `JARVIS_DATA_DIR` y el modelo de Ollama.
4. Ejecuta:

```powershell
cd core
.\run.ps1
```

La primera ejecución crea `core\.venv`, instala dependencias y descarga el modelo Whisper configurado. Para iniciarlo al entrar en Windows, abre PowerShell normal (no requiere administrador) y ejecuta una vez:

```powershell
.\install-autostart.ps1
```

El Core reconecta automáticamente con espera exponencial si Internet o el servidor no están disponibles. `edge-tts` genera el audio desde el proceso del PC, aunque utiliza el servicio de voz de Microsoft y por tanto requiere Internet; sustituirlo por Piper local es una mejora pendiente si se quiere TTS totalmente offline.

Whisper usa CPU por defecto para funcionar sin instalar librerías CUDA adicionales. Si se instala CUDA/cuBLAS compatible con CTranslate2, se puede cambiar `JARVIS_WHISPER_DEVICE=cuda` y `JARVIS_WHISPER_COMPUTE_TYPE=float16` para aprovechar la GPU.

## Configurar Hetzner

El repositorio debe estar en `/opt/jarvis`, con un `.env` no versionado:

```dotenv
JARVIS_CORE_TOKEN=<64 caracteres hexadecimales o más>
JARVIS_CORS_ORIGINS=https://jarvis.charlydob.com
```

Genera el secreto en el servidor con `openssl rand -hex 32`; copia ese valor al `.env` del PC por un canal seguro. No lo añadas a GitHub ni al código.

Arranque manual:

```bash
cd /opt/jarvis
docker compose config --quiet
docker compose up -d --build gateway web
curl --fail http://127.0.0.1:8088/api/health
```

El único puerto publicado por Compose es `127.0.0.1:8088`. `8080` queda libre para TechTree. No ejecutes el antiguo perfil Caddy del proyecto: se reutiliza el Caddy del host.

Integra el bloque de ejemplo [docker/Caddyfile](docker/Caddyfile) en la configuración existente del host. Mantén `/internal/core/ws` fuera del forward-auth de navegador, ya que ese endpoint usa el token interno; protege el resto de la aplicación con la directiva de Authelia ya existente. Valida con `caddy validate` antes de recargar Caddy.

## Autodeploy desde GitHub

Cada push a `main` ejecuta primero tests y build. Solo si pasan, GitHub Actions entra por SSH y ejecuta [scripts/deploy-server.sh](scripts/deploy-server.sh). El script:

- comprueba que está exactamente en `/opt/jarvis` y que el remoto es este repositorio;
- se detiene si hay cambios locales, sin borrarlos;
- acepta únicamente un avance fast-forward de `main`;
- reconstruye solo `gateway` y `web`;
- verifica `http://127.0.0.1:8088/api/health` y muestra logs si falla.

Configura el environment de GitHub `production` y estos secrets:

| Secret | Contenido |
|---|---|
| `JARVIS_HOST` | IP o hostname SSH de Hetzner |
| `JARVIS_USER` | Usuario de despliegue con acceso limitado a `/opt/jarvis` y Docker |
| `JARVIS_SSH_KEY` | Clave privada dedicada al despliegue |

La clave pública verificada del host está fijada en `.github/jarvis_known_hosts`; no es un secreto y evita confiar a ciegas en `ssh-keyscan` durante cada deploy.

El token PC↔gateway no es un secret de Actions: vive solo en los dos `.env` de ejecución.

## API

| Método | Ruta | Responsabilidad |
|---|---|---|
| `GET` | `/api/health` | Vida del gateway, aunque el PC esté apagado |
| `GET` | `/api/status` | Conectividad y proveedores anunciados por el Core |
| `POST` | `/api/chat` | Relay de conversación hacia Ollama en el PC |
| `POST` | `/api/audio` | Relay de audio hacia Whisper en el PC |
| `POST` | `/api/tts` | Audio TTS generado desde el Core |
| `GET` | `/api/memories` | Contrato de memorias explícitas |
| `GET` | `/api/history` | Historial persistente para el dashboard |
| `POST` | `/api/feedback` | Valoración y corrección para entrenamiento futuro |
| WebSocket | `/ws` | Ping/chat compatible para clientes |
| WebSocket | `/internal/core/ws` | Canal privado autenticado del Core; no es una API de navegador |

## Desarrollo y pruebas

```bash
cd web
npm ci
npm test
npm run lint
npm run build

python -m pip install -r backend/requirements-dev.txt
PYTHONPATH=backend pytest backend/tests -q
PYTHONPATH=core pytest core/tests -q
```

Para un entorno local completo, usa el mismo token de desarrollo en gateway y Core. Nunca reutilices ese valor en producción.

## Pendiente o provisional

- `edge-tts` no es TTS offline; Piper es el reemplazo recomendado si se exige funcionamiento sin Internet.
- La tabla de memorias explícitas existe, pero todavía no hay extracción automática de hechos ni una política de consolidación.
- Las correcciones se almacenan y exportan desde SQLite, pero todavía no hay un pipeline de fine-tuning automático.
- Authelia y el bloque de Caddy del host deben integrarse manualmente porque este repositorio no debe sobrescribir la configuración compartida con otros servicios.
- El umbral VAD es conservador y puede requerir ajuste según el micrófono y el ruido de la habitación.
