# Contrato JARVIS ↔ BookShell

BookShell es la fuente de verdad. JARVIS Core accede desde el PC a `https://api-bookshell.charlydob.com/jarvis/*`; el navegador y el gateway público nunca reciben la credencial. Todas las fechas se interpretan con `JARVIS_BOOKSHELL_TIMEZONE` (por defecto `Europe/Zurich`).

## Matriz auditada

| Dominio / operación humana | Tool | R/W | Endpoint | Datos y lógica de negocio | Resultado de auditoría |
|---|---|---:|---|---|---|
| Books: actual, búsqueda, página, historial | `bookshell_books_query` | R | `GET /jarvis/books`; notas mediante `/jarvis/data/books/links` | Página, total, porcentaje, última lectura e historial | API dedicada adecuada |
| Books: “actualiza Musashi a 222” | `bookshell_update_progress` | W | `PATCH /jarvis/books/progress` | Transacción atómica: `currentPage`, reading log, timestamps y transición finished/reading; read-back | Sustituye dos escrituras genéricas no atómicas |
| Gym: última sesión, días, ejercicio/carga | `bookshell_gym_query` | R | `GET /jarvis/data/gym/gym` | Lee el esquema canónico y calcula vistas sin copiar datos | Adecuado |
| Gym: registrar sesión | `bookshell_gym_write` | W | `POST /jarvis/gym/sessions` | Calcula repeticiones/volumen, actualiza plantilla, usa idempotencia y read-back | API dedicada añadida |
| Habits: listar, pendientes, racha, última realización | `bookshell_habits_query` | R | `GET /jarvis/data/habits` | Calcula calendario/racha desde stores canónicos | Adecuado |
| Habits: registrar cumplimiento | `bookshell_habits_mark` | W | `POST /jarvis/habits/mark` | Escribe check/count/time de forma atómica y verificable | API dedicada añadida |
| Finance: cuentas, categorías, movimientos, saldos | `bookshell_finance_query` | R | `GET /jarvis/data/finance/finance` | Conserva monedas, catálogo y movimientos reales | Adecuado |
| Finance: gasto, ingreso, transferencia | `bookshell_finance_create` | W | `POST /jarvis/finance/movements` | Lógica canónica de validación, FX, cuentas y categorías; idempotencia + read-back | Dejó de reutilizar token/ruta de Shortcuts |
| Reminders/agenda/guardias: rangos y búsqueda | `bookshell_reminders_query` | R | `GET /jarvis/reminders` | Rangos locales; hoy incluye vencidos; `eventType`/`subject` con fallback legado | API dedicada adecuada |
| Reminders: crear/editar/completar/cancelar | tools reminders | W | `POST/PATCH/DELETE /jarvis/reminders...` | Conserva alertas, recurrencia, estados e idempotencia; read-back | API dedicada protegida |
| Notes: recientes/buscar/crear/actualizar | tools notes | R/W | `/jarvis/data/notes/notes` | El árbol persistido es el modelo canónico; writes verifican | No requiere endpoint adicional |
| World: buscar/guardar/actualizar | tools world | R/W | `/jarvis/data/world` | Modelo canónico de lugares/categorías; sin borrado expuesto | No requiere endpoint adicional |
| Recipes (prioridad baja) | tools recipes | R/W | `/jarvis/data/recipes/items` | Estructura canónica existente | Sin ampliación |

## Autenticación

- Credencial propia: `Authorization: Bearer <JARVIS_BOOKSHELL_API_TOKEN>`.
- BookShell guarda solo SHA-256 en `jarvis_api_tokens`, con scopes `dominio:read` / `dominio:write`.
- El valor bruto vive únicamente en el `.env` del Core Windows; no llega a frontend, gateway ni Shortcuts.
- Para rotar: generar token aleatorio, insertar SHA-256 y scopes, configurar el valor bruto en Core y poner `revoked_at=NOW()` al anterior.
- Token ausente/revocado o scope insuficiente devuelve 401/403.

## Garantías y pruebas

- Los verbos de escritura tienen prioridad sobre las lecturas.
- Datos dinámicos siempre consultan BookShell.
- Solo se confirma una escritura si API + read-back coinciden.
- Finanzas, recordatorios y gimnasio aceptan `Idempotency-Key`.
- Los logs guardan endpoint, parámetros, HTTP status, resumen y verificación sin secretos.
- Unitarias: `core/tests/test_bookshell.py`, `test_bookshell_domains.py`, `test_intents.py`.
- Contrato real reversible: `scripts/test-bookshell-contract.ps1`; exige `JARVIS_BOOKSHELL_API_TOKEN` y `-Write` para mutaciones.
