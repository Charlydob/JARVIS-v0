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

## Regression fixes and feedback UX

### Causas confirmadas

- Escucha: los logs reales mostraban `av.error.InvalidDataError` en varias capturas WebM. La PWA conservaba la cabecera pero eliminaba fragmentos intermedios del contenedor para formar el preroll; ciertos WebM/MP4 resultantes no eran decodificables por Whisper.
- Permisos: el hook detenía el track cada vez que cambiaba su ciclo de vida (cambio de vista, error o caída breve del Core), por lo que el navegador podía volver a solicitar acceso.
- Idioma: la instrucción enviada a Ollama era débil y estaba redactada en español; además, durante streaming el frontend forzaba al TTS el idioma de entrada, aunque el texto generado fuese de otro idioma.
- Boca: la clase visual `speaking` empezaba con el primer fragmento de texto, antes de que el MP3 estuviera sintetizado y reproduciéndose.
- Ojos desktop: la animación de escucha usaba solo escalado sutil. En pantallas grandes el movimiento era prácticamente imperceptible, aunque en móvil sí se apreciaba.

### Solución aplicada

- Feedback rápido persistente en la esquina superior izquierda de la cara. La galleta valora la última respuesta como positiva; el látigo abre el diálogo existente de motivo y corrección. La selección guardada queda marcada y el historial conserva sus controles por respuesta.
- Nuevo `GET /api/stats`, alimentado directamente por SQLite, con totales reales de mensajes, positivos y negativos. El dashboard los presenta junto al historial y los actualiza después de cada respuesta/valoración.
- Ollama recibe una obligación explícita de idioma con nombre y código. El texto manual también se detecta en el Core. El TTS detecta el idioma del texto generado y usa el idioma de entrada solo como fallback.
- La grabación conserva todos los fragmentos de cada contenedor. Los periodos sin voz rotan cada 15 segundos para acotar memoria sin cortar el interior de WebM/MP4. Se mantienen los umbrales de VAD existentes: no se subió sensibilidad sin evidencia.
- Telemetría añadida: consola web con motivo de parada/descarte, duración, voz estimada, bytes, MIME, RMS máximo y threshold; Core con bytes recibidos, duración declarada, idioma/probabilidad de Whisper, duración decodificada/VAD y transcripción o descarte vacío.
- El stream de micrófono se reutiliza durante la sesión de página frente a cambios temporales de vista/Core. Solo se libera al abandonar la página. El permiso persistente entre cierres/reinstalaciones sigue dependiendo de Safari/iOS y de los ajustes del sitio/PWA; la aplicación no puede concederlo ni conservarlo contra la política del sistema.
- La boca usa ahora un estado separado de reproducción: se abre únicamente después de que `HTMLAudioElement.play()` arranca y se cierra en `ended`/error. La síntesis y el streaming de texto no la mueven.
- Se añadieron keyframes solo para desktop (`min-width: 641px`) con traslación visible de ojos; los keyframes móviles no se tocaron. `prefers-reduced-motion` continúa respetándose.

### Archivos principales

- `web/src/App.tsx`
- `web/src/api/client.ts`
- `web/src/components/JarvisFace.tsx`
- `web/src/hooks/useContinuousVoice.ts`
- `web/src/styles.css`
- `backend/app/main.py`
- `core/jarvis_core/services.py`
- `core/jarvis_core/storage.py`
- `backend/tests/test_api.py`
- `core/tests/test_storage.py`
- `core/tests/test_streaming.py`

### Pruebas

- Gateway: `10 passed`.
- Core: `8 passed`.
- Web/Vitest: `4 passed`.
- ESLint: correcto.
- TypeScript + Vite + PWA build: correcto.
- Prueba real de Ollama: entrada inglesa produjo una respuesta íntegramente inglesa; entrada española produjo una respuesta íntegramente española.
- Base SQLite real leída sin modificar: `92 mensajes`, `1 positivo`, `0 negativos` en el momento de la prueba.
- Verificación visual desktop: feedback global visible y accesible; dashboard con los tres contadores persistentes.
- GitHub Actions `35220858532`: `Deploy JARVIS` completado con éxito. Hetzner quedó en `23b9d6bb20a84961300d31b56ab356b7c0d9ddf8`, con gateway/web saludables, Core conectado y `/api/stats` operativo.

### Límites y pasos manuales

- Tras el despliegue conviene cerrar y volver a abrir la PWA para que iOS active el service worker nuevo.
- iOS puede volver a pedir permiso tras cerrar/reinstalar la PWA, usar navegación privada, revocar permisos o aplicar su propia política de privacidad. Esto no se puede evitar desde JavaScript.
- Con “Reducir movimiento” activado en el sistema, las animaciones se reducen deliberadamente por accesibilidad.
- La captura móvil real debe confirmarse hablando varias veces desde el iPhone; los nuevos logs permiten distinguir un descarte VAD, un contenedor inválido y una transcripción vacía.

### Commit y estado Git

- Implementación: `23b9d6bb20a84961300d31b56ab356b7c0d9ddf8` (`fix: harden voice capture and feedback UX`).
- Rama: `main`.
- El commit documental que contiene esta sección es el `HEAD` posterior inmediato.
- Antes de añadir esta sección, el árbol estaba limpio y `origin/main` contenía el commit de implementación.

## Feedback learning + BookShell integration

### Cambios del TTS

- La segmentación conserva frases completas y palabras, distingue límites de frase, párrafo y continuación, y aplica solo 15 ms tras una frase y 120 ms tras un párrafo.
- La nueva cola desacopla preparación y reproducción: sintetiza ordenadamente el segmento siguiente mientras suena el actual, pero mantiene una única reproducción activa y respeta el orden original.
- El texto continúa hablándose de forma incremental; no se espera a que termine de generarse la respuesta completa.

### Recuperación de feedback

- Antes de responder se consultan hasta 50 valoraciones recientes, pero se inyectan como máximo tres ejemplos pertinentes.
- Como el Ollama local devuelve `501 Not Implemented` para `/api/embed`, un selector semántico separado basado en el propio modelo compara la petición nueva con las peticiones valoradas. Si ese selector falla, se usa similitud léxica como fallback.
- Una valoración positiva aporta un ejemplo aprobado. Una negativa aporta la respuesta que debe evitarse, el motivo y la corrección preferida, sin convertir esa corrección en una respuesta universal fija.
- El módulo está desacoplado mediante un selector inyectable para sustituirlo posteriormente por embeddings, preference training o fine-tuning.
- El logger `jarvis-core.feedback` registra modo, número de candidatos, IDs recuperados y petición cuando el mecanismo se utiliza.

### Tools de BookShell

- `bookshell_get_current_book`: consulta el libro activo o actualizado más recientemente y su progreso real.
- `bookshell_update_progress`: actualiza la página mediante transacción, ajusta el estado del libro y mantiene el registro diario de lectura. Permite título aproximado y devuelve candidatos si existe ambigüedad.
- `bookshell_create_reminder`: crea un recordatorio canónico con fecha, hora, zona horaria y aviso previo.
- APIs existentes utilizadas: `GET /data/books/books`, `POST /data/transaction/books/books/{id}`, `GET /data/books/readingLog/{date}/{id}`, `POST /data/transaction/books/readingLog/{date}/{id}` y `POST /reminders` en `https://api-bookshell.charlydob.com`.
- Las descripciones de las herramientas permiten a Ollama decidirlas desde lenguaje natural; el resultado ejecutado se vuelve a insertar como dato autoritativo para impedir que el modelo lo ignore al redactar.

### Pruebas reales

- TTS Edge real: 12 segmentos breves, incluyendo cambio de párrafo; 194.832 bytes generados, media de síntesis de 0,97 s por segmento. La prueba de cola confirmó precarga durante la primera reproducción, orden íntegro y cero solapamientos.
- Feedback controlado con SQLite temporal y Ollama real: una corrección negativa se recuperó tanto para la pregunta exacta como para la variante semántica “Sintetiza este email de trabajo en puntos claros”, y quedó presente en el contexto.
- BookShell real: se consultó `Musashi 1: Earth, water and fire.` en página 221, se actualizó a 222, una segunda consulta confirmó persistencia y se restauró a 221; ambas variaciones actualizaron correctamente el reading log.
- Tool calling real: Ollama eligió respectivamente `bookshell_get_current_book`, `bookshell_update_progress` y `bookshell_create_reminder` para tres expresiones naturales. El flujo completo devolvió el título real y la página 221.
- Gateway: `10 passed`. Core: `12 passed`. Web/Vitest: `6 passed`. ESLint y build TypeScript/Vite/PWA: correctos.

### Limitaciones

- La mejora elimina la espera de síntesis entre pistas, pero la pausa exacta percibida también depende del silencio incorporado por Edge TTS y del búfer/reproductor de Safari; debe confirmarse auditivamente en el iPhone tras actualizar la PWA.
- La selección semántica añade una inferencia breve de Ollama cuando hay feedback disponible. La interfaz permite cambiar a embeddings cuando el servidor local exponga un modelo compatible.
- La API actual de BookShell declara modo de usuario único con autenticación desactivada. El adaptador admite `JARVIS_BOOKSHELL_API_TOKEN` para cuando se active Bearer auth, pero la protección definitiva debe habilitarse en BookShell.
- No se creó un recordatorio de prueba real para evitar una notificación basura; se validaron su endpoint y cuerpo canónico con prueba automatizada, y Ollama seleccionó la tool real correctamente.

### Archivos modificados

- `web/src/App.tsx`, `web/src/speech.ts`, `web/src/speechQueue.ts` y sus pruebas.
- `core/jarvis_core/feedback.py`, `storage.py`, `services.py` y sus pruebas.
- `core/jarvis_core/integrations/bookshell.py`, `.env.example`, `core/requirements.txt` y pruebas de integración.

### Commit y git status

- Implementación: `2e5d89c` (`feat: learn from feedback and connect BookShell`).
- Rama: `main`.
- Antes de añadir esta sección documental, `git status` estaba limpio. El commit documental que contiene esta sección es el `HEAD` posterior inmediato.

## Full Bookshell integration

### Módulos integrados

- Books, Gym, Habits, Finance, Reminders/agenda, World/ubicaciones, Notes y Recipes.
- BookShell sigue siendo la fuente de verdad; JARVIS consulta o modifica sus rutas existentes y no duplica estos datos en `memory.db`.

### Tools disponibles

- Books: `bookshell_books_query`, `bookshell_update_progress`.
- Gym: `bookshell_gym_query`, `bookshell_gym_write`.
- Habits: `bookshell_habits_query`, `bookshell_habits_mark`.
- Finance: `bookshell_finance_query`, `bookshell_finance_create`.
- Reminders: `bookshell_create_reminder`, `bookshell_reminders_query`, `bookshell_reminder_update`.
- World: `bookshell_world_query`, `bookshell_world_write`.
- Notes: `bookshell_notes_query`, `bookshell_notes_write`.
- Recipes: `bookshell_recipes_query`, `bookshell_recipes_write`.
- El catálogo completo de parámetros, riesgos y ejemplos está en `docs/bookshell-tools.md`.

### Endpoints y rutas usados

- Datos persistentes: `GET/PUT/PATCH/DELETE /data/{path}` y `POST /data/transaction/{path}`.
- Raíces: `/data/books`, `/data/gym/gym`, `/data/habits`, `/data/finance/finance`, `/data/world`, `/data/notes` y `/data/recipes`.
- Finanzas: `POST /shortcuts/finance/movements` con Bearer token e `Idempotency-Key`.
- Agenda: `GET/POST /reminders` y `PATCH/DELETE /reminders/{id}`.

### Operaciones read/write

- Books lee libro activo/búsquedas/progreso/porcentaje/estado/última lectura/historial/citas y actualiza página, estado y reading log.
- Gym lee sesiones, ejercicios, series, repeticiones, pesos y días desde el último entrenamiento; crea sesiones y actualiza sesiones identificadas.
- Habits lista y calcula estado, valor, racha, progreso, última realización y pendientes; escribe checks, conteos y tiempo.
- Finance lee cuentas, saldo, categorías, movimientos y agregados por periodo; prepara gastos, ingresos y transferencias mediante el endpoint idempotente protegido.
- Reminders crea, busca, filtra, reprograma, completa y cancela recordatorios con `Europe/Zurich`.
- World busca y guarda/actualiza lugares, locales y geografía. Notes y Recipes permiten búsqueda/recientes y creación/actualización básica.

### Reglas de confirmación

- Sin confirmación: lecturas; actualizar página; marcar/completar hábitos; crear recordatorio; registrar una sesión de gym; crear nota, receta o lugar cuando la intención es inequívoca.
- Confirmación obligatoria: cancelar recordatorios y desmarcar hábitos.
- Las eliminaciones destructivas no se exponen como tools. Finance pide una sola aclaración si cuenta/categoría/origen/destino no son inequívocos y falla cerrado si falta el token.
- Un pre-router por dominio reduce el catálogo antes de que Ollama elija la acción; no ejecuta por palabras clave, solo evita colisiones entre tools no relacionadas.

### Pruebas realizadas

- Datos reales: Books 221→222→221 con persistencia y restauración; Gym devolvió la sesión del 2026-08-26 y 22 días; Habits devolvió 49 hábitos y estado/racha; Finance devolvió 13 cuentas y 70 categorías; World 207 registros; Notes 127; Recipes 15.
- Reminder real temporal: creado para 2099, consultado por título y eliminado con `200`, sin dejar fixture.
- Finance real: la ruta protegida devolvió `401` sin el token completo, confirmando el bloqueo. Una fixture controlada validó cuerpo, resolución e `Idempotency-Key` sin crear un movimiento real.
- Routing natural correcto para ocho lecturas y cinco escrituras, incluyendo “Laura guardia”, “sin gym”, “último gasto”, “página 317”, “marca Alemán” y “24 francos en Migros”.
- End-to-end Core: “¿Cuántos días llevo sin ir al gimnasio?” consultó BookShell y respondió 22 días.
- Gateway `10 passed`; Core `19 passed`; Web `6 passed`; ESLint y build PWA correctos.

### Limitaciones reales

- El token completo de Shortcuts existente no se puede recuperar: BookShell solo conserva el hash y muestra prefijo/últimos caracteres. Para activar escrituras financieras hay que copiar un token completo en `JARVIS_BOOKSHELL_API_TOKEN`; no se rotó el token actual para no romper el Shortcut del iPhone.
- BookShell mantiene actualmente `auth: disabled-single-user` en las rutas genéricas; Finance Shortcuts sí exige Bearer token. La autenticación global debe endurecerse en BookShell, no duplicarse en JARVIS.
- La escritura avanzada de Gym no reconstruye plantillas ni edita arbitrariamente sets históricos; la tool crea sesiones compatibles y permite actualización básica sin exponer borrado.

### Archivos modificados

- `.env.example`.
- `core/jarvis_core/integrations/bookshell.py` y `bookshell_domains.py`.
- `core/jarvis_core/services.py` y `tools.py`.
- `core/tests/test_bookshell_domains.py` y `test_tools.py`.
- `docs/bookshell-tools.md`.

### Commit final

- Implementación: `87ab6bf` (`feat: integrate full BookShell tool catalog`).
- La sección documental forma el commit posterior inmediato.

### Git status

- Rama `main`; árbol limpio antes de añadir esta sección documental.

## Language stability + latency + tool reliability

### Causas raíz

- Idioma: cada turno aceptaba directamente el idioma indicado por Whisper o `langdetect`; no existía un idioma persistente por conversación ni un umbral que protegiera palabras cortas, transcripciones ruidosas o detecciones inesperadas.
- Tools: cuando el router no encontraba un dominio devolvía las 17 definiciones. Además, el resultado de una tool se entregaba al modelo sin bloquear de forma determinista una confirmación falsa si la ejecución fallaba o pedía aclaración.
- Latencia: una conversación normal cargaba todas las tools; el feedback podía provocar una inferencia adicional aunque no hubiera similitud; se enviaban 20 mensajes históricos y consultas evidentes de Books/Reminders pagaban una ronda de Ollama solo para elegir una tool inequívoca.
- Animación: el estado `listening` nuevo sustituía el movimiento relajado por ojos azules abiertos, boca plana y asentimientos, eliminando el desplazamiento flotante anterior.

### Solución aplicada

- `SessionLanguagePolicy` mantiene español por defecto y un idioma por `conversation_id`. Las peticiones explícitas cambian al instante; una frase larga y muy clara puede cambiar, mientras que frases medias deben coincidir en dos turnos. Detecciones cortas, débiles, no soportadas o aisladas mantienen el idioma actual. La probabilidad real de Whisper llega ahora desde `/api/audio` hasta el Core.
- El idioma devuelto por Core es el idioma de sesión validado. La PWA conserva ese idioma para TTS y el sintetizador comprueba el texto real con fallback estable para segmentos breves.
- El router ligero devuelve 0 tools para conversación normal y como máximo 3 por dominio. Las lecturas inequívocas “página actual” y “recordatorios de hoy” se ejecutan directamente, sin una inferencia de selección; las escrituras y peticiones ambiguas siguen pasando por tool calling.
- Los logs incluyen `tool_requested`, `tool_executed`, `tool_success` y `tool_error`. Un fallo, configuración incompleta o aclaración se devuelve directamente y nunca pasa por una redacción capaz de fingir éxito. Un recordatorio sin hora responde `¿A qué hora, señor?` y no llama a BookShell.
- Se añadieron tiempos estructurados para STT, contexto externo, feedback, selección de tools, decisión de tools, primer token y total de Ollama, ejecución de tool, primer audio TTS y total del chat.
- El historial enviado bajó de 20 a 8 mensajes; el feedback irrelevante toma una salida léxica rápida; contexto externo y feedback se preparan en paralelo; Ollama conserva `keep_alive=10m`.
- Las respuestas son breves por defecto mediante la instrucción de sistema, sin limitar artificialmente respuestas largas solicitadas.
- `idle` y `listening` vuelven a compartir ojos blancos suaves, parpadeo/respiración y deriva lenta de lado a lado basada en la animación anterior. No se modificó el SVG.

### Timings antes/después

Medidos contra el mismo Ollama local calentado, con base SQLite temporal. TTFT y total en milisegundos:

| Escenario | Antes TTFT / total | Después TTFT / total |
| --- | ---: | ---: |
| Conversación normal | 25.361 / 26.030 | 0.809 / 1.641 |
| Books, página actual | 9.172 / 11.015 | 7.200 / 9.309 |
| Reminders, hoy | 6.098 / 6.901 | 2.564 / 3.360 |
| Escritura de recordatorio | 17.117 / 20.133 | 16.753 / 19.030 |

La escritura mantiene dos rondas de Ollama porque debe extraer y validar argumentos antes de confirmar. El script reproducible es `scripts/measure_core_latency.py`. En la ruta normal medida, contexto/feedback/routing consumieron menos de 2 ms y el primer token llegó en unos 0,8 s; el coste restante fue Ollama.

### Pruebas y verificación real

- Idioma: secuencia automatizada de 10 turnos ES → ES con palabra inglesa → español ruidoso → EN claro → EN corto → detección portuguesa débil → ES claro; no hubo cambios por señales débiles. También se probaron dos turnos alemanes consistentes y cambio explícito.
- Recordatorio sin hora: devolvió aclaración y realizó cero peticiones HTTP.
- Fallo forzado de BookShell: la respuesta fue `No he podido completar esa acción.` y no incluyó “creado”.
- BookShell real: se creó `Prueba temporal de JARVIS` para `2099-12-31 23:57`, se volvió a consultar con el mismo ID/fecha/hora y luego se canceló. Las dos fixtures generadas por las mediciones quedaron canceladas.
- Tool routing: conversación normal 0 tools; dominio limitado a 3; Books y Reminders evidentes usan lectura determinista.
- Animación: `listening.ts` reutiliza `startIdleAnimation`; `idle.ts` contiene la deriva flotante de 9 s y movimiento suave de ojos/boca recuperado del historial.
- Core: `25 passed`. Gateway: `10 passed`. Web: `6 passed`. ESLint y build TypeScript/Vite/PWA: correctos.

### Archivos modificados

- Core: `language.py`, `services.py`, `tools.py`, `feedback.py`, integración BookShell y pruebas.
- Gateway/PWA: modelo de confianza de idioma, cliente, `App.tsx`, animaciones `idle`/`listening`.
- Medición: `scripts/measure_core_latency.py`.

### Commits y estado

- Core/gateway: `53792e0` (`fix: stabilize language tools and latency`).
- PWA/animación: `6704585` (`fix: restore relaxed listening motion`).
- Rama `main`; árbol limpio antes de este bloque documental. El commit documental es el siguiente commit.

### Pendiente

- Google Sheets queda expresamente como integración futura. BookShell continúa siendo la fuente principal.
- La escritura genérica sigue dependiendo de una ronda de selección de Ollama; solo se aceleraron lecturas inequívocas para no introducir ejecuciones incorrectas.

## Reliability + zero-hallucination tools + latency v2

### Causas raíz

- Escrituras falsas: las tools podían devolver una respuesta HTTP sin comprobar que el valor aparecía realmente en una lectura posterior. El modelo recibía ese resultado y aún podía redactar una confirmación positiva.
- Recordatorios incompletos: la extracción general mediante Ollama no mantenía de forma determinista la fecha y el título entre el turno “clase el viernes” y la respuesta “a las 18”.
- Loops y duplicados: el audio, el turno y los eventos SSE no compartían identificadores idempotentes; una reconexión o listener repetido podía volver a procesar una entrada ya resuelta.
- Silencio: se enviaban grabaciones a Whisper sin un filtro obligatorio de duración, voz detectada y energía, y una transcripción repetida podía volver a entrar en conversación.
- Etiqueta `assistant`: podía llegar como prefijo generado por Ollama o permanecer en datos históricos; la interfaz no la normalizaba.
- Latencia: incluso las intenciones obvias de Books y Reminders pagaban selección de tool y una segunda generación de Ollama. Las escrituras de página también repetían lecturas que ya se habían realizado.

### Correcciones

- Las escrituras de página, recordatorio, gym, nota y gasto hacen `write → read-back`. El Core solo considera exitosa una tool de escritura si recibe `verified: true`; de lo contrario responde “No se pudo guardar, señor.”
- Un router determinista resuelve libro actual, progreso, actualización de página, recordatorios de hoy y creación de recordatorios. Si falta fecha u hora pregunta únicamente el dato ausente. “El viernes” se resuelve al próximo viernes razonable y la aclaración siguiente conserva título y fecha.
- Cada entrada usa `utterance_id`, cada petición `turn_id` y cada ejecución `tool_call_id`. Core memoriza resultados de audio/turno, comparte una petición ya en curso y la PWA descarta eventos SSE ya vistos.
- El filtro de audio exige 500 ms de captura, 300 ms de voz, RMS mínimo `0.014` y 1000 bytes. También descarta vacío, ruido conocido y la misma transcripción repetida durante 8 segundos. Los logs registran `audio_duration`, `speech_ms`, `rms`, `transcript` y `discard_reason`.
- El prefijo literal `assistant` se elimina al recibir el stream, antes de persistir y al renderizar historial o respuesta actual.
- Las rutas comunes usan tool directa y plantilla breve, sin Ollama. El modelo se mantiene caliente durante la conexión y las fases STT, routing, selección, pre-LLM, TTFT/total de Ollama, tool, read-back, TTS y total quedan instrumentadas con el mismo `turn_id`.

### Timings antes/después

Tiempos reales observados por el usuario frente a la verificación final local contra BookShell real, en milisegundos:

| Escenario | Antes total | Después TTFT / total |
| --- | ---: | ---: |
| Libro actual | 27.000 | 1.284 / 1.285 |
| Página actual | 20.000 | 1.109 / 1.112 |
| Actualizar página | 19.000 | 2.850 / 2.852 |
| Recordatorios de hoy | 30.000 | 0.347 / 0.350 |
| Crear recordatorio | 17.000 | 0.751 / 0.752 |
| Conversación normal calentada | — | 0.356 / 1.180 |

Las lecturas simples quedan por debajo de 2 s y las escrituras verificadas por debajo de 3 s en esta ejecución. Los tiempos dependen de red, Ollama y BookShell, pero cada fase queda registrada para localizar regresiones reales.

### BookShell real y persistencia verificada

- Libro actual: `Musashi`, id `-OzHVYhCmxL5Tdo_9Z9N`, página inicial 221.
- Progreso: escritura real 221 → 220, lectura posterior confirmó 220; restauración 220 → 221, lectura posterior confirmó 221.
- Recordatorio temporal: creado para `2099-12-30 23:41`, leído de vuelta con el mismo ID/fecha/hora y cancelado. La lectura final devolvió estado cancelado o ausencia, según el filtrado de BookShell.
- Fallo controlado: una tool de recordatorio que lanza error produce `No se pudo guardar, señor.` y nunca contiene una confirmación de creación.

El script reproducible es `scripts/verify_reliability_v2.py` y deja restaurada la página original y cancelada la fixture temporal.

### Pruebas

- Stress de 20 turnos consecutivos más silencio y transcripción duplicada: 0 respuestas duplicadas, 0 turnos fantasma, una sola ejecución por `turn_id` repetido y 0 confirmaciones de escritura sin `verified: true`.
- Recordatorio multiturno: “Clase de alemán el viernes” pregunta la hora; “A las 18” crea argumentos completos conservando título y fecha.
- Core: `32 passed`. Gateway: `10 passed`. Web: `6 passed`. ESLint y build TypeScript/Vite/PWA: correctos.

### Archivos cambiados

- Core: `core/jarvis_core/intents.py`, `services.py`, `main.py`, integraciones `bookshell.py` y `bookshell_domains.py`.
- Gateway: `backend/app/models.py`, `main.py` y `relay.py`.
- PWA: `web/src/App.tsx`, `web/src/api/client.ts` y `web/src/hooks/useContinuousVoice.ts`.
- Pruebas y verificación: `core/tests/test_intents.py`, `test_reliability.py`, pruebas existentes actualizadas y `scripts/verify_reliability_v2.py`.

### Commits y estado

- Core/gateway: `f9ad202` (`fix: verify tool writes and deduplicate turns`).
- PWA: `fb4c07d` (`fix: deduplicate voice and stream events`).
- Este bloque documental forma el commit posterior inmediato. Google Sheets y animaciones avanzadas no se tocaron.

## iPhone voice + reminder state consistency

### Captura de voz

- La captura usa ahora una máquina estricta `IDLE → LISTENING → FINALIZING → TRANSCRIBING → PROCESSING → SPEAKING → IDLE` con un UUID por utterance.
- Cada inicio vacía el buffer. `FINALIZING` solo se puede solicitar una vez y, al construir el Blob, los chunks se extraen y borran inmediatamente.
- Hay watchdog independiente de silencio, límite máximo de grabación de 30 segundos y timeout de cierre de `MediaRecorder`.
- Durante transcripción, procesamiento y TTS la pista del micrófono queda deshabilitada; se reactiva únicamente al volver a escucha.
- Los logs del navegador incluyen `utterance_id`, inicio, detección de voz, silencio, finalización, duración, bytes, comienzo de transcripción, texto y descarte. El Core colapsa además frases consecutivas idénticas dentro de una sola transcripción.
- La prueba de máquina ejecuta 20 utterances consecutivas: cada una finaliza una sola vez y el buffer queda a cero antes de la siguiente.

### Hora, pending action y BookShell

- Las horas habladas de 12 horas se resuelven en `Europe/Zurich`. Para hoy se elige la única interpretación futura; si ambas son futuras pregunta, y si todas pasaron no crea nada.
- `pending_action` conserva título, fecha, clave idempotente y momento de creación durante diez minutos. Solo se elimina tras `verified: true`; los reintentos simultáneos comparten lock/resultado por clave idempotente.
- CREATE envía `Idempotency-Key`. La lectura posterior y las consultas de hoy usan `Cache-Control: no-cache`; “hoy” conserva recordatorios vencidos y excluye cancelados.
- Libro/página, recordatorios de hoy y último entrenamiento usan tool real en cada turno, sin memoria como fuente factual.

### Audio y permisos de iOS

- Se detecta `navigator.audioSession`. Antes de grabar se usa `play-and-record`; durante TTS se deshabilita la pista de entrada y se usa `playback`; al terminar se restaura captura.
- No se intenta seleccionar un dispositivo de salida con APIs inexistentes. WebKit mantiene incidencias conocidas de routing mientras `getUserMedia` está activo; por eso la verificación física sigue siendo necesaria en el iPhone objetivo.
- `getUserMedia` se llama una vez por sesión de página y se reutiliza el stream vivo. Se registran contador, razón, reutilización y recreación. `pagehide` libera las pistas.
- Tras cerrar completamente y reabrir una PWA, una nueva solicitud de permiso puede depender de WebKit/iOS y no puede evitarse de forma segura desde JavaScript.

### Verificación real

- `Anota que hoy tengo clase de alemán` preguntó hora sin escribir.
- `A las cinco y media` se resolvió como `17:30`, creó un solo recordatorio y verificó el read-back.
- Dos consultas consecutivas de `¿Qué tengo hoy?` volvieron a BookShell y devolvieron inmediatamente la clase.
- Fixture `97be3928-2b50-4fae-89e6-96d3c5d83027` cancelada; lectura final ausente.
- Tiempos: aclaración 234,8 ms; crear+verificar 680,7 ms; consultas frescas 357,1 ms y 347,1 ms.
- Core `48 passed`; PWA `7 passed`; ESLint y build correctos. La prueba física de 20 utterances y routing de altavoz debe completarse en el iPhone real del usuario; no se declara realizada desde el entorno de desarrollo.
