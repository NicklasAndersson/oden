# Database

Oden uses a single SQLite file: `{oden_home}/config.db` (default `~/.oden/config.db`).

All tables live in this one file. Schema is created and migrated at startup by `config_db.init_db()`.

## Schema version

Tracked in the `metadata` table under key `schema_version`. Current version: **5**.
Migrations are additive-only and never downgrade.

---

## Tables

### `metadata`
Internal key/value store for schema housekeeping.

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PK | e.g. `schema_version` |
| `value` | TEXT | |

---

### `config`
All user-configurable settings. One row per key.

| Column | Type | Notes |
|--------|------|-------|
| `key` | TEXT PK | Setting name (see below) |
| `value` | TEXT | Serialized value |
| `type` | TEXT | `str`, `int`, `bool`, or `json` |

Boolean values are stored as `"true"`/`"false"`. JSON values (lists, dicts) are stored as JSON strings.
Reads fall back to `DEFAULT_CONFIG` in [config_db.py](../oden/config_db.py) when a key is absent.

**Known keys** (from `DEFAULT_CONFIG` / `TYPE_MAP`):

| Key | Type | Default | Notes |
|-----|------|---------|-------|
| `vault_path` | str | `~/oden-vault` | Where markdown reports are written |
| `signal_number` | str | — | The Signal account number |
| `display_name` | str | `oden` | Display name for outgoing messages |
| `signal_cli_path` | str | — | Path to signal-cli binary |
| `signal_cli_host` | str | `127.0.0.1` | |
| `signal_cli_port` | int | `7583` | |
| `signal_cli_log_file` | str | — | |
| `diagnostic_mode` | bool | `false` | |
| `unmanaged_signal_cli` | bool | `false` | Don't start/stop signal-cli |
| `timezone` | str | `Europe/Stockholm` | |
| `append_window_minutes` | int | `30` | Reply window for appending to existing report |
| `startup_message` | str | `self` | Who gets the startup notification |
| `ignored_groups` | json | `[]` | Group IDs to silently drop |
| `whitelist_groups` | json | `[]` | If non-empty, only process these groups |
| `filename_format` | str | `classic` | |
| `log_level` | str | `INFO` | |
| `log_file` | str | — | Platform default if unset |
| `web_enabled` | bool | `true` | |
| `web_port` | int | `8080` | |
| `web_access_log` | str | — | |
| `auto_reaction_enabled` | bool | `false` | Send emoji reaction on receipt |
| `auto_reaction_emoji` | str | `✅` | |
| `auto_read_receipt_enabled` | bool | `false` | |
| `db_first_enabled` | bool | `true` | Persist raw messages before processing |
| `enabled_pipelines` | json | see source | Ordered list of active pipeline names |
| `pipeline_settings` | json | see source | Per-pipeline config dict |
| `raw_message_retention_days` | int | `30` | Automatic cleanup window |
| `signal_typing_indicators` | bool | `false` | |
| `signal_link_previews` | bool | `false` | |
| `signal_unidentified_delivery_indicators` | bool | `false` | |
| `regex_patterns` | json | see source | Named regex patterns used by pipelines |
| `report_template` | str | — | Jinja2 template for new reports |
| `append_template` | str | — | Jinja2 template for appended entries |

---

### `responses`
Auto-reply templates triggered by keyword commands (e.g. `#help`, `#ok`).

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `keywords` | TEXT | JSON array of lowercase strings |
| `body` | TEXT | Markdown reply body |

Lookup uses `json_each` for case-insensitive keyword matching.
Seeded with `help`/`hjälp` and `ok` defaults on first migration.

---

### `groups`
Signal group cache — populated from `listGroups` calls, survives restarts.

| Column | Type | Notes |
|--------|------|-------|
| `group_id` | TEXT | Signal group ID (base64) |
| `account` | TEXT | Signal account number |
| `name` | TEXT | Display name |
| `member_count` | INTEGER | Last known member count |
| `is_member` | INTEGER | `1` = still a member |
| `last_seen` | TEXT | ISO-8601 UTC timestamp of last upsert |

Primary key: `(group_id, account)` — supports multi-account setups.

---

### `raw_messages`
*(Added in schema v5 — requires `db_first_enabled = true`)*

Every incoming Signal envelope stored verbatim before pipeline processing.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | `message_id` used by downstream tables |
| `account` | TEXT | Signal account number |
| `timestamp_utc` | TEXT | ISO-8601 UTC from Signal envelope |
| `envelope_raw` | TEXT | Full JSON envelope blob |
| `source_number` | TEXT | Sender's phone number |
| `source_name` | TEXT | Sender's display name |
| `group_id` | TEXT | Signal group ID (nullable for DMs) |
| `group_name` | TEXT | Group display name at time of receipt |
| `message_body` | TEXT | Plain text extracted from `dataMessage` |
| `has_attachments` | INTEGER | `1` if attachments present |
| `status` | TEXT | See lifecycle below |
| `status_timestamp` | TEXT | ISO-8601 UTC of last status change |
| `created_at` | TEXT | ISO-8601 UTC, default `strftime(…,'now')` |

**Status lifecycle:** `received` → `queued` → `processing` → `processed` | `failed` | `ignored`

**Indexes:**
- `idx_raw_messages_account_ts` on `(account, timestamp_utc DESC)`
- `idx_raw_messages_status` on `(status)`

Cleaned up by `retention_db.cleanup_old_data()` based on `raw_message_retention_days`.

---

### `pipeline_runs`
One row per (message, pipeline) execution attempt.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | `run_id` |
| `message_id` | INTEGER FK → `raw_messages.id` | Cascade delete |
| `pipeline_name` | TEXT | e.g. `seven_s`, `group_filter` |
| `status` | TEXT | See lifecycle below |
| `started_at` | TEXT | ISO-8601 UTC |
| `completed_at` | TEXT | ISO-8601 UTC |
| `output_file` | TEXT | Path to generated vault file (if any) |
| `error_code` | TEXT | Short error class on failure |
| `error_message` | TEXT | Human-readable error detail |

**Status lifecycle:** `pending` → `running` → `done` | `failed` | `skipped`

`skipped` means the message did not match this pipeline's filter — not an error.

**Indexes:**
- `idx_pipeline_runs_message_id` on `(message_id)`
- `idx_pipeline_runs_status` on `(pipeline_name, status)`

---

### `pipeline_events`
Structured event log per pipeline run — append-only.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `run_id` | INTEGER FK → `pipeline_runs.id` | Cascade delete |
| `event_type` | TEXT | e.g. `match`, `write`, `error` |
| `occurred_at` | TEXT | ISO-8601 UTC, default `strftime(…,'now')` |
| `details` | TEXT | JSON blob (nullable) |

**Index:** `idx_pipeline_events_run_id` on `(run_id)`

---

## Retention

`retention_db.cleanup_old_data(db_path, retention_days)` runs on a schedule and deletes:

1. `pipeline_events` older than the cutoff (by `occurred_at`)
2. `pipeline_events` whose parent `pipeline_run` belongs to an old `raw_message`
3. `pipeline_runs` whose `raw_message` is older than the cutoff
4. `raw_messages` older than the cutoff (by `created_at`)

`config`, `metadata`, `responses`, and `groups` are never cleaned up by retention.

---

## Source files

| File | Responsibility |
|------|---------------|
| [oden/config_db.py](../oden/config_db.py) | Schema init, migrations, config CRUD |
| [oden/messages_db.py](../oden/messages_db.py) | `raw_messages` CRUD |
| [oden/pipelines_db.py](../oden/pipelines_db.py) | `pipeline_runs` and `pipeline_events` CRUD |
| [oden/groups_db.py](../oden/groups_db.py) | `groups` CRUD |
| [oden/responses_db.py](../oden/responses_db.py) | `responses` CRUD |
| [oden/retention_db.py](../oden/retention_db.py) | Time-based cleanup |
