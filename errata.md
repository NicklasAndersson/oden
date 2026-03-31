# Errata (docs vs kod/test)

Datum: 2026-03-30

Det här dokumentet listar verifierade avvikelser mellan dokumentationen (krav), enhetstesterna och nuvarande implementation.

**Princip:** Koden behandlas som facit. Dokumentationen uppdateras för att matcha implementationen.

## Källor som jämförts

- Dokumentation: `docs/WEB_GUI.md`, `docs/FEATURES.md`, `docs/SETUP_FLOW.md`
- Kod: `oden/web_server.py`, `oden/web_handlers/*`, `oden/templates/web/js/dashboard/*`
- Tester: `tests/test_web_gui.py`, `tests/test_security.py`, `tests/test_processing.py`, `tests/test_formatting.py`

## Statuslegend

- **ÅTGÄRDAD**: Dokumentationen har uppdaterats för att matcha koden.
- **KVARSTÅR**: Avvikelsen kvarstår och kräver kravbeslut.

## Avvikelsetabell

| ID | Område | Tidigare avvikelse | Status | Åtgärd |
| ---: | --- | --- | --- | --- |
| 1 | Setup-mode routing | Docs sa att "alla andra anrop omdirigeras till `/setup`", men enbart `/` omdirigeras. | **ÅTGÄRDAD** | Docs uppdaterade: förtydligat att enbart `/` omdirigeras och övriga paths returnerar 404. |
| 2 | Setup endpoint-namn | Docs använde `/api/setup/set-home` och `/api/setup/save` istället för `/api/setup/oden-home` och `/api/setup/save-config`. | **ÅTGÄRDAD** | Docs uppdaterade med korrekta endpoint-namn. |
| 3 | Setup endpoints tillgänglighet | Docs sa "enbart tillgängliga i setup-mode", men setup-routes registreras alltid. | **ÅTGÄRDAD** | Docs uppdaterade: förtydligat att setup-routes alltid registreras och är åtkomliga även i dashboard-mode, men är avsedda för setup-flödet och kan utföra åtgärder som t.ex. soft reset och spara config. |
| 4 | Auth: config reset | Tidigare markerad som åtgärdad. | **ÅTGÄRDAD** | — |
| 5 | Dashboard: INI-export | Docs listade `GET /api/config/export` som endpoint, men den existerar inte i koden. | **ÅTGÄRDAD** | Endpoint borttagen från docs. |
| 6 | Auth-referenser | Docs och README refererade till token-baserad autentisering, men ingen auth finns implementerad. | **ÅTGÄRDAD** | Alla auth-referenser borttagna. Docs och README uppdaterade att korrekt beskriva att ingen autentisering finns. |
| 7 | Konfigurationsnyckel: whitelist | Docs använde `whitelisted_groups`, koden använder `whitelist_groups`. | **ÅTGÄRDAD** | Docs uppdaterade till `whitelist_groups`. |
| 8 | Setup-dokumentation: QR | Docs sa `segno`-biblioteket, koden använder `qrcode`. | **ÅTGÄRDAD** | Docs uppdaterade till `qrcode`. |
| 9 | INI-import endpoint | Docs listade `POST /api/config-file` som dashboard-endpoint, men den existerar inte i koden. | **ÅTGÄRDAD** | Endpoint borttagen från docs. |
| 10 | ideas.md: historiska observationer | ideas.md innehåller observationer som delvis är inaktuella. | **KVARSTÅR** | ideas.md bör granskas separat — den är ett internt arbetsdokument och inte officiell dokumentation. |

## Noteringar

- Alla tester passerar. Denna uppdatering har granskat dokumentationen och korrigerat alla identifierade avvikelser mot koden (koden behandlas som facit).
- Saknade endpoints i docs (INI-export, INI-import) har tagits bort istället för att implementeras — implementera dem vid behov som nya features.
