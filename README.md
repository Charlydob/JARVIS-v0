# JARVIS v0

Interfaz web/PWA y API modular para un asistente personal. Esta primera versión prioriza una presencia visual limpia, responsive y orientada a voz, junto con una base desacoplada para integrar modelos y servicios posteriormente.

## Funcionalidad

- PWA instalable en escritorio y móvil, con caché del shell de la aplicación.
- Rostro minimalista de dos ojos con estados `sleeping`, `idle`, `listening`, `thinking`, `speaking` y `error`.
- Máquina de estados independiente de React y animaciones respetuosas con `prefers-reduced-motion`.
- Conversación por texto, panel de transcripción/respuesta, configuración y modo display fullscreen.
- API FastAPI con REST, WebSocket y documentación OpenAPI automática.
- Contratos reemplazables para LLM, STT, TTS, memoria y herramientas.
- Adaptador Ollama opcional, configurable y no acoplado al resto de la aplicación.

## Estructura

```text
web/       React + TypeScript + Vite + PWA
backend/   FastAPI, proveedores y tests
docs/      documentación técnica
docker/    proxy Caddy para producción
```

Consulta [la arquitectura detallada](docs/architecture.md) para ver los límites y el flujo entre componentes.

## Desarrollo local

### Requisitos

- Node.js 20 o superior
- Python 3.11 o superior

### 1. Configuración

```bash
cp .env.example .env
```

El modo predeterminado usa proveedores mock y no requiere claves ni Ollama.

### 2. Backend

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements-dev.txt
cd backend
uvicorn app.main:app --reload
```

La API queda en `http://localhost:8000`, su documentación en `/docs` y el health check en `/api/health`.

### 3. Web

En otra terminal:

```bash
cd web
npm install
npm run dev
```

Abre `http://localhost:5173`. Para comprobar la experiencia instalable real, genera el build (`npm run build`) y sírvelo sobre HTTPS o localhost.

## API

| Método | Ruta | Uso inicial |
|---|---|---|
| `GET` | `/api/health` | Sonda de vida |
| `GET` | `/api/status` | Versión y proveedores activos |
| `POST` | `/api/chat` | Conversación de texto |
| `POST` | `/api/audio` | Carga de audio (STT mock) |
| `GET` | `/api/memories` | Memorias del proveedor activo |
| WebSocket | `/ws` | Ping y chat bidireccional |

Ejemplo:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"Hola, JARVIS"}'
```

## Variables de entorno

No guardes `.env` ni secretos en Git. El archivo `.env.example` documenta los valores admitidos.

| Variable | Predeterminado | Descripción |
|---|---|---|
| `VITE_API_URL` | `http://localhost:8000` | Base HTTP usada por el navegador; vacía detrás de Caddy |
| `VITE_WS_URL` | `ws://localhost:8000/ws` | URL del WebSocket reservado para streaming |
| `JARVIS_ENV` | `development` | Entorno de ejecución |
| `JARVIS_HOST` / `JARVIS_PORT` | `0.0.0.0` / `8000` | Bind del servidor |
| `JARVIS_CORS_ORIGINS` | `http://localhost:5173,...` | Orígenes permitidos, separados por coma |
| `JARVIS_LLM_PROVIDER` | `mock` | `mock` u `ollama` |
| `JARVIS_OLLAMA_URL` | `http://localhost:11434` | URL configurable del servicio Ollama |
| `JARVIS_OLLAMA_MODEL` | `llama3.2` | Modelo solicitado a Ollama |
| `JARVIS_DOMAIN` | `jarvis.example.com` | Dominio usado por Caddy en producción |

Para Ollama en el mismo equipo, usa `JARVIS_LLM_PROVIDER=ollama` y la URL local. En Docker Compose se utiliza `host.docker.internal`; para Ollama remoto, sustituye `JARVIS_OLLAMA_URL` por su URL alcanzable desde el contenedor. No expongas Ollama públicamente sin autenticación y controles de red.

## Docker

Levanta web y API para desarrollo o validación local:

```bash
docker compose up --build web backend
```

La aplicación estará en `http://localhost:8080`. El contenedor web sirve la SPA y el backend permanece en la red interna.

## Despliegue Linux detrás de Caddy

El perfil `production` incluye una configuración Caddy preparada para TLS automático, proxy WebSocket y enrutamiento de `/api/*`. No instala ni modifica servicios del host.

1. Apunta el DNS del subdominio al servidor.
2. Copia `.env.example` a `.env`, establece `JARVIS_DOMAIN` y revisa las variables.
3. Si ya existe un Caddy en el servidor, **no levantes el servicio `gateway`**: incorpora manualmente las reglas de `docker/Caddyfile` en la configuración existente y enruta al puerto local `8080`/backend según tu topología.
4. En un host sin proxy existente, ejecuta:

```bash
docker compose --profile production up -d --build
```

Antes de producción se recomienda añadir persistencia real de memoria, autenticación, límites de petición, observabilidad y una política de copias de seguridad.

## Pruebas

```bash
cd web && npm test && npm run build
cd backend && pytest
```

## Alcance

Esta versión no implementa cámara, domótica, hexápodo, wake word ni visión artificial. Las interfaces de proveedores y herramientas permiten añadir esas capacidades más adelante sin acoplarlas a la UI ni al proveedor de lenguaje.
