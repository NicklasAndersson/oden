# Web-gränssnitt

Oden har ett inbyggt webbgränssnitt baserat på aiohttp som startar automatiskt vid uppstart. Det här dokumentet beskriver alla sidor, flikar, säkerhetsmodell och API-endpoints i detalj.

---

## Översikt

| Egenskap | Beskrivning |
|----------|-------------|
| **Framework** | aiohttp |
| **Standardadress** | `http://127.0.0.1:8080` |
| **Binding** | Localhost only (`127.0.0.1`). I Docker: `0.0.0.0` via `WEB_HOST`. |
| **Konfiguration** | `web_enabled` (standard: `True`), `web_port` (standard: `8080`) |
| **Två lägen** | Setup-mode (första start) och dashboard-mode (normal drift) |

---

## Setup-mode

Aktiveras automatiskt när ingen giltig konfiguration finns. Enbart setup-routes är tillgängliga — alla andra anrop omdirigeras till `/setup`.

Ingen autentisering krävs i setup-mode.

→ Se [SETUP_FLOW.md](SETUP_FLOW.md) för detaljerad beskrivning av varje steg i wizarden.

---

## Dashboard-mode

Dashboard-mode aktiveras när konfigurationen är komplett. Alla funktioner beskrivs nedan.

### Flikar

#### Konfiguration

Konfigurationssidan har tre underflikar:

| Flik | Beskrivning |
|------|-------------|
| **Grundläggande** | Vanliga inställningar: vault-sökväg, telefonnummer, tidszon, filnamnsformat, loggnivå |
| **Avancerat** | signal-cli-inställningar, append-fönster, startup-meddelande, webbport |
| **Rå config** | Alla konfigurationsnycklar i rått format (key-value) |

Varje fält har en hjälptext som förklarar vad inställningen gör.

**Osparade ändringar:** Om ändringar har gjorts utan att spara visas en amber-färgad banner högst upp och en punkt på fliken.

#### Live-loggar

| Egenskap | Beskrivning |
|----------|-------------|
| **Uppdateringsintervall** | Var 3:e sekund (automatisk polling av `/api/logs`) |
| **Buffert** | 500-post cirkulärbuffert i minnet |
| **Innehåll** | Tidsstämpel, loggnivå och meddelande per rad |

#### Grupper

Listar alla Signal-grupper som kontot är medlem i.

| Funktion | Beskrivning |
|----------|-------------|
| **Ignorera-knapp** | Lägger till/tar bort gruppen i `ignored_groups` |
| **Whitelist-knapp** | Lägger till/tar bort gruppen i `whitelisted_groups` |
| **Gå med via länk** | Textfält för att klistra in en `https://signal.group/…`-inbjudningslänk |
| **Väntande inbjudningar** | Listar grupper som Oden har blivit inbjuden till, med Acceptera/Avböj-knappar |

#### Mallar (Template-editor)

| Funktion | Beskrivning |
|----------|-------------|
| **Split-screen** | Vänster: mallkod (Jinja2). Höger: live-förhandsvisning. |
| **Förhandsvisningsdata** | Växla mellan minimal och full exempeldata |
| **Mallar** | `report.md.j2` (nya rapporter) och `append.md.j2` (tillägg) |
| **Spara** | Ändringar lagras i config_db och gäller från nästa meddelande |
| **Återställ** | Återställ en mall till standardversionen |
| **Export** | Ladda ner en enskild mall eller alla som ZIP-fil |

→ Se [REPORT_TEMPLATE.md](REPORT_TEMPLATE.md) för komplett mallreferens.

#### Autosvar

| Funktion | Beskrivning |
|----------|-------------|
| **Lista** | Visar alla konfigurerade autosvar med nyckelord och svarstext |
| **Skapa** | Lägg till nytt autosvar med ett eller flera nyckelord |
| **Redigera** | Ändra nyckelord och/eller svarstext |
| **Ta bort** | Radera ett autosvar |

Nyckelord anges som kommaseparerad lista. Varje nyckelord triggar samma svar när en användare skickar `#nyckelord` i en Signal-grupp.

#### Regex-editor

| Funktion | Beskrivning |
|----------|-------------|
| **Lista** | Visar alla konfigurerade regex-mönster med namn och uttryck |
| **Redigera** | Ändra namn eller regex-uttryck |
| **Lägg till / ta bort** | Skapa nya mönster eller ta bort befintliga |
| **Testfunktion** | Skriv in testtext och se vilka mönster som matchar i realtid |
| **Validering** | Regex-uttryck valideras innan sparning |

### Övriga funktioner

| Funktion | Beskrivning |
|----------|-------------|
| **INI-export** | Ladda ner konfigurationen som `.ini`-fil |
| **INI-import** | Ladda upp en `.ini`-fil för att importera inställningar |
| **Shutdown-knapp** | Stäng ner Oden helt (stoppar signal-cli, web-server och tray) |

---

## Säkerhet

### Token-baserad autentisering

| Egenskap | Beskrivning |
|----------|-------------|
| **Generering** | Slumpmässig token genereras per session |
| **Hämtning** | `GET /api/token` — returnerar token som JSON |
| **Användning** | HTTP-header `Authorization: Bearer <token>` eller query-parameter `?token=<token>` |
| **Skydd** | Känsliga endpoints (skriv-/raderingsanrop) kräver giltig token |
| **Undantag** | Läs-endpoints och setup-routes kräver ingen token |

### Nätverksbinding

| Miljö | Binding | Åtkomst |
|-------|---------|---------|
| **macOS / Linux** | `127.0.0.1` | Enbart localhost |
| **Docker** | `0.0.0.0` (via `WEB_HOST`) | Alla interface — kräver extern brandvägg/reverse proxy |

---

## API-endpoints

### Setup-endpoints

Dessa är enbart tillgängliga i setup-mode.

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/setup` | Nej | Setup-wizardens HTML-sida |
| GET | `/api/setup/status` | Nej | Aktuell setup-status (JSON) |
| POST | `/api/setup/set-home` | Nej | Sätt Oden-hemkatalog |
| POST | `/api/setup/validate-path` | Nej | Validera en sökväg |
| POST | `/api/setup/start-link` | Nej | Starta QR-kodlänkning |
| POST | `/api/setup/cancel-link` | Nej | Avbryt pågående länkning |
| POST | `/api/setup/start-register` | Nej | Starta nummerregistrering |
| POST | `/api/setup/verify-code` | Nej | Verifiera registreringskod |
| POST | `/api/setup/save` | Nej | Spara setup-konfiguration |
| POST | `/api/setup/install-obsidian-template` | Nej | Installera Obsidian-mallar i valvet |
| DELETE | `/api/setup/reset` | Nej | Mjuk reset (återgå till setup) |

### Dashboard-endpoints

#### Konfiguration

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/` | Nej | Dashboard HTML-sida |
| GET | `/api/token` | Nej | Hämta autentiseringstoken |
| GET | `/api/config` | Nej | Hämta all konfiguration (JSON) |
| POST | `/api/config-save` | ✅ | Spara konfiguration (formulärdata) |
| GET | `/api/config/export` | ✅ | Exportera som INI-fil (nedladdning) |
| POST | `/api/config-file` | Nej | Importera INI-konfiguration |
| DELETE | `/api/config/reset` | ✅ | Återställ konfiguration |
| POST | `/api/shutdown` | ✅ | Stäng ner Oden |

#### Loggar

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/api/logs` | Nej | Hämta loggposter (JSON-array) |

#### Grupper

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/api/groups` | Nej | Lista alla grupper |
| POST | `/api/join-group` | ✅ | Gå med i grupp via inbjudningslänk |
| POST | `/api/toggle-ignore-group` | ✅ | Toggla ignorera-status för en grupp |
| POST | `/api/toggle-whitelist-group` | ✅ | Toggla whitelist-status för en grupp |
| GET | `/api/invitations` | Nej | Lista väntande gruppinbjudningar |
| POST | `/api/invitations/accept` | ✅ | Acceptera gruppinbjudan |
| POST | `/api/invitations/decline` | ✅ | Avböj gruppinbjudan |

#### Mallar

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/api/templates` | Nej | Lista tillgängliga mallar |
| GET | `/api/templates/{name}` | ✅ | Hämta mallinnehåll |
| POST | `/api/templates/{name}` | ✅ | Spara mall |
| POST | `/api/templates/{name}/preview` | ✅ | Förhandsgranska mall med exempeldata |
| POST | `/api/templates/{name}/reset` | ✅ | Återställ mall till standard |
| GET | `/api/templates/{name}/export` | Nej | Exportera enskild mall |
| GET | `/api/templates/export` | Nej | Exportera alla mallar som ZIP |

#### Autosvar

| Metod | Sökväg | Auth | Beskrivning |
|-------|--------|------|-------------|
| GET | `/api/responses` | Nej | Lista alla autosvar |
| GET | `/api/responses/{id}` | ✅ | Hämta enskilt autosvar |
| POST | `/api/responses/new` | ✅ | Skapa nytt autosvar |
| POST | `/api/responses/{id}` | ✅ | Uppdatera autosvar |
| DELETE | `/api/responses/{id}` | ✅ | Ta bort autosvar |
