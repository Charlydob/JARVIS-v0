# BookShell tools for JARVIS

BookShell is the source of truth. These tools read or mutate its existing API; JARVIS does not copy this domain data into its own memory database. Dates default to `Europe/Zurich` through `JARVIS_BOOKSHELL_TIMEZONE`.

| Tool | Description | Main parameters | Type | Confirmation | Natural-language example |
|---|---|---|---|---|---|
| `bookshell_books_query` | Current book, title search, progress, state, reading history and book notes/quotes. | `mode: current\|progress\|search\|history\|notes`, `title?`, `limit?` | Read | No | “¿Cuánto me queda de Dune?” |
| `bookshell_update_progress` | Updates the current page, reading status and daily reading log. | `page`, `title?` | Write | No when book is unambiguous | “Apunta que voy por la 317 de Dune.” |
| `bookshell_gym_query` | Last/recent sessions, days since training and exercise/set/weight history. | `mode: last\|days_since\|recent\|exercise`, `exercise?`, `limit?` | Read | No | “¿Cuánto levanté la última vez en press banca?” |
| `bookshell_gym_write` | Creates a completed session with optional exercises or renames an identified session. | `action: create\|update`, `session_id?`, `date?`, `name?`, `exercises?` | Write | No when intent and exercise are clear | “Registra 3 series de 10 con 70 kilos.” |
| `bookshell_habits_query` | Lists scheduled habits or returns status, value, progress, last completion, days and streak. | `mode: list\|status\|pending`, `name?`, `date?` | Read | No | “¿Qué hábitos tengo pendientes hoy?” |
| `bookshell_habits_mark` | Marks a check habit or writes the count/time value for a quantitative habit. | `name`, `date?`, `completed?`, `value?`, `unit?`, `confirmed?` | Write | No to add/complete; yes to unmark | “Marca que hoy hice alemán.” |
| `bookshell_finance_query` | Accounts/balances, categories, movements, latest movement and expense/income totals. | `mode`, `type?`, `category?`, `period?`, `from_date?`, `until_date?`, `limit?` | Read | No | “¿Cuánto he gastado en comida este mes?” |
| `bookshell_finance_create` | Creates an idempotent expense, income or transfer through BookShell Shortcuts API. | `type`, `amount`, `currency?`, `description?`, `category?`, `account?`, `from_account?`, `to_account?`, `date?`, `idempotency_key?` | Write | Only when account/category/transfer is ambiguous | “Añade un gasto de 24 CHF en Migros.” |
| `bookshell_create_reminder` | Creates a canonical reminder with an exact or relative date and alerts. | `title`, `description?`, `target_date?`, `relative_day?`, `target_time?`, `minutes_before?` | Write | No when date is clear | “Recuérdame llamar al dentista mañana a las 10.” |
| `bookshell_reminders_query` | Searches reminders by today/week, dates, text, person, event type and status. | `scope?`, `query?`, `person?`, `event_type?`, `status?`, `from?`, `until?`, `limit?` | Read | No | “¿Cuándo tiene Laura guardia esta semana?” |
| `bookshell_reminder_update` | Reschedules/edits, completes or cancels an identified reminder. | `reminder_id`, `action`, edit fields, `confirmed?` | Write | Cancellation requires confirmation | “Cambia el recordatorio de mañana a las 12.” |
| `bookshell_world_query` | Searches saved places, locals, geography and stays by text/location/category, including rating. | `scope?`, `query?`, `city?`, `category?`, `country?`, `limit?` | Read | No | “¿Qué cafeterías guardé en Interlaken?” |
| `bookshell_world_write` | Creates or updates a saved place/local/geography record without deleting. | `action`, `scope`, `item_id?`, location and rating fields | Write | No when place is identified | “Guarda este sitio como cafetería.” |
| `bookshell_notes_query` | Searches note title/content/tags or returns recent notes. | `query?`, `limit?` | Read | No | “Busca mis notas sobre alemán.” |
| `bookshell_notes_write` | Creates or updates a basic text note; deletion is not exposed. | `action`, `note_id?`, `title?`, `content?`, `category?`, `folderId?`, `tags?` | Write | No when note is identified | “Crea una nota con estas ideas.” |
| `bookshell_recipes_query` | Searches recipes and returns their persisted ingredients and steps. | `query?`, `limit?` | Read | No | “Busca la receta del sándwich de huevo.” |
| `bookshell_recipes_write` | Creates or updates a recipe when its structure is clear; deletion is not exposed. | `action`, `recipe_id?`, `title?`, `notes?`, `meal?`, `servings?`, `tags?`, `ingredients?`, `steps?` | Write | No when recipe is identified | “Añade esta receta para dos personas.” |

## Safety and routing

- JARVIS first narrows the available definitions to the relevant BookShell domain, then Ollama chooses the exact read/write tool and arguments.
- Destructive deletes are not exposed. Cancelling a reminder and unmarking a habit return `confirmationRequired` until `confirmed=true` is supplied.
- Finance writes use BookShell's `Idempotency-Key`. They fail closed unless `JARVIS_BOOKSHELL_API_TOKEN` contains the full Shortcuts bearer token.
- Ambiguous books, exercises, accounts or categories return candidates/a short clarification instead of guessing.
- Relative periods (`today`, `tomorrow`, `week`, `month`) are resolved inside the integration using the configured timezone.

## Existing BookShell API routes used

- Generic persisted data: `GET/PUT/PATCH/DELETE /data/{path}`, `POST /data/transaction/{path}`.
- Finance: `GET /data/finance/finance` and protected `POST /shortcuts/finance/movements`.
- Reminders: `GET/POST /reminders`, `PATCH/DELETE /reminders/{id}`.
- Domain roots: `/data/books`, `/data/gym/gym`, `/data/habits`, `/data/world`, `/data/notes`, `/data/recipes`.
