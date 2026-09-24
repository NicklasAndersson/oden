# Pipelines i Oden 3.0

## Översikt

**Pipelines** är moduler som processar inkommande meddelanden efter att de sparats i SQLite. Varje pipeline kan välja att hantera ett meddelande (returera `True`) eller hoppa det (`False`) så nästa pipeline i kön får en chans.

### Vägval och grenar

Först väljs en **gren** utifrån meddelandets källa, sedan körs grenens steg
uppifrån och ner. Första steg som hanterar meddelandet stoppar kedjan.

```
Inkommande meddelande
         │
         ▼
[Spara i raw_messages]
         │
         ▼
[Vägval]  källa → gren   (sparas som körningen "router", syns i Flöde)
   │
   ├─▶ Spaning:   7S → SCRIM → Reserv
   ├─▶ Underhåll: FORS → PEDARS → Reserv
   ├─▶ Ignorera:  inga steg (status ignored, inget skrivs)
   └─▶ Standardgren: allt som inte tilldelats
```

- **Källor:** `source:tak` (allt från TAK-lyssnaren), `group_id:<id>`,
  `group:<namn>` och `source:direct` (direktmeddelanden), i den ordningen. En
  källa hör till exakt en gren; det som inte tilldelats går till standardgrenen.
- **Ignorera-gren:** `ignore: true`, inga steg. Meddelandet sparas och syns i
  Flöde med skälet, men skrivs aldrig till valvet.
- **Reserven** (`generic_template`) ligger alltid sist i en vanlig gren.
- **TAK-publicering** (`tak_publish`) läggs först i varje vanlig gren när
  publicering är påslagen i TAK-fliken.
- **Inställningar per steg:** ett stegs `config` gäller bara i den grenen och
  lägger sig över pipelinens grundinställningar, t.ex. `vault_subdir`. Pipelines
  läser dem med `routing.step_settings(name, cfg.PIPELINE_SETTINGS)`.

## Konfiguration

Grenarna ligger i config-nyckeln `routing` (JSON):

```json
{
  "version": 1,
  "branches": [
    {"id": "spaning", "name": "Spaning", "ignore": false, "steps": [
      {"pipeline": "seven_s", "enabled": true, "config": {"vault_subdir": "Spaning/7S", "vault_subdir_enabled": true}},
      {"pipeline": "generic_template", "enabled": true, "config": {}}
    ]},
    {"id": "ignore", "name": "Ignorera", "ignore": true, "steps": []}
  ],
  "assign": {"group:Kaffe & logistik": "ignore", "source:tak": "spaning"},
  "default": "spaning"
}
```

Den redigeras i fliken **Pipelines** eller via `GET`/`PUT /api/routing`, som
validerar (okända pipelines tas bort, reserven läggs sist, referenser till
grenar som inte finns avvisas).

### Migrering från den gamla kedjan

Före grenarna fanns en enda kedja (`enabled_pipelines`) med `group_filter` som
första steg. Vid första start efter uppgradering skapas `routing` med samma
utfall (`config._migrate_routing`, `routing.derive_from_legacy`):

| Förut | Blir |
|---|---|
| Svartlista med grupper | *Huvudgren* med den gamla kedjan (standard) + *Ignorera* med de listade grupperna |
| Vitlista med grupper | *Huvudgren* med de listade grupperna och direktmeddelanden + *Ignorera* som standard |
| Inget filter | *Huvudgren* för allt (och en tom *Ignorera*) |

`enabled_pipelines` och gruppfiltrets inställningar lämnas orörda (för en
nedgradering) men styr inte längre något. Gruppfiltret är inte längre ett steg.

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
- Konverterar MGRS i `Ställe` till `lat`, `lon` och `location` när koordinater kan härledas — `Ställe: <MGRS>, <plats>` eller bara `Ställe: <MGRS>`. Mellanslag/tabbar och gemener i MGRS spelar ingen roll (`34VCM7934926095`, `34V CM 79349 26095`, `34vcm 79349 26095` tolkas lika)
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

### TAK → text (`tak_text`)

**Vad den väljer:** meddelanden från TAK. Signal-meddelanden går vidare orörda
(”Inte från TAK”).

**Vad den gör:** gör om den sparade CoT:en (`_cot_xml`) till den text stegen
efter läser: 8S → `7S RAPPORT`, SCRIM → `SCRIM RAPPORT`, allt annat en
`TAK-OBSERVATION`. Steget skriver inget självt; stegen efter får den nya texten.
I Flöde syns steget som *Omvandlad* med skälet. Står alltid först i grenen
(före TAK-publiceringen).

**Inställningar per gren** (stegets `config`):
- `reshape_8s` (standard på) och `reshape_scrim` (standard på) — av: formuläret
  blir en observation i stället
- `unknown_forms`: `observation` (standard) eller `form_header` — ett
  ATAK-formulär som Oden inte har en egen tolkning för blir text med
  formulärets namn som första rad (t.ex. `8-Line Spot Report`), följt av
  fälten som `namn: värde` (namnen ATAK skickade), `Position` (MGRS),
  `Koordinater`, `Källa`, `Tid`, `Typ`, `UID` och `Anmärkning`. Ett
  rapportformat med den rubriken ger formuläret en egen anteckningstyp utan kod
- `other`: `observation` (standard) eller `skip` — allt annat från TAK
  (markörer, och formulär som inte tagits ovan) skrivs då inte, utan sparas
  bara i Flöde (status `ignored`)
- `raw_block` (standard på) — formuläret oförändrat i ett dolt `%%`-block

Med standardinställningarna blir texten exakt den som gjordes vid mottagningen,
så steget ändrar inget för befintliga flöden; det gör omvandlingen synlig och
inställbar. Meddelanden som togs emot innan rå CoT sparades går vidare med sin
text (”Ingen rå CoT sparad”). Vid uppgradering läggs steget en gång in först i
grenen som TAK går till (`routing.add_pre_step`, `routing.version` 2); tar man
bort det kommer det inte tillbaka.

### TAK-publicering (`tak_publish`)

**Avstängd som standard.** Oden samlar in och skriver filer för analys; att
skriva tillbaka till TAK är ett aktivt val. Slå på **Publicera 7S-rapporter från
Signal som markörer i TAK** i TAK-fliken (`publish_reports` i `tak_settings`).

**Vad den väljer:** Ingenting — den *konsumerar* aldrig ett meddelande. Körs
först när TAK-bryggan är ansluten *och* `publish_reports` är på, som en
sidoeffekt, och låter sedan resten av kedjan köra som vanligt.

**Vad den gör:**
- Parsar 7S-rapporter och plockar ut MGRS → lat/lon
- Skickar en CoT-markör till TAK-servern (stabil UID per TNR, så en `++`-påfylld
  rapport uppdaterar markören i stället för att dubblera den)
- Hoppar över meddelanden från TAK (`_source = tak`) för att undvika eko-loop
- FORS/PEDARS saknar position → ingen markör

**Inställningar:** fliken **TAK** i web-GUI, eller `tak_settings` i config.db.
Se [TAK_SETUP.md](TAK_SETUP.md) och [PLAN_TAK.md](PLAN_TAK.md).

**Ingår inte** i `enabled_pipelines` — den läggs till automatiskt och kan inte
ordnas om.

---

### Gruppfilter-pipeline (`group_filter`)

**Ersatt av vägvalet.** Gruppfiltret var ett steg som kunde stoppa kedjan för
listade grupper (svart- eller vitlista). Nu tilldelas grupper en gren, och en
ignorera-gren gör samma sak. Befintliga filter migreras automatiskt (se ovan).

---

### FORS-pipeline (`fors`)

**Vad den väljer:** Meddelanden som börjar med `FORS-RAPPORT`.

**Vad den gör:**
- Parsar strukturerade FORS-fält
- Validerar obligatoriska sektioner
- Skriver separat rapportfil med FORS-frontmatter

---

### PEDARS-pipeline (`pedars`)

**Vad den väljer:** Meddelanden som börjar med `PEDARS` / `PEDARS - UNDERHÅLLSRAPPORT`.

**Vad den gör:**
- Parsar strukturerade underhållsfält (personal, drivmedel, ammunition, reparationer)
- Validerar obligatoriska delar
- Skriver separat PEDARS-rapport

---

### SCRIM-pipeline (`scrim`)

**Vad den väljer:** Meddelanden som börjar med `SCRIM RAPPORT`.

**Vad den gör:**
- Parsar fordonsbeskrivningen (Storlek, Färg, Registrering, Kännetecken, Märke)
- Skriver en `TNR<DDHHMM>.md` med `typ: SCRIM-rapport`
- **Länkar registreringsnumret** som `[[PLÅT]]` i exakt samma kanoniska form som
  7S-pipelinen använder, så samma plåt sedd i en 7S och i en SCRIM blir *en* nod

Kommer från ATAK-formuläret med samma namn, via `oden/tak/scrim.py`.

**Tid.** TNR härleds ur `STUND` (observationen), inte ur ankomsttiden. Rapporterna
vidarebefordras manuellt genom ledningskedjan, så ankomsttiden är fel med
vidarebefordringsfördröjningen — i en skarp fångst tre månader. Kedjan är
`STUND → Skapad → CoT-händelsetid`, och vilken källa som användes står som
`tnr_kalla:` i det dolda `%%`-blocket.

**Registrering.** `R`-fältet normaliseras till versaler utan mellanslag, så
`PHS 331` blir `PHS331`. Utländska plåtar länkas också — fältet är *deklarerat*
som en registrering, så till skillnad från 7S behövs inget svenskt plåtformat.
Saknas plåt renderas `–`: på en checklista är "tittade, ingen plåt" inte samma sak
som "fältet utelämnat".

**Begränsning att känna till.** En plåt som nämns i löptexten, t.ex. rättelsen
`Regnr rättning TOS99218 Polsk registrerad`, länkas **inte** om den är utländsk.
Att hitta utländska plåtar i prosa kräver antingen ett regex brett nog att länka
`E4` och `T-72`, eller en gissning om vilket ord som är en plåt — båda är analys,
som FORMAT_SPEC §6.2 lägger på plugin:en. Rättelsen kommer fram som text i
`**Anmärkning:**` och ordagrant i `%%`-blocket.

**Dedup vid manuell vidarebefordran.** Skickar toppnoden om en rapport med samma
CoT-uid fångas repetitionen av dedupen. Myntas ett nytt uid blir det en ny not med
`_2`-suffix.

---

### Generic Template-pipeline (`generic_template`)

**Vad den väljer:** *Alla* meddelanden som inte redan hanterats.

**Vad den gör:**
- Använder legacy-logik från Oden 2.x (`process_message`)
- Stöder Jinja2-mallar för rapportgenerering
- Hanterar reply-append (svar/quote inom `append_window_minutes`)
- Är övergripande fallback för att ingen meddelande-data går förlorad

**Meddelandeflöde:**
1. Kontrollera ignorerade grupper
2. Generera rapport från Jinja2-mall
3. Hämta bilagor (om aktiverat)
4. Skriva markdown-fil til vault

**Inställningar som påverkar:**
- `vault_path` — mappsökväg för markdown-filer
- `append_window_minutes` — tidsfönster för append-läge
- `report_template` / `append_template` — Jinja2-mallar

**Per gren** (stegets `config` i `routing`):
- `vault_subdir` — mapp under gruppens mapp för allt som hamnar i reserven i
  just den grenen, t.ex. `Övrigt`. Svar som läggs till en tidigare anteckning
  letas också upp där.
- `enabled: false` — reserven avstängd: det inget steg tog skrivs inte, utan
  sparas bara i Flöde (status `ignored`). Så kan en grupp ha en gren med bara
  PEDARS.

---

### Rapportformat (`format:<id>`)

Rapportformat som definieras i inställningarna i stället för i kod
(`oden/report_formats.py`, config-nyckeln `report_formats`). Ett format är data:

| Del | Betydelse |
|-----|-----------|
| `headers` | Rubrikrader. Formatet tar meddelandet när första raden börjar med någon av dem |
| `fields` | Fält som skrivs `Etikett: värde`. Varje fält har `key`, `label`, `aliases`, `required` och `type` (`text` eller `mgrs` — ger `lat`/`lon`/`location` i frontmatter) |
| `sections` | Avsnitt: en rubrikrad (eller `Rubrik: text`), sedan fri text till nästa avsnitt. `key`, `label`, `aliases`, `required` |
| `tnr_field` | Fältet som ger filnamn och rapporttid (`DDHHMM` eller lång form). Tomt = meddelandets tid |
| `file_prefix` | Filen blir `<prefix><TNR>.md`, som för de inbyggda |
| `report_type` | `typ:` i frontmatter |
| `end_marker` | Valfri slutrad, t.ex. `SLUT!` |
| `template` | Valfri Jinja-mall (sandlåda). Börjar den med `---` skriver den hela anteckningen, frontmatter också; annars bara innehållet efter Odens frontmatter. Variabler: `fields`, `sections`, `other`, `id`, `report_type`, `tnr`, `report_time`, `report_time_iso`, `signal_time`, `signal_time_iso`, `sender_name`, `sender_number`, `sender_id`, `lat`/`lon` (från första MGRS-fältet), `group`, `format`, `message`. Filter: `yaml` (citerar för frontmatter), `plate` (registreringsnummer i kanonisk form), `link_plates` (gör plåtar i text till `[[länkar]]`). Tom = fälten som **Etikett:** värde och avsnitten som rubriker |

Etiketter jämförs utan skiftläge, accenter, mellanslag och skiljetecken, så
`Förbandets position` och `FORBANDETS-POSITION` är samma etikett. Rader som inte
är fält och ligger före första avsnittet hamnar under *Övrigt*. Saknas ett
obligatoriskt fält eller avsnitt fallerar steget med skälet (”Anmälan saknar
obligatoriska fält: Vad”) och meddelandet går vidare till nästa steg, precis
som för de inbyggda.

Ett sparat format blir steget `format:<id>` som en gren kan innehålla. Det
skriver en anteckning per rapport på samma sätt som de inbyggda: samma
frontmatter-bas, filnamn, bilagor, undermapp per gren och samma Testruta. Ett
format som används i en gren kan inte tas bort förrän steget tagits bort.

De inbyggda formaten (7S, FORS, PEDARS, SCRIM) finns kvar i kod och ändras inte
här. Varje inbyggt format har en startpunkt (*Utgå från …*) som fyller i
rubriker, fält, avsnitt och en mall för hela anteckningen, frontmatter
inkluderat. Mallen skriver samma anteckning som det inbyggda formatet (utom det
slumpade `id`): för 7S, FORS och SCRIM tecken för tecken, plåtlänkar
inkluderade; för PEDARS med samma rubriker, listor och underrubriker, men
personalsiffrorna i den ordning de står i meddelandet. Testerna
(`StarterTemplateTest`) jämför startpunkterna med de inbyggda.

---

## Administrering

### I Web-gränssnitt

Fliken **Pipelines**:
- **Vägval:** varje källa (TAK, direktmeddelanden, varje känd grupp) med en
  rullista för gren, antal meddelanden senaste 24 h, och en markering för
  grupper med trafik som saknar egen gren. Standardgrenen väljs under listan.
  *Ignorera* är ett val i rullistorna, inte en kolumn: den har inga steg.
  Under listan står vilka källor som ignoreras, med länk till dem i Flöde.
  Routingen har alltid en ignorera-gren (`normalize_routing` lägger till
  den om den saknas).
- **Grenar som kolumner:** varje gren är en kolumn med sina steg i
  körordning (★ = standardgren, antal källor och meddelanden senaste 24 h).
  Varje steg visar undermapp i grenen och hur många meddelanden det hanterat
  senaste 24 h. Sist står kolumnen *Ny gren* (samma steg som standardgrenen,
  eller bara reserven).
- **Detaljpanelen:** klick på en gren eller ett steg visar det till höger.
  För en gren: byt namn, gör till standardgren, ta bort, *Visa grenens
  meddelanden i Flöde*. För ett steg: på/av, upp/ner, *Undermapp i den här
  grenen* (Spara/Ångra), hanterade/hoppade över/fel senaste 24 h och länkar
  till just de meddelandena i Flöde.
- **Testruta:** klistra in ett meddelande och välj källa. Visar vägvalet,
  vad varje steg säger (tog meddelandet, hoppade över, fel — t.ex. vilka
  fält som saknas i en 7S), vilken fil som skulle skrivas och dess innehåll.
  Inget skrivs till valvet, skickas till Signal/TAK eller sparas i databasen
  (`oden/dry_run.py`, `POST /api/pipelines/test`).
- **Rapportformat:** egna format (se ovan) med editor för rubriker, fält,
  avsnitt, TNR-fält, filprefix och mall, och en testruta som visar vilka
  fält som hittades och anteckningen som skulle skrivas. De inbyggda visas
  som startpunkter. Ett sparat format läggs till i en gren med *+ Steg*.
- **Reserven per gren:** klick på *Reserv* i en gren ger *Mapp för allt
  annat* och *Stäng av reserven* (då sparas det inget steg tog bara i Flöde).
- **Grundinställningar per pipeline:** det som gäller i alla grenar
  (standardundermapp, rapportmallar m.m.).

### I config.db

```sql
SELECT value FROM config WHERE key = 'routing';
SELECT value FROM config WHERE key = 'report_formats';
```

---

## Framtida: Pipeline-instanser med inställningar

*Delvis på plats: samma pipeline kan nu ha egen undermapp per gren (stegets `config`). Resten nedan är fortfarande planerat.*

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
| GET | `/api/report-formats` | Egna rapportformat, vilka grenar som använder dem, de inbyggda med startpunkt och mallvariabler |
| PUT | `/api/report-formats` | Spara hela listan (`{"formats": [...]}`); valideras, och ett format som används i en gren kan inte tas bort |
| POST | `/api/report-formats/test` | `{"format", "text"}` → om rubriken matchar, hittade fält och avsnitt, vad som saknas och anteckningen. Skriver inget |

---

## Se även

- [`docs/FEATURES.md`](FEATURES.md#meddelandeflöde) — Arkitektur-överblick
- [`docs/PLAN_3.0.md`](PLAN_3.0.md) — Implementeringsplan för Oden 3.0
- `oden/pipeline_orchestrator.py` — Orkestrering-logik
- `oden/pipelines/` — Pipeline-implementationer
