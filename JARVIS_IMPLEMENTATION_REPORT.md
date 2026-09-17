# JARVIS implementation report

## 1. Estado encontrado

- Rama `main`, sincronizada inicialmente con `origin/main` en `7a8b3e8`.
- PWA minimalista, escucha continua, Core Windows, gateway Hetzner, Ollama, Whisper, Edge TTS, memoria SQLite, historial diario y autodeploy ya operativos.
- En el inicio había un cambio incompleto sin commit en `core/jarvis_core/services.py` para comenzar el streaming.
- El enlace PC-gateway seguía autenticado por WebSocket saliente; Ollama continuaba limitado a localhost.

## 2. Trabajo que estaba incompleto

- Ollama respondía con `stream: false` y `num_predict: 220`, por lo que las respuestas largas se cortaban.
- La web esperaba toda la respuesta antes de solicitar TTS.
- El texto largo quedaba oculto por el `overflow` de la pantalla principal.
- La instrucción del sistema priorizaba español aunque el usuario hablara inglés.
- No existía una interfaz extensible para tools/actions.
- El feedback guardaba `good/bad` y corrección, pero no una recompensa numérica ni un motivo normalizado.

## 3. Implementación terminada

- Streaming Ollama → Core → WebSocket privado → gateway → SSE → PWA.
- Eliminado el tope artificial de salida: `num_predict: -1`, terminación natural por EOS/modelo.
- Texto incremental completo con desplazamiento automático y área desplazable para respuestas largas.
- TTS en cola ordenada por frases; comienza cuando aparece la primera frase completa y continúa mientras Ollama genera.
- Corte de seguridad a 240 caracteres por espacio o puntuación cuando una frase no contiene cierre, sin cortar palabras.
- Respuesta automática en el idioma detectado del usuario y voz nativa asociada.
- Registro de tools/actions con carga modular por `JARVIS_TOOL_MODULES`.
- Feedback persistente `reward = +1/-1`, `reason` y `correction`; migración compatible con datos existentes.
- Iconos de galleta para recompensa positiva y látigo para negativa.
- Workflow corregido para instalar y probar las dependencias reales del Core antes de desplegar.

## 4. Archivos modificados

- `.env.example`
- `.github/workflows/deploy.yml`
- `README.md`
- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/relay.py`
- `backend/tests/test_api.py`
- `core/jarvis_core/config.py`
- `core/jarvis_core/main.py`
- `core/jarvis_core/services.py`
- `core/jarvis_core/storage.py`
- `core/jarvis_core/tools.py`
- `core/tests/test_storage.py`
- `core/tests/test_streaming.py`
- `core/tests/test_tools.py`
- `docs/architecture.md`
- `docs/tools.md`
- `web/src/App.tsx`
- `web/src/api/client.ts`
- `web/src/speech.ts`
- `web/src/speech.test.ts`
- `web/src/styles.css`

## 5. Arquitectura final relevante

```text
PWA ──POST /api/chat/stream──> Hetzner gateway
                                  │
                                  │ WebSocket saliente autenticado
                                  ▼
Windows Core ──localhost──> Ollama / Whisper / Edge TTS / SQLite / ToolRegistry
```

- `/api/chat` se conserva por compatibilidad.
- `/api/chat/stream` devuelve eventos SSE `chunk`, seguidos de un único evento `result` persistido.
- Hetzner no ejecuta modelos ni tiene acceso directo a Ollama.
- Las tools se ejecutan exclusivamente en el Core y sus secretos permanecen en Windows.

## 6. Streaming de texto y TTS

1. Ollama entrega fragmentos NDJSON al Core.
2. El Core reenvía cada fragmento por el WebSocket autenticado.
3. El gateway lo publica como SSE sin buffering.
4. La PWA concatena cada fragmento una sola vez y actualiza el texto.
5. `takeSpeechSegments` extrae frases completas en orden.
6. Cada frase entra en una única cola Promise: sintetizar → reproducir → continuar.
7. Al finalizar el evento `result`, se vacía el último fragmento aunque no termine en puntuación.

## 7. Detección de idioma

- Whisper detecta el idioma del audio y la PWA lo envía junto al mensaje.
- Para texto manual, el Core detecta el idioma con `langdetect`.
- El prompt obliga a contestar en el idioma del mensaje más reciente, salvo petición explícita contraria.
- El TTS recibe el idioma de entrada durante streaming; si no existe, detecta el idioma del propio fragmento.
- Edge TTS selecciona una voz masculina del locale correspondiente, con preferencia explícita para idiomas comunes.

## 8. Tools/actions

- Estado: base extensible terminada; ninguna aplicación externa activada todavía (`tools: none`).
- `ToolRegistry` permite registrar nombre, descripción, JSON Schema y handler asíncrono.
- Ollama recibe solo tools registradas, puede solicitar una llamada estructurada, recibe el resultado y genera la respuesta final.
- Los módulos se habilitan con `JARVIS_TOOL_MODULES=modulo_bookshell,modulo_guardias`.
- Contrato y ejemplo: `docs/tools.md`.
- BookShell, Guardias, Calendar, Sheets, Vuxel, Home Assistant y robots siguen sin adaptador, credenciales ni permisos configurados.

## 9. Feedback `+1/-1`

- Positivo: `rating=good`, `reward=1`, motivo predeterminado `perfect`.
- Negativo: `rating=bad`, `reward=-1`, motivo seleccionable y corrección escrita.
- Motivos UI: incorrecta, demasiado larga, poco útil, tono inadecuado y otro.
- La migración añade `reward` y `reason` a la tabla existente y convierte valoraciones antiguas.
- Verificación sobre la base real: columnas presentes y cero recompensas nulas.

## 10. Pruebas ejecutadas

- Core: `5 passed`.
- Gateway: `8 passed`.
- Web/Vitest: `4 passed`.
- ESLint: correcto.
- TypeScript + Vite + PWA build: correcto.
- GitHub Actions para `aa4fb45`: `validate=success`, `deploy=success`.
- Prueba Ollama larga: primer fragmento en `0.85 s` con el modelo caliente; lista completa hasta 60 y EOS natural.
- Prueba completa SSE: 424 chunks, un único result y final completo hasta 60.
- Prueba final de producción en inglés: 7 chunks, respuesta `Bern is the capital of Switzerland.`, idioma `en`.
- TTS de producción inglés: HTTP 200, MP3 mono 24 kHz, 17 856 bytes.
- Los mensajes creados por las pruebas se eliminaron del historial al terminar.

## 11. Limitaciones pendientes reales

- El primer audio empieza al completarse una frase o alcanzar 240 caracteres; Edge TTS necesita sintetizar ese primer fragmento.
- La longitud máxima absoluta sigue limitada por la ventana de contexto del modelo, no por un corte artificial de JARVIS.
- No hay tools externas instaladas: cada aplicación necesita un adaptador y una API/autenticación verificable.
- Tras un despliegue, una PWA ya abierta puede requerir cerrarse y abrirse para activar el nuevo service worker.

## 12. Commits y estado Git

- Implementación principal: `6ea209d4292e79d3b6f204010ee04e43829e282e`.
- Corrección CI: `cbb03ff954088a8e51858ad58bc18e91783d2691`.
- Implementación final desplegada: `aa4fb45c704df5ccf653973bd735618d59870910`.
- Rama: `main`.
- Hetzner: `aa4fb45c704df5ccf653973bd735618d59870910`, servicios saludables.
- El commit documental que contiene este informe es el `HEAD` inmediatamente posterior; consultar con `git rev-parse HEAD`.
- Estado previo a añadir este informe: limpio y sincronizado con `origin/main`.

## 13. Reproducción manual

1. Cerrar y abrir la PWA para actualizar el service worker.
2. Decir: `JARVIS, explícame en detalle la historia de Internet en diez apartados.` Confirmar que el texto aparece incrementalmente, puede desplazarse y llega al final.
3. Con la voz activada, repetir la prueba y confirmar que empieza a hablar tras la primera frase mientras el texto sigue creciendo; comprobar que lee también el último apartado.
4. Decir en inglés: `What is the capital of Switzerland?` Confirmar texto y voz en inglés sin pedir cambio de idioma.
5. Abrir Historial, pulsar la galleta y comprobar recompensa positiva; pulsar el látigo en otra respuesta, escoger motivo y guardar corrección.
6. Pruebas automatizadas locales desde la raíz:

```powershell
$env:PYTHONPATH='core'; .\core\.venv\Scripts\python.exe -m pytest core\tests -q
$env:PYTHONPATH='backend'; .\.venv-check\Scripts\python.exe -m pytest backend\tests -q
npm --prefix web test
npm --prefix web run lint
npm --prefix web run build
```

7. Estado de producción:

```powershell
ssh -i C:\Users\carlo\.ssh\hetzner_ed25519 root@46.224.61.193 "cd /opt/jarvis; git rev-parse HEAD; docker compose ps; curl -sS http://127.0.0.1:8088/api/status"
```
