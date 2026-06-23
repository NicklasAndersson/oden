# Plan: Pipeline-administrationsmeny för Oden 3.0

## Mål

Skapa ett adminsnitt för att:
1. Se vilka pipelines som är aktiva och i vilken ordning
2. Slå av/på individuella pipelines
3. Ändra körordningen (drag-and-drop eller upp/ner-knappar)
4. Visa hur varje pipeline väljer meddelanden
5. (Framtida) Hantera pipeline-instanser med olika inställningar

## Design

### Web-UI — "Pipelines"-flik i Dashboard

Placering: Ny flik i web-gränssnitt mellan "Konfiguration" och "Loggar" (eller som undermeny under Konfiguration).

#### Layout

```
┌─────────────────────────────────────────────────────┐
│ PIPELINES                                           │
├─────────────────────────────────────────────────────┤
│                                                     │
│ Aktiva pipelines (i körordning):                   │
│                                                     │
│ ☑ 1. Seven S RAPPORT-pipeline                      │
│     └─ Väljer: Meddelanden som börjar med         │
│        "7S RAPPORT" (skiftlägesokänsligt)         │
│     └─ Status: 247 processade sedan boot         │
│     [⬆] [⬇] [⚙] [X]                              │
│                                                     │
│ ☑ 2. Generic Template-pipeline                     │
│     └─ Väljer: Alla meddelanden (fallback)        │
│     └─ Status: 4521 processade sedan boot        │
│     [⬆] [X]  [⚙]                                  │
│                                                     │
│ ☐ 3. My Custom Pipeline                            │
│     └─ Väljer: (inaktiv)                           │
│     [⬆] [⬇] [⚙]                                  │
│                                                     │
├─────────────────────────────────────────────────────┤
│ [+ Lägg till pipeline] (future)                     │
└─────────────────────────────────────────────────────┘

Legend:
  [⬆] = Flytta upp i ordning
  [⬇] = Flytta ner i ordning
  [⚙] = Redigera inställningar (if supported)
  [X] = Ta bort från lista (inaktivera)
  ☑ / ☐ = Aktiverad/inaktiverad
```

#### Interaktion

1. **Toggle (☑/☐)**: Klick på checkbox slår på/av pipeline
2. **Ordningsändring**: [⬆]/[⬇]-knappar skickar API-anrop för reorder
3. **Inställningar**: [⚙] öppnar modal med pipeline-specifika inställningar (framtida)
4. **Tar bort från lista**: [X] inaktiverar pipeline (samma som toggle off)

#### Responsiv design

Mobile: Stackad lista utan upp/ner-knappar, drag-handle (⋮⋮) för reorder.

---

## Backend-API

### GET `/api/pipelines`

Hämta lista över alla tillgängliga och aktiva pipelines.

**Response:**
```json
{
  "available": [
    {
      "name": "seven_s",
      "display_name": "Seven S RAPPORT-pipeline",
      "description": "Parsar och lagrar strukturerade 7S-rapporter",
      "selection_criteria": "Meddelanden som börjar med '7S RAPPORT'",
      "supports_config": false,
      "config_schema": null
    },
    {
      "name": "generic_template",
      "display_name": "Generic Template-pipeline",
      "description": "Fallback-pipeline för resterande meddelanden. Använder Jinja2-mallar.",
      "selection_criteria": "Alla meddelanden (fallback)",
      "supports_config": true,
      "config_schema": {
        "vault_path_override": "string",
        "ignored_groups": "array",
        "whitelist_groups": "array",
        "append_window_minutes": "integer"
      }
    }
  ],
  "enabled": [
    {
      "order": 1,
      "name": "seven_s",
      "enabled": true,
      "config": {}
    },
    {
      "order": 2,
      "name": "generic_template",
      "enabled": true,
      "config": {}
    }
  ],
  "stats": {
    "total_processed": 4768,
    "by_pipeline": {
      "seven_s": 247,
      "generic_template": 4521
    }
  }
}
```

### PATCH `/api/pipelines/{name}/enabled`

Aktivera eller inaktivera en pipeline.

**Request:**
```json
{
  "enabled": true
}
```

**Response:**
```json
{
  "success": true,
  "updated_list": ["seven_s", "generic_template"]
}
```

### POST `/api/pipelines/reorder`

Ändra körordningen för pipelines.

**Request:**
```json
{
  "order": ["generic_template", "seven_s"]
}
```

**Response:**
```json
{
  "success": true,
  "updated_list": ["generic_template", "seven_s"]
}
```

### GET `/api/pipelines/{name}/stats`

Hämta statistik för en pipeline (optional, kan byggas senare).

**Response:**
```json
{
  "name": "seven_s",
  "total_runs": 247,
  "succeeded": 245,
  "failed": 2,
  "skipped": 0,
  "avg_duration_ms": 45
}
```

---

## Implementation Steps

### Fas 1: Backend-infrastruktur

- [ ] **1.1** Skapa `oden/web_handlers/pipeline_handlers.py`
  - Implementera endpoints: `/api/pipelines`, `/api/pipelines/{name}/enabled`, `/api/pipelines/reorder`
  - Hämta pipeline-info från `PipelineOrchestrator`
  - Uppdatera `enabled_pipelines` i config_db

- [ ] **1.2** Uppdatera `oden/pipeline_orchestrator.py`
  - Exponera `get_pipeline_info()` för att hämta metadata
  - Exponera `get_pipeline_stats()` för statistik (börja enkelt)

- [ ] **1.3** Uppdatera `oden/config_db.py`
  - Lägga till pipeline-metadata i DEFAULT_CONFIG eller separat tabell

- [ ] **1.4** Integrera routes i `oden/web_server.py`
  - Registrera `/api/pipelines` och subpaths

### Fas 2: Frontend-UI

- [ ] **2.1** Skapa flik i dashboard HTML
  - `oden/templates/web/pipelines.html`
  - Listan av aktiva pipelines
  - Upp/ner-knappar, toggle, info-text

- [ ] **2.2** JavaScript för interaktion
  - `oden/templates/web/js/pipelines.js`
  - Hämta från `/api/pipelines`
  - Klick-hanterare för toggle, reorder
  - Auto-refresh av stats

- [ ] **2.3** CSS för UI
  - Styling av pipeline-kort, knappar, responsive layout

### Fas 3: Testing

- [ ] **3.1** Testfil `tests/test_pipeline_handlers.py`
  - Testa GET `/api/pipelines`
  - Testa PATCH för enable/disable
  - Testa reorder validation

- [ ] **3.2** Integrationtest
  - Verifiera att ändringar sparas i config_db
  - Verifiera att PipelineOrchestrator respekterar ny ordning

### Fas 4: Documentation

- [ ] **4.1** Uppdatera [`docs/PIPELINES.md`](PIPELINES.md)
  - Lägga till API-endpoints

- [ ] **4.2** Uppdatera [`docs/WEB_GUI.md`](WEB_GUI.md)
  - Dokumentera "Pipelines"-fliken

---

## Data-lagring

Inga nya databastabeller krävs för v1. Vi använder befintlig `config`-tabell:

```sql
-- Sparad i config-tabellen
{
  "key": "enabled_pipelines",
  "value": "["seven_s", "generic_template"]",
  "type": "json"
}
```

**Framtida (v3.1+):** Ny tabell `pipeline_instances` för instans-konfigurationer:

```sql
CREATE TABLE pipeline_instances (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  enabled BOOLEAN DEFAULT true,
  order INTEGER NOT NULL,
  config JSON,
  created_at TEXT,
  updated_at TEXT
)
```

---

## Pipeline-metadata

Varje pipeline exponerar:
- `name` — Konfigurationsnamn (t.ex. `"seven_s"`)
- `display_name` — Användarvisningsnamn (t.ex. "Seven S RAPPORT-pipeline")
- `description` — Kort beskrivning av vad pipelinen gör
- `selection_criteria` — Hur pipelinen väljer meddelanden
- `supports_config` — Kan pipelinen konfigureras (bool)
- `config_schema` — JSON-schema för konfigurerbara fält (om applicable)

**Implementering:**
```python
# I varje pipeline-klass
class SevenSPipeline:
    name = "seven_s"
    display_name = "Seven S RAPPORT-pipeline"
    description = "Parsar och lagrar strukturerade 7S-rapporter"
    selection_criteria = "Meddelanden som börjar med '7S RAPPORT'"
    supports_config = False
    config_schema = None
```

eller via registrering i `PipelineOrchestrator`:

```python
PIPELINE_REGISTRY = {
    "seven_s": {
        "class": SevenSPipeline,
        "display_name": "Seven S RAPPORT-pipeline",
        # ...
    },
    # ...
}
```

---

## Framtida: Pipeline-instanser (v3.1+)

Den nuvarande designen är en-pipeline-per-typ. För att stödja instanser:

1. Byta från `enabled_pipelines` (lista av strängnamn) till `pipeline_instances` (tabell)
2. Uppdatera `PipelineOrchestrator` för att ladda från instans-tabell
3. Exponera instanser i web-gränssnitt
4. Lägga till modal för instans-konfigurering

Denna plan är skissad men inte prioriterad för v3.0.

---

## Acceptance Criteria

- [ ] Pipeline-meny visas korrekt i web-gränssnitt
- [ ] Toggle på/av uppdaterar config_db och påverkar nästa ingest
- [ ] Reorder-knappar ändrar körordning omedelbar
- [ ] Stats visar antal processade meddelanden per pipeline
- [ ] Alla ändringar är persistenta över restart
- [ ] Tests täcker >85% av pipeline_handlers.py
- [ ] Dokumentation är uppdaterad och korrekt

---

## Beroenden

- Fas 3.0 måste vara avslutad (pipelines ska redan existera)
- Web-server måste redan köra (redan implementerat)
- config_db-system måste vara etablerat (redan implementerat)

---

## Tidsestimering

| Fas | Aktivitet | Est. timmar |
|-----|-----------|-------------|
| 1 | Backend-API | 4 |
| 2 | Frontend-UI | 6 |
| 3 | Testing | 3 |
| 4 | Dokumentation | 1 |
| — | Buffer (debugging, etc.) | 2 |
| **Total** | | **16** |

*Estimation är ungefärlig och kan variera baserat på komplexitet.*

---

## Öppen fråga: Konfiguration per instans

Om vi vill stödja samma pipeline flera gånger med olika inställningar (t.ex. två `generic_template` med olika vault-sökvägar), behöver vi:

1. **Schema-ändring:** `enabled_pipelines` från lista av strängnamn till lista av objekt
2. **Orchestrator-update:** Ladda config från instans-objekt istället för globala config-variabler
3. **UI-update:** Visa inställningsikon per instans, öppna modal för konfigurering

Denna komplexitet skjuts upp till v3.1 om behov uppstår.

Se även [`docs/PIPELINES.md`](PIPELINES.md#framtida-pipeline-instanser-med-inställningar).
