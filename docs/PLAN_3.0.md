# Oden 3.0 — Plan: DB-first multipipeline med 7S-stöd

> **Status:** Planering
>
> **Mål:** Ombygg Oden till en DB-first ingest-arkitektur med stöd för
> flera parallella pipelines. Varje inkommande Signal-meddelande sparas
> rått i SQLite innan det processas. Nuvarande template-flöde blir generisk
> pipeline. En specialpipeline för 7S-rapport-formatet (HvSS-Innovation/7s-rapport)
> implementeras som första specialfall. Web-GUI byggs ut med full insyn
> i meddelandehistorik, pipeline-status och reprocessning.

## Bakgrund

Oden tar idag emot Signal-meddelanden och processerar dem direkt till
Markdown i Obsidian-vaulten via ett enda sekventiellt flöde
(`signal_listener.py` → `process_message()` → filskrivning). Det finns
inget sätt att:

- Spara råa meddelanden för revision eller reprocessning.
- Köra olika logik för olika meddelandeformat (7S vs generiskt).
- Se i ett GUI vad som tagits emot, hur det processats och varför något
  ignorerades eller misslyckades.

## 7S-format (HvSS-Innovation/7s-rapport)

Meddelanden med 7S-format identifieras och hanteras av en specialpipeline:

```
7S RAPPORT
Till: TILL_NAMN
Från: FRÅN_NAMN
TNR: 220932
Stund: 220930
Ställe: 33VXF 56007 96107, Strandvägen, Kungsängen
Styrka: 2
Slag: Personbil
Sysselsättning: Spanar
Symbol: Svart
Sagesman: 2A GRUPP
Sedan: Fortsätter spaning
```

Övriga meddelanden fortsätter i det befintliga generiska template-flödet.

## Arkitektur (3.0)

```
Signal-meddelande (TCP JSON-RPC)
       ↓
signal_listener.py  →  raw_messages-tabell (DB) ← persist-first
       ↓
PipelineOrchestrator
  ├─ SevenSPipeline           (matchar 7S RAPPORT-format, kör om matchat)
  └─ GenericTemplatePipeline  (nuvarande beteende, fallback för övriga)
       ↓
pipeline_runs-tabell (status, output, events per körning)
       ↓
Web GUI — "Meddelandehantering"-tab
  ├─ Lista råmeddelanden med status och pipeline
  ├─ Detaljvy (rå envelope, pipeline-spår, output-fil)
  └─ Reprocess-knapp
```

## Faser och steg

### Fas 1 — DB-lager *(blockerar allt nedan)*

- [x] **1a. Kontrakt och statusmodell**
  Definiera gemensam meddelandemodell och statuslivscykeln:
  - Meddelande: `received → queued → processing → processed | failed | ignored`
  - Pipeline-run: `pending → running → done | failed | skipped`

- [x] **1b. DB-migration (config_db.py)**
  Utöka schemaversion till 5 med tre nya tabeller:
  - `raw_messages` — en rad per inkommande Signal-envelope, med JSON-blob
    och extraherade sökbara fält (account, timestamp_utc, source_number,
    source_name, group_id, group_name, message_body, has_attachments, status,
    status_timestamp).
  - `pipeline_runs` — en rad per pipeline-körning per meddelande
    (message_id, pipeline_name, status, started_at, completed_at,
    output_file, error_code, error_message).
  - `pipeline_events` — detaljlogg per pipeline-körning (run_id,
    event_type, occurred_at, details JSON).

- [x] **1c. Datalager**
  Nya moduler `oden/messages_db.py` och `oden/pipelines_db.py` med API:
  `create_raw_message`, `update_message_status`, `list_messages`,
  `get_message_detail`, `start_pipeline_run`, `complete_pipeline_run`,
  `fail_pipeline_run`, `append_pipeline_event`.

### Fas 2 — Ingest och orkestrering *(beror på Fas 1)*

- [x] **2a. Persist-first i signal_listener.py**
  Ändra `subscribe_and_listen()` så att rå payload skrivs till
  `raw_messages` *innan* orkestraren anropas. Om DB-skrivning misslyckas
  loggas felet men ingest stoppas inte.

- [x] **2b. PipelineOrchestrator (pipeline_orchestrator.py)**
  Ny klass som laddar aktiva pipelines, kör dem i ordning per message_id,
  skriver run-status och events till DB, och exponerar
  `reprocess(message_id)` för GUI.

- [x] **2c. GenericTemplatePipeline (oden/pipelines/generic_template.py)**
  Extrahera befintlig logik från `process_message()` till en pipeline-klass.
  Bevarar all semantik: append-regler, command-svar, attachment-hantering,
  template-rendering, filskrivning. `processing.py` anropas av pipeline-klassen.

### Fas 3 — 7S-specialpipeline *(beror på Fas 2)*

- [x] **3a. SevenSPipeline (oden/pipelines/seven_s.py)**
  - Robust matchning av 7S RAPPORT-format (case-insensitive, tolererar
    varianter i fältnamn och radordning).
  - Parserar och validerar alla fält; strukturerat fel-objekt för partiellt
    giltiga rapporter.
  - Skriver till vault med egen 7S-template.
  - Returnerar `skipped` om meddelandet inte matchar → generisk pipeline
    tar vid utan ytterligare config.

- [x] **3b. Routing-regler och config**
  - `GenericTemplatePipeline` alltid aktiv som fallback.
  - `SevenSPipeline` aktiv per default, kan stängas av via config-nyckel
    `enabled_pipelines` (JSON-lista).

### Fas 4 — GUI/API för observability *(kan börjas parallellt med Fas 3)*

- [x] **4a. Backend-API (oden/web_handlers/message_handlers.py)**
  Nya endpoints registrerade i `web_server.py`:
  - `GET /api/messages` — lista med filter (status, pipeline, group,
    account, tid) och paginering.
  - `GET /api/messages/{id}` — detalj inkl rå envelope och pipeline-runs.
  - `POST /api/messages/{id}/reprocess` — kör om via orkestraren.
  - `GET /api/messages/stats` — aggregat per period/grupp/pipeline.

- [x] **4b. GUI-tab "Meddelandehantering"**
  Ny tab i dashboarden (`dashboard.html`):
  - Vänster panel: kronologisk meddelandelista med statusbadge, grupp,
    avsändare, flaggor (7S, IGNORED, APPEND, ERROR).
  - Höger panel (vid klick): rå JSON-envelope, pipeline-spår med steg och
    utfall, output-fil-länk och reprocess-knapp.
  - Sidopanel: räknare (totalt/processat/ignorerat/misslyckat) och
    filterkontroller.

- [x] **4c. Frontend**
  Ny JS-modul `js/dashboard/message_queue.js` — polling var 3:e sekund
  när tab är aktiv, filter-dropdowns, detaljvy med raw JSON och pipeline-trace.
  CSS-tillägg i `dashboard.css`.

### Fas 5 — Bakåtkompatibilitet och drift *(kan köras parallellt med Fas 4)*

- [x] **5a. Feature-flag**
  Config-nyckel `db_first_enabled` (bool, default `true`). Om `false` körs
  gammalt flöde direkt utan DB-persistering.

- [x] **5b. Retention-policy**
  Schemalagd cleanup av `raw_messages` och `pipeline_events` äldre än
  konfigurerbart antal dagar (default 30). Exponeras i GUI under Avancerat.

- [ ] **5c. Testutökning**
  - Migration-test: uppgradering v4 → v5 utan dataförlust.
  - Ingest-test: payload alltid sparad även om pipeline kraschar.
  - Regressions-test: generisk pipeline producerar identiskt utfall som idag.
  - 7S-parser-test: valid/partiell/ogiltig rapport, alla fältvarianter.
  - Reprocess-test: idempotens vid upprepad körning.
  - API-test: list/detalj/filter/stats/reprocess-endpoints.

- [ ] **5d. Dokumentationsuppdatering**
  Uppdatera all dokumentation så att den matchar nya implementationen i 3.0:
  - `README.md` (DB-first, multipipeline, 7S-stöd, Meddelandehantering, retention)
  - `docs/FEATURES.md` och `docs/WEB_GUI.md` (nya funktioner och GUI-flöden)
  - `docs/SETUP_FLOW.md` / övriga relevanta docs där konfigurationsnycklar ändrats
  - driftnoteringar för `db_first_enabled`, `enabled_pipelines`, `raw_message_retention_days`

## Filer att skapa/ändra

| Fil | Förändring |
|-----|-----------|
| `oden/config_db.py` | Schema v5-migration, tre nya tabeller |
| `oden/messages_db.py` | **Ny** — CRUD och status för råmeddelanden |
| `oden/pipelines_db.py` | **Ny** — CRUD för pipeline-runs och events |
| `oden/pipeline_orchestrator.py` | **Ny** — orkestrering, registry, retry/reprocess |
| `oden/pipelines/__init__.py` | **Ny** — base pipeline-protokoll (ABC) |
| `oden/pipelines/generic_template.py` | **Ny** — extraherad logik från processing.py |
| `oden/pipelines/seven_s.py` | **Ny** — 7S RAPPORT-parser och pipeline |
| `oden/signal_listener.py` | Persist-first, anrop till orchestrator |
| `oden/processing.py` | Behålls; anropas av GenericTemplatePipeline |
| `oden/web_server.py` | Registrera nya message-endpoints |
| `oden/web_handlers/message_handlers.py` | **Ny** — list/detail/stats/reprocess |
| `oden/templates/web/dashboard.html` | Ny tab Meddelandehantering |
| `oden/templates/web/js/dashboard/message_queue.js` | **Ny** — frontend |
| `oden/templates/web/css/dashboard.css` | Tillägg för ny vy |
| `templates/seven_s.md.j2` | **Ny** — 7S-rapport template |
| `tests/test_pipeline_orchestrator.py` | **Ny** |
| `tests/test_seven_s_pipeline.py` | **Ny** |

## Kända risker och öppna frågor

- **Append + reprocess**: Reprocessning av ett append-meddelande kan skriva
  dubbelt. Kräver idempotens-check eller att reprocess blockeras för
  append-typer tills lösning designats.
- **Retention och storlek**: Raw JSON-envelopes ackumuleras. Attachments
  sparas på disk (inte i DB), men envelope-metadata kan bli stor över tid.
  Retention-policy (Fas 5b) måste implementeras tidigt om produktionsdata
  är hög volym.
- **7S-fältordning**: Formatet specificerar ingen garanterad fältordning.
  Parsern måste vara ordningsoberoende.

## Uteslutna i 3.0

- WebSocket-streaming i realtid (framtida förbättring)
- Extern köinfrastruktur (Redis, RabbitMQ etc.)
- Fler specialpipelines än 7S

## Progress-logg

| Datum | Vem | Notering |
|-------|-----|---------|
| 2026-06-22 | — | Plan skapad. Fas 1–5 definierade. |
| 2026-06-22 | — | Fas 1 klar. Schema v5-migration, messages_db.py, pipelines_db.py. 240/240 tester gröna. |
| 2026-06-22 | — | Fas 2a + 2b klar. Persist-first i listener, ny PipelineOrchestrator, pipeline_runs/events skrivs. Hittat/löst: inkommande payload kan vara wrapper med envelope; messages_db normaliserar nu för metadata men sparar hela råobjektet i envelope_raw. Fallback kvar: om DB-persist misslyckas körs befintlig process_message ändå. 240/240 tester gröna. |
| 2026-06-22 | — | Fas 2c klar. Ny pipeline-package med GenericTemplatePipeline och orchestratorn kör nu pipeline-klassen istället för direktanrop. Hittat/löst: importordning i pipeline_orchestrator.py (ruff I001) och autoformatterad fil. 240/240 tester gröna. |
| 2026-06-22 | — | Fas 3a + 3b klar. Ny SevenSPipeline med robust 7S-parser och filskrivning, samt routing via config-nyckeln enabled_pipelines (default: seven_s, generic_template). Orchestratorn kör nu multipipeline i ordning och markerar skipped/completed/failed per run. Hittat/löst: ruff SIM108 i pipeline_orchestrator.py. 246/246 tester gröna (inkl nya 7S-tester). |
| 2026-06-22 | — | Fas 4a klar. Ny backendmodul message_handlers.py med endpoints för list/detalj/stats/reprocess (`/api/messages*`), kopplad i web_server och web_handlers-export. 246/246 tester gröna. |
| 2026-06-22 | — | Fas 4b + 4c klar. Ny Meddelandehantering-tab i dashboard med listvy, detaljvy, statusbadges, stats och reprocess-knapp. Polling när tabben är aktiv samt filter på status. 246/246 tester gröna. |
| 2026-06-22 | — | Fas 5 (delsteg) påbörjad: feature-flag `db_first_enabled` tillagd i config_db/config, exponerad i config-API och kopplad i signal_listener som säker fallback till legacy-flödet. 246/246 tester gröna. |
| 2026-06-22 | — | CI-fix: PR snapshot-pipeline föll i docker arm64-bygget. Rotorsak var ogiltig Python one-liner i Dockerfile (compound `with` efter semikolon). Fixad till kompatibel rad-för-rad-variant i ARM64-injektionssteget för `libsignal_jni.so`. |
| 2026-06-22 | — | Fas 5b klar. Retention-policy implementerad med ny config-nyckel `raw_message_retention_days` (default 30), cleanup-logik i `retention_db.py`, periodisk körning i listener och ny inställning i Avancerat-fliken i GUI. |
| 2026-06-22 | — | Fas 5c delvis utökad. Nya tester för retention-cleanup och web-config validering av `raw_message_retention_days`. Full testsvit: 251/251 gröna. |
| 2026-06-22 | — | Plan uppdaterad med Fas 5d: explicit dokumentationsspår för att synka README och docs med DB-first/multipipeline/7S/retention-implementationen. |
