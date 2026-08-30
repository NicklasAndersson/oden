# Plan: Skicka och ta emot underrättelser till/från TAK

## Utgångsläge

- TAK Server körs på en **annan maskin**. Vi är **användare** (klient), inte
  serveradmin. Vi har (eller kan få) ett klientcertifikat / en data-package-`.zip`
  – samma som en ATAK/WinTAK-enhet enrollas med.
- Oden tar redan emot strukturerade rapporter (7S, FORS, PEDARS) via Signal,
  parserar dem och skriver markdown i valvet. 7S-pipelinen konverterar redan
  MGRS → lat/lon (`oden/pipelines/seven_s.py`, `mgrs`-biblioteket).
- Allt i Oden är redan `asyncio` och `aiohttp` finns.

**Mål:** rapporter med position ska kunna pushas till TAK som CoT-markörer, och
CoT-händelser från andra TAK-klienter ska kunna landa i valvet som rapporter.

## Utvärdering av första utkastet

Rättat/skärpt i den här versionen:

1. **Certformat** – `pytak` läser `.p12` direkt (med lösenord); ingen PEM-konvertering
   krävs. `pytak` kan dessutom importera hela ATAK-data-package-`.zip` (`PREF_PACKAGE`)
   eller enrolla med användarnamn/lösenord. Konfigen speglar nu de faktiska
   `PYTAK_*`-nycklarna istället för påhittade.
2. **Inkommande SA är en brandslang** – en TAK Server pushar *all* lägesbild
   (PLI var ~30 s per klient, spår, chat) till varje ansluten klient. Utan hårt
   filter + dedup skulle Oden skapa tusentals `raw_messages`. Fas 3 har nu en
   explicit dedup-/rate-strategi och `tls+ro://`-läge.
3. **Eko-loop på pipeline-nivå** – om inkommande CoT renderas som text som ser ut
   som en `7S RAPPORT` skulle `TakPublishPipeline` skicka tillbaka den till TAK.
   Åtgärd: inkommande CoT renderas med egen rubrik (`TAK-OBSERVATION`, inte
   `… RAPPORT`) **och** `TakPublishPipeline` hoppar över `_source == "tak"`.
4. **Persistens** – markörer *kan* överleva på servern via `<detail><archive/></detail>`
   och/eller serverns retention-konfig; det är inte enbart en Marti-REST-fråga.
   Vi sätter `<archive/>` som default på rapport-markörer och verifierar mot den
   faktiska servern.
5. **`how`-attribut** – manuellt inknackade rapporter ska vara `how="h-g-i-g-o"`
   (människa, manuellt), inte `m-g` (maskin/GPS). Påverkar hur klienter visar
   noggrannhet.
6. **Ingen fejkad egenposition** – Oden ska *inte* broadcasta en egen
   blue-force-PLI som standard (ingen GPS, skräpar ner kartan). Valbart fast läge.
7. **Klocka & certutgång** – CoT-tider är UTC; kräver NTP-synk på Oden-värden.
   Klientcert går ut (ofta 1–2 år) → övervaka och varna.
8. **Dev/test** – lokal `taky` eller FreeTAKServer (med `FTS_COMPAT=1`) som
   testmål; behöver inte den riktiga servern för att utveckla.

## Protokollval

TAK-klienter pratar **CoT (Cursor on Target)** – små XML-`<event>`-paket.
En "användare" ansluter till TAK Server via streaming-porten:

| Väg | Transport | Auth | Använd? |
|-----|-----------|------|---------|
| 8087 | TCP plain | ingen | bara betrott slutet nät / labb |
| 8089 | TLS (mTLS) | klientcert `.p12` / data package | **ja, standard** |
| 8446 / Marti REST | HTTPS | klientcert | valfritt: radera specifik markör, data packages (bilagor), mission-API |
| UDP multicast 239.2.3.1:6969 | — | ingen | endast lokalt mesh utan server – ej aktuellt |

Streaming-porten räcker för **både ut och in** på samma anslutning
(`tls://`). Vill man skilja flödena: `tls+wo://` (write-only, bara skicka) och en
separat `tls+ro://` (read-only, bara ta emot).

**Kolla med TAK-admin:** kräver deploymentet **data marking / RBAC** (`access`-attribut)
eller att markörer läggs på en specifik **mission/feed**? I så fall behöver
CoT-byggaren sätta rätt attribut, annars kan servern tysta våra events.

## Biblioteksval

**Använd `pytak`** (`pip install "pytak[with_crypto]"`). De-facto Python-biblioteket
för TAK: asyncio, mТLS med `.p12`/PEM/data-package, exponentiell reconnect,
bounded TX/RX-köer (`MAX_OUT_QUEUE=100`, `MAX_IN_QUEUE=500`), TCP/TLS/UDP/Marti.
Att skriva mTLS-klient + reconnect + CoT-serialisering för hand är långt mer än
"några rader" – rung 4 (befintlig lösning finns).

`pytak` drar in `cryptography` (via `lxml`/`cryptography`) – påverkar
DMG/Windows-bundlen (fas 5). Görs till **optional extra** (`oden[tak]`), som `tray`.
Ingen TAK → ingen ny dependency för övriga användare.

> Fallback utan dependency: om kravet reduceras till **plain TCP 8087 på betrott nät**
> räcker `asyncio.open_connection` + f-string-XML (~40 rader). Lägg bara om
> mTLS-kravet försvinner.

## Arkitektur

```
                         ┌────────────────────────────┐
   Signal ──► messages_db ──► PipelineOrchestrator     │
                         │      ├─ TakPublishPipeline ──┼──► tx_queue ─┐
                         │      ├─ seven_s / fors / …   │              │
                         │      └─ generic_template     │          pytak (mTLS)
                         │                              │              │
   valv/*.md ◄───────────┼──── create_raw_message ◄─────┼── TakListener ┘
                         └────────────────────────────┘   rx_queue (filter+dedup)
                                                          syntetiskt kuvert, _source=tak
```

En `TakBridge` (singleton) äger pytak-anslutningen (`clitool.tx_queue` /
`clitool.rx_queue`) och startas i `s7_watcher.py` bredvid Signal-lyssnaren, bara
om `[TAK] enabled = true`. `TakPublishPipeline` producerar; `TakListener`-tasken
konsumerar.

## Fas 1 – CoT-mappning (ren kod, ingen nätverk)

Ny modul `oden/tak/cot.py`. `xml.etree.ElementTree` räcker – inget CoT-bibliotek.

- `report_to_cot(report: dict, *, callsign: str, stale_s: int, archive: bool) -> bytes`
  Bygger CoT-`<event>` från en parserad rapport-dict (fält som pipelines redan
  ger: `lat`, `lon`, `tnr`, `stund_dt` (UTC), `sagesman`, `styrka`, `symbol`,
  `handelse`, `plats`, `report_type`).
  - `uid`: stabil, härledd ur rapporttyp + TNR, t.ex. `ODEN.7S.281430`. En
    uppdaterad/`++`-påfylld rapport → samma uid → ersätter markören.
  - `type`: affiliering. Default `a-u-G` (okänd mark). Härled `a-h-G` (fiende) /
    `a-f-G` (egen) / `a-n-G` (neutral) ur Sägesman/symbol/styrka bara när det går
    entydigt; annars okänd. Konservativt – hellre okänd än fel.
  - `how="h-g-i-g-o"` (människa, manuellt).
  - `time` = nu (UTC), `start` = rapportens `stund_dt`, `stale` = `start + stale_s`.
  - `<point lat lon hae="9999999.0" ce="9999999.0" le="9999999.0"/>` när bara
    lat/lon är kända.
  - `<detail>`: `<contact callsign="7S 281430"/>`, `<remarks>` med hela
    rapporttexten, `<link uid="…" relation="p-p"/>` till Oden-noten,
    `<archive/>` om `archive`, ev. `<usericon iconsetpath="…"/>` för 2525-symbol,
    `<color argb="…"/>`.
- `cot_to_report(xml: bytes) -> InboundCot | None`
  Parserar `<event>` → dataklass med `lat/lon/hae/callsign/uid/type/how/remarks/
  time/stale`. `None` för det vi inte bryr oss om (se Fas 3-filter).
- `latlon_to_mgrs(lat, lon) -> str` – återanvänd `mgrs`-lib, för att visa MGRS i
  inkommande observationstext.

**Test:** `tests/test_tak_cot.py` – rapport-dict → XML (assert lat/lon/type/uid/
how/archive/callsign), XML → dataklass, och round-trip. Validera mot CoT 2.0-XSD
om den bundlas. Helt offline.

## Fas 2 – Utgående (Oden → TAK)

1. `[TAK]`-sektion i `config.ini` + `oden/config.py` (se `docs/TAK_SETUP.md` för
   full förklaring):
   ```ini
   [TAK]
   enabled = false
   cot_url = tls://tak.example.mil:8089   ; tls:// (dubbelriktat) | tls+wo:// | tcp://
   tls_client_cert =                      ; sökväg till .p12 ELLER .pem (cert+nyckel)
   tls_client_key =                       ; separat PEM-nyckel om cert saknar den
   tls_client_password_env = ODEN_TAK_CERT_PASSWORD   ; lösenord läses ur env, ej fil
   tls_ca_cert =                          ; server-CA (PEM); annars systemets truststore
   tls_verify = true                      ; false = farligt, endast labb
   pref_package =                         ; alt: sökväg till ATAK data-package .zip (ersätter cert-fälten)
   callsign = ODEN
   cot_stale_seconds = 3600
   cot_archive = true                     ; sätt <archive/> så servern behåller markören
   publish_report_types = 7S, FORS, PEDARS
   publish_require_coords = true          ; hoppa rapporter utan lat/lon (annars GeoChat, se nedan)
   ```
   `oden/config.py` mappar dessa till `PYTAK_TLS_CLIENT_CERT`,
   `PYTAK_TLS_CLIENT_PASSWORD`, `PYTAK_TLS_CLIENT_CAFILE`, `PYTAK_TLS_DONT_VERIFY`,
   `COT_URL`, `PREF_PACKAGE` innan `pytak.read_pref_package()` /
   `pytak.CLITool(config)`.
2. `oden/tak/bridge.py` – `TakBridge`:
   - `async def start()`: bygg config, `clitool = pytak.CLITool(cfg)`,
     `await clitool.setup()`, kör `clitool.run()` som bakgrundstask.
   - `async def publish_report(report: dict)`: `report_to_cot(...)` →
     `await clitool.tx_queue.put(cot_bytes)`. Full kö → logga warning, släpp
     (aldrig blockera pipelinen).
   - Statuscallback → `app_state` (ansluten, senaste TX/RX/fel, räknare).
   - Reconnect/backoff sköts av pytak.
   - Re-publish-task: om `cot_archive=false`, skicka om aktiva markörer var
     ~`stale/2` så de inte försvinner medan Oden är uppe.
3. `oden/pipelines/tak_publish.py` – `TakPublishPipeline`:
   - Placeras **först** i kedjan. Hoppar direkt om `msg_data.get("_source") == "tak"`
     (eko-skydd) eller `TakBridge` ej aktiv.
   - Återanvänder `parse_7s_report` m.fl. för att peeka. Är det en typ i
     `publish_report_types` med lat/lon → `await bridge.publish_report(...)`.
   - **Returnerar alltid `False`** (icke-konsumerande) → seven_s/fors/pedars kör
     som vanligt efteråt. Dubbelparsning kostar försumbart.
   - Alla fel fångas → `last_warnings`, aldrig fälla rapportskrivningen.
4. Wire in i `s7_watcher.py`: starta `TakBridge` om enabled; registrera
   `tak_publish` i `PipelineOrchestrator._pipeline_map` och default främst i
   `ENABLED_PIPELINES`.

Effekt: en 7S på Signal syns som markör i ATAK inom sekunder, befintligt flöde
oförändrat.

### Valfritt: GeoChat för positionslösa rapporter
Rapporter utan position kan skickas som CoT GeoChat (`type="b-t-f"`,
`<detail><__chat>…</__chat><remarks>…</remarks></detail>`, uid
`GeoChat.<ourUid>.<dest>.<msgId>`) till en team-/allkanal. Egen byggare i
`cot.py`, samma `tx_queue`. Lägg bara om behovet finns.

## Fas 3 – Inkommande (TAK → Oden)

`oden/tak/listener.py` – task som läser `clitool.rx_queue`:

1. **Filter (billigast först), konfig i `[TAK]`:**
   ```ini
   inbound_enabled = false
   inbound_types = a-h-*, a-u-*, b-a-*     ; fiende, okänd, larm. INTE a-f-* (egen PLI-brus)
   inbound_callsign_allow =                 ; tom = alla; annars vitlista
   inbound_callsign_deny =
   inbound_min_move_m = 100                 ; känd uid som rört sig < så här → ignorera
   inbound_group_name = TAK Inkommande
   ```
   - Släpp CoT vars `uid` börjar med `callsign`/`ODEN.` (eget eko).
   - Släpp `a-f-*` blue-force-PLI som default (det är brandslangen).
2. **Dedup / rate-limit** (i minnet, `dict[uid] -> (last_time, last_latlon)`):
   - Ny `uid` → släpp igenom.
   - Känd `uid`: bara igenom om typ ändrats, flyttat ≥ `inbound_min_move_m`, eller
     remarks ändrats. Annars uppdatera bara tidsstämpeln.
   - Hård tak: max N inkommande/min → utöver det, logga och droppa (pytax
     `MAX_IN_QUEUE` ger redan mothållning).
3. **Landa via syntetiskt kuvert** → `create_raw_message(db, account, envelope)`:
   ```python
   envelope = {
       "sourceName": safe_callsign,               # sanerad
       "sourceNumber": f"tak:{safe_uid}",
       "timestamp": cot_epoch_ms,
       "dataMessage": {
           "message": render_observation(cot),    # rubrik: "TAK-OBSERVATION", ej "… RAPPORT"
           "groupV2": {"id": tak_group_id, "name": cfg.inbound_group_name},
       },
       "_source": "tak",
   }
   ```
   Då flyter TAK-observationer genom samma pipelines, web-GUI, retention och
   grupp-filter som allt annat. `render_observation` skriver callsign, tid,
   MGRS + lat/lon, CoT-typ i klartext, och remarks.
   - Enklare alternativ: skriv markdown direkt till valv-mapp `TAK/` via
     `template_loader`. Välj kuvert-vägen om vi vill se dem i meddelandevyn och få
     retention gratis.
4. **Trust boundary – inkommande CoT är osäker indata:**
   - `callsign`/`uid` saneras innan de rör filnamn: tillåt `[A-Za-z0-9 ._-]`,
     avvisa `..`, `/`, styrtecken; trunkeras.
   - lat/lon klampas till `[-90,90]`/`[-180,180]`; orimliga → droppas.
   - `remarks` behandlas som text, trunkeras (t.ex. 4 kB), aldrig HTML/kommandon.
   - Inga URL:er i CoT-detail hämtas utan explicit opt-in.
   - Bounded queue + rate-tak = DoS-skydd.

**Test:** `tests/test_tak_listener.py` – exempel-CoT → kuvert (assert
filnamnssäkerhet, filter släpper/stoppar rätt, dedup undertrycker upprepning,
`_source=tak` går ej vidare till `tak_publish`). Offline.

## Fas 4 – Web-GUI

TAK-panel (flik eller under Konfiguration), mönster från
`oden/web_handlers/config_handlers.py` + `oden/app_state.py`:
- Status: ansluten / frånkopplad / återansluter, senaste TX, senaste RX,
  senaste fel, certets utgångsdatum (varna < 30 dygn).
- Räknare: skickade markörer, mottagna/filtrerade sedan boot.
- Konfig-formulär för `[TAK]` (lösenord maskerat, aldrig i logg/HTML).
- Knapp "Skicka test-CoT" – en markör på angiven MGRS för driftverifiering.

## Fas 5 – Paketering, drift & dokumentation

- `pyproject.toml`: `[project.optional-dependencies]`
  `tak = ["pytak[with_crypto]>=7"]`.
- PyInstaller (`s7_watcher.spec`): verifiera att `pytak`, `cryptography`,
  `lxml` följer med när tak-extran byggs in (hidden imports / binaries).
- **NTP** på Oden-värden – dokumentera som krav (CoT-tider i UTC).
- **Certrotation** – rutin + GUI-varning innan utgång.
- `config.ini`: kommenterad `[TAK]`-sektion, avstängd default.
- `docs/PIPELINES.md`: dokumentera `tak_publish`.
- `docs/TAK_SETUP.md`: operatörsguide (skapad i denna PR) – skaffa cert / data
  package, config, brandvägg (utgående 8089), `taky`-testmål, felsökning.

## Ordning & beroenden

```
Fas 1 (cot.py + test)      ── fristående, börja här
  └─► Fas 2 (utgående)     ── kräver Fas 1 + pytak
  └─► Fas 3 (inkommande)   ── kräver Fas 1 + pytak; oberoende av Fas 2
        └─► Fas 4 (GUI)    ── kräver 2 och/eller 3
Fas 5 löpande
```

## Vad som medvetet skippas nu

- **Marti REST för utgående** – streaming räcker; `<archive/>` ger persistens.
  Lägg Marti om vi behöver *radera* specifika markörer eller ladda upp bilagor.
- **TAK Protocol v1 (protobuf)** – `TAK_PROTO=0` (XML) fungerar mot alla servrar;
  protobuf bara om bandbredd blir ett problem.
- **Missions / Data Sync-feeds** – publicera till råa SA först; mission-API senare
  om förbandet organiserar sig kring missions.
- **Federation, flera servrar, kanal per rapporttyp** – en server, ett callsign.
- **Tvåvägs-kvittens / task (uppdrag) via CoT** – Oden är underrättelsebrygga,
  inte ledningssystem.
- **Bild-/filbilagor** – kräver Marti data-package-flöde; separat plan.
- **Egen blue-force-PLI för Oden** – ingen GPS; valbart fast läge om det efterfrågas.

## Källor

- [PyTAK – Configuration](https://pytak.readthedocs.io/en/stable/configuration/)
- [PyTAK – GitHub](https://github.com/snstac/pytak)
- [CoT base schema (Event.xsd)](https://github.com/docjason/XmlValidate/blob/master/schemas/Event.xsd)
- [FreeTAKServer – CoT Messages](https://freetakteam-freetakserver.mintlify.app/concepts/cot-messages)
