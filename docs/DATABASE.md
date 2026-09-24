# Databas

Oden använder en enda SQLite-fil: `{oden_home}/config.db` (standard `~/.oden/config.db`).

Alla tabeller finns i samma fil. Schema skapas och migreras vid uppstart av `config_db.init_db()`.

## Schemaversion

Spåras i tabellen `metadata` under nyckeln `schema_version`. Nuvarande version: **5**.
Migrationer är additiva och nedgraderas aldrig.

---

## Tabeller

### `metadata`

Intern nyckel/värde-tabell för schemahantering.

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `key` | TEXT PK | t.ex. `schema_version` |
| `value` | TEXT | |

---

### `config`

Alla användarkonfigurerbara inställningar. En rad per nyckel.

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `key` | TEXT PK | Inställningsnyckel |
| `value` | TEXT | Serialiserat värde |
| `type` | TEXT | `str`, `int`, `bool` eller `json` |

Booleska värden lagras som `"true"`/`"false"`. JSON-värden (listor, dict) lagras som JSON-strängar.
Läsningar faller tillbaka till `DEFAULT_CONFIG` i [config_db.py](../oden/config_db.py) när en nyckel saknas.

**Kända nycklar** (från `DEFAULT_CONFIG` / `TYPE_MAP`):

| Nyckel | Typ | Standard | Notering |
| --- | --- | --- | --- |
| `vault_path` | str | `~/oden-vault` | Sökväg där markdownrapporter skrivs |
| `signal_number` | str | — | Signal-kontonummer |
| `display_name` | str | `oden` | Visningsnamn för utgående meddelanden |
| `signal_cli_path` | str | — | Sökväg till signal-cli-binär |
| `signal_cli_host` | str | `127.0.0.1` | |
| `signal_cli_port` | int | `7583` | |
| `signal_cli_log_file` | str | — | |
| `diagnostic_mode` | bool | `true` | |
| `unmanaged_signal_cli` | bool | `false` | Starta/stoppa inte signal-cli |
| `timezone` | str | `Europe/Stockholm` | |
| `append_window_minutes` | int | `30` | Reply-fönster för append till befintlig rapport |
| `group_split_enabled` | bool | `true` | Spara utdata under `vault/<group>/` när aktiverat |
| `startup_message` | str | `self` | Vem som får startmeddelandet |
| `ignored_groups` | json | `[]` | Äldre, används inte — ersatt av ignorera-grenar i `routing` |
| `whitelist_groups` | json | `[]` | Äldre, används inte — ersatt av `routing` |
| `filename_format` | str | `classic` | |
| `log_level` | str | `INFO` | |
| `log_file` | str | — | Plattformens standard om ej satt |
| `web_enabled` | bool | `true` | |
| `web_port` | int | `8080` | |
| `web_access_log` | str | — | |
| `auto_reaction_enabled` | bool | `false` | Skicka emoji-reaktion vid mottagning |
| `auto_reaction_emoji` | str | `✅` | |
| `auto_read_receipt_enabled` | bool | `false` | |
| `db_first_enabled` | bool | `true` | Persista råmeddelanden före bearbetning |
| `report_formats` | json | `[]` | Egna rapportformat (rubriker, fält, avsnitt, TNR-fält, mall); varje format blir steget `format:<id>`. Se [PIPELINES.md](PIPELINES.md#rapportformat-formatid) |
| `routing` | json | se källa | Vägval och grenar: källa → gren, stegen per gren. Det som körs — se [PIPELINES.md](PIPELINES.md) |
| `enabled_pipelines` | json | se källa | Den gamla kedjan; används bara för att skapa `routing` vid uppgradering |
| `pipeline_settings` | json | se källa | Per-pipeline-konfiguration |
| `raw_message_retention_days` | int | `30` | Fönster för automatisk rensning |
| `raw_message_max_mb` | int | `0` | Max storlek på lagrade råmeddelanden i MB; äldsta tas bort först. `0` = ingen gräns |
| `signal_typing_indicators` | bool | `false` | |
| `signal_link_previews` | bool | `false` | |
| `signal_unidentified_delivery_indicators` | bool | `false` | |
| `report_template` | str | — | Jinja2-mall för nya rapporter |
| `append_template` | str | — | Jinja2-mall för appendposter |

---

### `responses`

Autosvarsmallar som triggas av nyckelordskommandon (t.ex. `#help`, `#ok`).

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | |
| `keywords` | TEXT | JSON-array med nyckelord i gemener |
| `body` | TEXT | Markdown-svarstext |

Uppslag använder `json_each` för skiftlägesokänslig nyckelordsmatchning.
Seedas med standardvärdena `help`/`hjälp` och `ok` vid första migrationen.

---

### `groups`

Signal-gruppcache som fylls på från `listGroups` och överlever omstarter.

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `group_id` | TEXT | Signal-grupp-ID (base64) |
| `account` | TEXT | Signal-kontonummer |
| `name` | TEXT | Visningsnamn |
| `member_count` | INTEGER | Senast kända medlemsantal |
| `is_member` | INTEGER | `1` = fortfarande medlem |
| `last_seen` | TEXT | ISO-8601 UTC-tidsstämpel för senaste upsert |

Primärnyckel: `(group_id, account)` — stöder multi-account.

---

### `raw_messages`

*(Tillagd i schema v5 — kräver `db_first_enabled = true`)*

Varje inkommande meddelande lagras oförändrat innan pipeline-bearbetning — från
**Signal** och från **TAK**. TAK-händelser (CoT-strömmen och data-paket från
serverns filarkiv) som klarar inkommande-filtren görs om till ett Signal-likt
kuvert (`oden/tak/listener.py`, `build_envelope`) och går sedan samma väg genom
pipelinekedjan. Det är den här tabellen fliken **Flöde** visar.

| | Signal | TAK |
| --- | --- | --- |
| `account` | Kontot som tog emot meddelandet | Det konfigurerade Signal-numret (platshållaren `+46XXXXXXXXX` om Oden körs utan Signal) — säger inget om källan |
| `source_number` | Avsändarens nummer | `tak:<enhets-id>` — så känns TAK igen |
| `envelope_raw` | signal-cli:s JSON | `{"envelope": {..., "_source": "tak", "_cot_xml": "<event …>", ...}}`; `_cot_xml` är CoT:en som den kom (högst 200 000 tecken), `dataMessage.message` texten som gjordes vid mottagningen; bilagor ligger inbäddade som base64 |

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | `message_id` som används i nedströms-tabeller |
| `account` | TEXT | Signal-kontonummer (se ovan för TAK) |
| `timestamp_utc` | TEXT | ISO-8601 UTC från Signal-envelope |
| `envelope_raw` | TEXT | Full JSON-envelope |
| `source_number` | TEXT | Avsändarens telefonnummer, eller `tak:<enhets-id>` |
| `source_name` | TEXT | Avsändarens visningsnamn |
| `group_id` | TEXT | Signal-grupp-ID (nullable för DM) |
| `group_name` | TEXT | Gruppnamn vid mottagningstillfället |
| `message_body` | TEXT | Ren text extraherad från `dataMessage` |
| `has_attachments` | INTEGER | `1` om bilagor finns |
| `status` | TEXT | Se livscykel nedan |
| `status_timestamp` | TEXT | ISO-8601 UTC för senaste statusändring |
| `created_at` | TEXT | ISO-8601 UTC, default `strftime(…,'now')` |

**Statuslivscykel:** `received` → `queued` → `processing` → `processed` | `failed` | `ignored`

`source_number`, `source_name`, `group_name` och `message_body` kan vara `NULL` beroende på envelope-innehåll.

**Index:**

- `idx_raw_messages_account_ts` på `(account, timestamp_utc DESC)`
- `idx_raw_messages_status` på `(status)`

Rensas av `retention_db` enligt `raw_message_retention_days` och `raw_message_max_mb` — se [Retention](#retention-datarensning).

---

### `pipeline_runs`

En rad per exekveringsförsök för (meddelande, pipeline).

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | `run_id` |
| `message_id` | INTEGER FK → `raw_messages.id` | Cascade delete |
| `pipeline_name` | TEXT | t.ex. `seven_s`, `group_filter` |
| `status` | TEXT | Se livscykel nedan |
| `started_at` | TEXT | ISO-8601 UTC |
| `completed_at` | TEXT | ISO-8601 UTC |
| `output_file` | TEXT | Sökväg till genererad vault-fil (om någon) |
| `error_code` | TEXT | Kort felklass vid fel |
| `error_message` | TEXT | Mänskligt läsbar feldetalj |

**Statuslivscykel (schema):** `pending` → `running` → `done` | `failed` | `skipped`

I nuvarande implementation skapas nya körningar direkt i `running` av `start_pipeline_run()`.

`skipped` betyder att meddelandet inte matchade pipeline-filtret, inte att ett fel uppstod.

**Index:**

- `idx_pipeline_runs_message_id` på `(message_id)`
- `idx_pipeline_runs_status` på `(pipeline_name, status)`

---

### `pipeline_events`

Strukturerad händelselogg per pipeline-körning — endast append.

| Kolumn | Typ | Notering |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_id` | INTEGER FK → `pipeline_runs.id` | Cascade delete |
| `event_type` | TEXT | t.ex. `match`, `write`, `error` |
| `occurred_at` | TEXT | ISO-8601 UTC, default `strftime(…,'now')` |
| `details` | TEXT | JSON-blob (nullable) |

**Index:** `idx_pipeline_events_run_id` på `(run_id)`

---

## Retention (datarensning)

**När:** `retention_db.run_retention_loop()` startas av Odens livscykel
(`s7_watcher._run_lifecycle`) och kör rensningen **direkt vid start och sedan en
gång i timmen** (`RETENTION_INTERVAL_SECONDS = 3600`), i en egen tråd. Den är
oberoende av Signal, så även en installation som bara kör TAK rensas. Knappen
**Rensa nu** under *Avancerat → Lagring* (`POST /api/storage/cleanup`) kör den
direkt med de sparade inställningarna.

**Vad:** `cleanup_old_data(db_path, retention_days, max_mb)` raderar i en transaktion:

1. `pipeline_events` äldre än cutoff (via `occurred_at`)
2. `raw_messages` äldre än cutoff (via `created_at`) med deras `pipeline_runs` och `pipeline_events`
3. om `max_mb > 0` och de råa kuverten (`SUM(LENGTH(CAST(envelope_raw AS BLOB)))`)
   är större: de äldsta `raw_messages` (lägst `id`) med körningar och händelser,
   tills resten ryms

Därefter körs `VACUUM` om minst 25 % av filen (och minst 8 MB) blivit ledigt,
så att databasfilen faktiskt krymper. Valvets filer rörs aldrig.

`GET /api/storage` visar antal meddelanden (varav TAK), storlek på rådata och
databasfil, äldsta meddelande och resultatet av senaste rensningen.

`config`, `metadata`, `responses` och `groups` rensas aldrig av retention-jobbet.

---

## Källfiler

| Fil | Ansvar |
| --- | --- |
| [oden/config_db.py](../oden/config_db.py) | Schemainitiering, migrationer, config-CRUD |
| [oden/messages_db.py](../oden/messages_db.py) | CRUD för `raw_messages` |
| [oden/pipelines_db.py](../oden/pipelines_db.py) | CRUD för `pipeline_runs` och `pipeline_events` |
| [oden/groups_db.py](../oden/groups_db.py) | CRUD för `groups` |
| [oden/responses_db.py](../oden/responses_db.py) | CRUD för `responses` |
| [oden/retention_db.py](../oden/retention_db.py) | Tidsbaserad rensning |
