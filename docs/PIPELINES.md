# Pipelines i Oden 3.0

## Översikt

**Pipelines** är moduler som processar inkommande meddelanden efter att de sparats i SQLite. Varje pipeline kan välja att hantera ett meddelande (returera `True`) eller hoppa det (`False`) så nästa pipeline i kön får en chans.

### Flöde
```
Inkommande meddelande
         │
         ▼
[Spara i raw_messages]
         │
         ▼
[PipelineOrchestrator]
         │
    ┌────┴────┬─────────┬─────────┐
    │ 7S      │ Generic │ Framtida│
    │ RAPPORT │ Template│ Pipeline│
    ▼         ▼         ▼         ▼
 [Hanterat?] [Hanterat?] [...]   
    │         │
    └─────────┘
```

## Konfiguration

Pipelines aktiveras/deaktiveras via config-nyckeln `enabled_pipelines` (JSON-lista):

```json
{
  "enabled_pipelines": ["seven_s", "generic_template"]
}
```

**Ordning är viktig:** Pipelines körs i den ordning de anges. Primera pipeline som hanterar meddelandet stoppar kedjan.

Nuvarande default:
- `seven_s` — kör först och söker 7S RAPPORT:er
- `generic_template` — fallback; hanterar resterande meddelanden

## Befintliga Pipelines

### 7S RAPPORT-pipeline (`seven_s`)

**Vad den väljer:** Meddelanden som börjar med `7S RAPPORT` (skiftlägesokänsligt).

**Förväntad indata:** 7S-rapporter skapas av `HvSS-Innovation/7s-rapport` och kopieras därefter in i Signal. Pipelinen är därför optimerad för ett kanoniskt, verktygsgenererat 7S-format.

**Vad den gör:**
- Parsar strukturerad 7S-rapport (Till, Från, TNR, Stund, Ställe, Styrka, Slag, Sysselsättning, Symbol, Sagesman, Sedan)
- Validerar alla obligatoriska fält samt att `TNR` och `Stund` båda följer formatet `DDHHMM`
- Tolkar `Stund` som observationstid och bevarar `TNR` som rapportens eget tidsnummer, även när de skiljer sig
- Loggar en varning om `Sagesman` avviker från den kanoniska plutonsnivån (`AQ`-`EQ`), men skriver rapporten ändå
- Sparar sådana avvikelser som `pipeline_warning` i meddelandets pipeline-events så att de syns i observability-vyn
- Skriver strukturerad markdown-fil till `vault/{group_name}/TNR<DDHHMM>[_n].md`, där filnamnet följer rapportens `TNR`
- Genererar schemaformad YAML-frontmatter enligt [FORMAT_SPEC.md](FORMAT_SPEC.md) och [7S_frontmatter.schema.json](7S_frontmatter.schema.json)
- Konverterar MGRS i `Ställe` till `lat`, `lon` och `location` när koordinater kan härledas
- Länkar särskiljande kännetecken i `Symbol` med `[[...]]` enligt specen

**Exempel på inmatning:**
```
7S RAPPORT
Till: TST
Från: TS
TNR: 221520
Stund: 221520
Ställe: 34VCM 79349 26095, Långkärrsvägen
Styrka: 1
Slag: Vi
Sysselsättning: Patrull
Symbol: ABC123 och logotyp-fragment DGE
Sagesman: AQ
Sedan: Återgår till bas
```

**Output-struktur:**
```
---
id: 7S-...
typ: 7S-rapport
tnr: "221520"
tidpunkt: "2026-06-22T15:20:00"
plats: "Långkärrsvägen"
lat: 59.49063
lon: 17.46740
location: "59.49063,17.46740"
sagesman: AQ
---

**TNR:** 221520

**Stund:** 2026-06-22 15:20

**Ställe:** Långkärrsvägen

**Styrka:** 1

**Slag:** Vi

**Sysselsättning:** Patrull

**Symbol:** [[ABC123]] och [[logotyp-fragment DGE]]

**Sagesman:** AQ
```

Full normativ specifikation finns i [FORMAT_SPEC.md](FORMAT_SPEC.md).

**Status i DB:** Om meddelande är en 7S RAPPORT markeras det som *processed* efter första körningen.

---

### Generic Template-pipeline (`generic_template`)

**Vad den väljer:** *Alla* meddelanden som inte redan hanterats.

**Vad den gör:**
- Använder legacy-logik från Oden 2.x (`process_message`)
- Stöder Jinja2-mallar för rapportgenerering
- Hanterar append-läge (`++`-prefix eller svar inom 30 min)
- Är övergripande fallback för att ingen meddelande-data går förlorad

**Meddelandeflöde:**
1. Kontrollera ignorerade grupper
2. Generera rapport från Jinja2-mall
3. Hämta bilagor (om aktiverat)
4. Skriva markdown-fil til vault

**Inställningar som påverkar:**
- `vault_path` — mappsökväg för markdown-filer
- `ignored_groups` — grupper att hoppa
- `whitelist_groups` — whitelist-begränsning
- `append_window_minutes` — tidsfönster för append-läge
- `report_template` / `append_template` — Jinja2-mallar

---

## Administrering

### I Web-gränssnitt (kommande)

En ny flik **"Pipelines"** visar:
- Aktiverade pipelines i körordning
- Knapp för att ändra ordning (drag-and-drop)
- Toggle för att slå av/på individuella pipelines
- Inställningsikon för pipelines med konfiguration

### I config.db

```sql
-- Visa aktiva pipelines
SELECT value FROM config WHERE key = 'enabled_pipelines';
-- Resultat: ["seven_s", "generic_template"]

-- Ändra ordning eller aktivering
UPDATE config 
SET value = '["generic_template"]' 
WHERE key = 'enabled_pipelines';
```

---

## Framtida: Pipeline-instanser med inställningar

*Planerat för Oden 3.1+*

För närvarande är pipelines globala — en pipeline körs med samma inställningar för alla meddelanden. Vi vill kunna:

1. **Skapa flera instanser av samma pipeline** med olika inställningar
2. **Exempel:** Två `generic_template`-instanser:
   - Instans A: Sparar 7S-liknande rapporter i `/vault/7s-style/`
   - Instans B: Sparar allt övrigt i `/vault/other/`

**Arkitekturändring:**
```json
{
  "pipeline_instances": [
    {
      "id": "seven_s_main",
      "type": "seven_s",
      "enabled": true,
      "order": 1,
      "config": {}
    },
    {
      "id": "generic_7s_style",
      "type": "generic_template",
      "enabled": true,
      "order": 2,
      "config": {
        "vault_path_override": "/vault/7s-style/",
        "filename_format": "7s_style"
      }
    },
    {
      "id": "generic_fallback",
      "type": "generic_template",
      "enabled": true,
      "order": 3,
      "config": {
        "vault_path_override": "/vault/other/",
        "ignored_groups": ["admin"]
      }
    }
  ]
}
```

**Fördelar:**
- Granulär kontroll över meddelandeflöde
- Möjlighet att skapa flera rapportlayouter baserat på samma data
- Möjlighet att implementera nya specialiserade pipelines senare

---

## Utveckling av nya Pipelines

En ny pipeline måste:

1. Implementera `MessagePipeline`-protokollet i `oden/pipelines/` 🡻

```python
from typing import Any
import asyncio

class MyCustomPipeline:
    """Describe pipeline purpose."""
    
    name = "my_custom"  # Unique identifier for config
    
    async def run(
        self,
        *,
        msg_data: dict[str, Any],
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        """Process one message.
        
        Returns True if handled, False to pass to next pipeline.
        """
        # msg_data innehåller rå signal-cli-envelope och metadata
        
        # Välj om denna pipeline ska hantera meddelandet
        if not self._should_handle(msg_data):
            return False
        
        # Gör något (skriva fil, API-anrop, etc.)
        await self._do_work(msg_data)
        
        return True  # Meddelandet hanterat
    
    def _should_handle(self, msg_data: dict[str, Any]) -> bool:
        # Din logik här
        pass
    
    async def _do_work(self, msg_data: dict[str, Any]) -> None:
        # Din logik här
        pass
```

2. Registrera i `PipelineOrchestrator._build_pipelines()` 🡻

```python
# oden/pipeline_orchestrator.py
pipeline_map = {
    "seven_s": self._seven_s_pipeline,
    "generic_template": self._generic_pipeline,
    "my_custom": self._my_custom_pipeline,  # NEW
}
```

3. Exponera instans i `__init__` 🡻

```python
def __init__(self, db_path: Path) -> None:
    # ...
    self._my_custom_pipeline = MyCustomPipeline()
```

4. Uppdatera config-schema för möjliga instansvärden (framtidigt steg när pipeline-instanshantering implementeras)

---

## Test-coverage

Se `tests/test_*_pipeline.py` för examples:
- `test_seven_s_pipeline.py` — enhetstester för 7S-parser
- `test_processing.py` — integrationstester för generic_template

Pipelines förväntas:
- Hantera felaktig inmatning utan att krascha
- Logga meningsfulla fel
- Uppdatera DB-status för pipeline_runs

---

## API-endpoints (v3.0)

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/pipelines` | Lista tillgängliga pipelines, aktiva pipelines och körningsstatistik |
| POST | `/api/pipelines/reorder` | Ändra exekveringsordning |
| PATCH | `/api/pipelines/{name}/enabled` | Aktivera/deaktivera pipeline |

---

## Se även

- [`docs/FEATURES.md`](FEATURES.md#meddelandeflöde) — Arkitektur-överblick
- [`docs/PLAN_3.0.md`](PLAN_3.0.md) — Implementeringsplan för Oden 3.0
- `oden/pipeline_orchestrator.py` — Orkestrering-logik
- `oden/pipelines/` — Pipeline-implementationer
