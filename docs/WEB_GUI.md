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

---

## Första start

Det finns ingen setup-guide och inget setup-läge. Första start skapar
standardinställningar och öppnar dashboarden; se [FIRST_START.md](FIRST_START.md).

## Dashboard-mode

Dashboard-mode aktiveras när konfigurationen är komplett. Alla funktioner beskrivs nedan.

### Flikar

| Flik | Innehåll |
|------|----------|
| **Flöde** | Allt som kommer in från alla källor, vart det tog vägen och varför |
| **Grundläggande** | Tidszon, append-fönster |
| **Obsidian** | Valvets sökväg, katalogstruktur, installera Odens Obsidian-inställningar |
| **Signal** | Allt som rör Signal, i underflikar: Konton (inkl. koppla Signal), Grupper, Kontakter, Kommandosvar, Inställningar |
| **TAK** | Allt som rör TAK: status, QR-anslutning, anslutning, certifikat, inkommande CoT, testmarkör |
| **Pipelines** | Körordning, aktivering och inställningar per pipeline, mallar |
| **Avancerat** | Loggnivå, lagring (dagar, max storlek, rensa nu) och Oden-hemkatalog |

Varje fält har en hjälptext som förklarar vad inställningen gör. Inställningarna sparas automatiskt.

#### Flöde

Varje inkommet meddelande i ankomstordning — från alla Signal-konton och TAK —
med källa, avsändare, kanal, en rå förhandsvisning och en markör per pipeline i
den ordning de kördes. Ersätter den tidigare fliken *Meddelandehantering*.

| Funktion | Beskrivning |
|----------|-------------|
| **Filter** | Källa (varje Signal-konto, TAK), status (hanterade, ignorerade, fel, väntar) och fritextsök |
| **Utan innehåll** | Kvitton och skrivindikatorer är dolda; *Visa dem också* tar med dem |
| **Live** | Uppdateras var 3:e sekund när fliken är öppen; kan pausas |
| **Spår** | Vad varje pipeline gjorde med meddelandet och varför |
| **Rått** | Kuvertet exakt som det lagrades (`raw_messages.envelope_raw`) |
| **Utdata** | Filen som skrevs i valvet (läses bara om den ligger inuti valvet) |
| **Händelser** | Alla pipeline-körningar och deras händelser, även tidigare försök |
| **Kör om** | Kör meddelandet genom pipelinekedjan igen |

#### Grundläggande

Tidszon och append-fönster.

#### Obsidian

Valvets sökväg, grupp-uppdelning av katalogstrukturen och **Installera
Obsidian-inställningar** (kopierar Odens `.obsidian` med Map View till valvet;
en befintlig `.obsidian` skrivs aldrig över).

#### Signal

Underflikar:

##### Konton

Hantera signal-cli-konton (multi-account daemon-läge).

| Funktion | Beskrivning |
|----------|-------------|
| **Lista konton** | Visar alla länkade signal-cli-konton med aktivt konto markerat |
| **Lägg till konto** | Starta QR-kodlänkning för att lägga till ett nytt Signal-konto |
| **Aktivera konto** | Växla aktivt konto — meddelanden behandlas för det valda kontot |
| **Radera konto** | Ta bort kontodata från signal-cli (avregistrerar inte från Signal) |
| **Tvångsradera** | Radera kontodatan direkt från filsystemet (för korrupta konton) |


##### Grupper

Listar alla Signal-grupper som kontot är medlem i.

| Funktion | Beskrivning |
|----------|-------------|
| **Ignorera-knapp** | Lägger till/tar bort gruppen i `ignored_groups` |
| **Whitelist-knapp** | Lägger till/tar bort gruppen i `whitelist_groups` |
| **Gå med via länk** | Textfält för att klistra in en `https://signal.group/…`-inbjudningslänk |
| **Väntande inbjudningar** | Listar grupper som Oden har blivit inbjuden till, med Acceptera/Avböj-knappar |
| **Redigera grupp** | Modal för gruppadministration (namn, beskrivning, medlemmar, behörigheter, grupplänk, försvinnande meddelanden). Visas bara för grupper där Oden är administratör |


##### Kontakter

Listar alla kontakter från signal-cli med namn, nummer och profilnamn.

| Funktion | Beskrivning |
|----------|-----------|
| **Uppdatera från Signal** | Hämtar kontakter på nytt från signal-cli |
| **Redigera kontakt** | Modal för att ändra förnamn, efternamn, smeknamn, anteckning och försvinnande-timer |

##### Kommandosvar

| Funktion | Beskrivning |
|----------|-------------|
| **Lista** | Visar alla konfigurerade autosvar med nyckelord och svarstext |
| **Skapa** | Lägg till nytt autosvar med ett eller flera nyckelord |
| **Redigera** | Ändra nyckelord och/eller svarstext |
| **Ta bort** | Radera ett autosvar |

Nyckelord anges som kommaseparerad lista. Varje nyckelord triggar samma svar när en användare skickar `#nyckelord` i en Signal-grupp.


##### Inställningar

Telefonnummer, visningsnamn och startup-meddelande; signal-cli (host, port,
sökväg, version, extern/ohanterad, diagnostikloggning, loggövervakning och
*Starta om signal-cli*); Signal-protokollinställningar (läskvitton,
skrivindikator, länkförhandsgranskning, sealed sender); och *Signal på/av*.
När Oden körs utan Signal har **Konton** rutan *Koppla Signal* (QR-länkning,
registrering, befintligt konto) — se [FIRST_START.md](FIRST_START.md).

#### TAK

Finns bara om Oden är installerad med `oden[tak]`. Visar anslutningsstatus,
antal skickade/mottagna CoT-händelser, cert-utgångsvarning, anslutning med
ATAK/iTAK-QR-kod, ett konfigformulär och en knapp för att skicka en testmarkör. Detaljer i [TAK_SETUP.md](TAK_SETUP.md).


#### Pipelines

Pipelines-fliken visar hur meddelanden routas i DB-first-flödet och låter dig styra vilka pipelines som körs.

| Funktion | Beskrivning |
|----------|-------------|
| **Aktiva pipelines** | Visar nuvarande körordning för aktiva pipelines |
| **Urvalslogik** | Visar textbeskrivning av hur varje pipeline väljer meddelanden |
| **Aktivera/Inaktivera** | Slå av/på en pipeline direkt från GUI |
| **Ändra ordning** | Flytta pipeline upp/ner i körordning |
| **Körningsräknare** | Visar antal historiska körningar per pipeline |


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


#### Avancerat

Loggnivå; **Lagring** — hur länge (dagar) och hur mycket (MB, 0 = ingen gräns)
av råmeddelanden och pipeline-körningar som sparas, vad databasen innehåller just
nu och *Rensa nu* (rensning sker annars vid start och varje timme, se
[DATABASE.md](DATABASE.md#retention-datarensning)); och
**Oden-hemkatalog**: byt katalog för `config.db`, Signal-data och loggar —
en tom katalog får en kopia av allt, en med `config.db` används som den är.
Gäller efter omstart; låst när `ODEN_HOME` är satt. Se
[FIRST_START.md](FIRST_START.md#byta-hemkatalog-avancerat).

#### Live-loggar

| Egenskap | Beskrivning |
|----------|-------------|
| **Uppdateringsintervall** | Var 3:e sekund (automatisk polling av `/api/logs`) |
| **Buffert** | 500-post cirkulärbuffert i minnet |
| **Innehåll** | Tidsstämpel, loggnivå och meddelande per rad |


### Övriga funktioner

| Funktion | Beskrivning |
|----------|-------------|
| **Shutdown-knapp** | Stäng ner Oden helt (stoppar signal-cli, web-server och tray) |

---

## Säkerhet

### Nätverksbinding

| Miljö | Binding | Åtkomst |
|-------|---------|---------|
| **macOS / Linux** | `127.0.0.1` | Enbart localhost |
| **Docker** | `0.0.0.0` (via `WEB_HOST`) | Alla interface — kräver extern brandvägg/reverse proxy |

Webbgränssnittet har ingen autentisering. Skyddet bygger helt på att det enbart lyssnar på localhost. I Docker-miljö (eller om `WEB_HOST=0.0.0.0` sätts) exponeras ett oskyddat admin-API på alla interface — skydda med brandvägg eller reverse proxy.

---

## API-endpoints

### Signal-koppling och Obsidian

Se [FIRST_START.md](FIRST_START.md#api) för `/api/signal/connect/*` och `/api/obsidian/*`.

### Dashboard-endpoints

#### Konfiguration

Konfigurationssidan innehåller även Oden 3.0-inställningar för DB-first ingest, aktiva pipelines och retention.

| Nyckel | Beskrivning |
|--------|-------------|
| `db_first_enabled` | Om `False` körs det äldre direkta flödet utan persist-first |
| `enabled_pipelines` | JSON-lista som styr körordningen för aktiva pipelines |
| `raw_message_retention_days` | Antal dagar som råmeddelanden och pipeline-events sparas |

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/` | Dashboard HTML-sida |
| GET | `/api/config` | Hämta all konfiguration (JSON) |
| POST | `/api/config-save` | Spara konfiguration (formulärdata) |
| DELETE | `/api/config/reset` | Återställ konfiguration |
| GET | `/api/signal-cli/status` | Hämta signal-cli-status |
| POST | `/api/signal-cli/restart` | Starta om signal-cli-processen |
| POST | `/api/shutdown` | Stäng ner Oden |

#### Signal-konton

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/accounts` | Lista alla länkade konton |
| POST | `/api/accounts/link` | Starta QR-kodlänkning för nytt konto |
| POST | `/api/accounts/link-cancel` | Avbryt pågående länkning |
| GET | `/api/accounts/link-status` | Kontrollera länkningsstatus |
| POST | `/api/accounts/activate` | Växla aktivt konto |
| DELETE | `/api/accounts/{number}` | Radera kontots lokala data |
| DELETE | `/api/accounts/{number}/force` | Tvångsradera kontodata (filsystem) |
| GET | `/api/accounts/devices` | Lista länkade enheter för aktivt konto |

#### Loggar

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/logs` | Hämta loggposter (JSON-array) |

#### Grupper

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/groups` | Lista alla grupper |
| POST | `/api/join-group` | Gå med i grupp via inbjudningslänk |
| POST | `/api/toggle-ignore-group` | Toggla ignorera-status för en grupp |
| POST | `/api/toggle-whitelist-group` | Toggla whitelist-status för en grupp |
| GET | `/api/invitations` | Lista väntande gruppinbjudningar |
| POST | `/api/invitations/accept` | Acceptera gruppinbjudan |
| POST | `/api/invitations/decline` | Avböj gruppinbjudan |
| POST | `/api/groups/refresh` | Uppdatera grupplistan från signal-cli |
| POST | `/api/groups/update` | Uppdatera gruppinställningar (namn, medlemmar, behörigheter m.m.) |

#### Kontakter

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/contacts` | Lista cachade kontakter |
| POST | `/api/contacts/refresh` | Hämta kontakter från signal-cli |
| PUT | `/api/contacts/{number}` | Uppdatera kontaktuppgifter (namn, smeknamn, anteckning, timer) |

#### Flöde och meddelanden

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/flow` | Flödet: meddelanden med väg och skäl per pipeline (`source`, `status` — kommaseparerad, `include_empty`, `limit`, `before_id`) |
| GET | `/api/flow/{id}` | Ett meddelande: spår, rått kuvert, utdatafil och alla pipeline-körningar |
| GET | `/api/messages` | Lista råmeddelanden med filter och paginering |
| GET | `/api/messages/{id}` | Hämta meddelandedetaljer inklusive raw envelope och pipeline-runs |
| GET | `/api/messages/stats` | Hämta aggregat per status/konto/grupp |
| POST | `/api/messages/{id}/reprocess` | Kör om ett lagrat meddelande |

#### Pipelines

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/pipelines` | Lista tillgängliga pipelines, aktiva pipelines och körningsstatistik |
| PATCH | `/api/pipelines/{name}/enabled` | Aktivera/inaktivera en pipeline |
| PATCH | `/api/pipelines/{name}/config` | Uppdatera pipeline-specifik konfiguration |
| POST | `/api/pipelines/reorder` | Uppdatera körordning för aktiva pipelines |

#### Mallar

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/templates` | Lista tillgängliga mallar |
| GET | `/api/templates/{name}` | Hämta mallinnehåll |
| POST | `/api/templates/{name}` | Spara mall |
| POST | `/api/templates/{name}/preview` | Förhandsgranska mall med exempeldata |
| POST | `/api/templates/{name}/reset` | Återställ mall till standard |
| GET | `/api/templates/{name}/export` | Exportera enskild mall |
| GET | `/api/templates/export` | Exportera alla mallar som ZIP |

#### TAK

Kräver att Oden är installerad med `oden[tak]`. Se [TAK_SETUP.md](TAK_SETUP.md).

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/tak/status` | Anslutningsstatus, räknare, senaste fel, cert-utgång |
| GET | `/api/tak/settings` | Aktuella TAK-inställningar (aldrig lösenord) |
| POST | `/api/tak/settings` | Spara TAK-inställningar (återansluter bryggan direkt) |
| POST | `/api/tak/test` | Skicka en testmarkör från en MGRS-position |
| POST | `/api/tak/upload-package` | Ladda upp en ATAK-data-package-`.zip` till `ODEN_HOME/tak/` |

#### Autosvar

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/responses` | Lista alla autosvar |
| GET | `/api/responses/{id}` | Hämta enskilt autosvar |
| POST | `/api/responses/new` | Skapa nytt autosvar |
| POST | `/api/responses/{id}` | Uppdatera autosvar |
| DELETE | `/api/responses/{id}` | Ta bort autosvar |

#### Signal-protokollinställningar

| Metod | Sökväg | Beskrivning |
|-------|--------|-------------|
| GET | `/api/signal-config` | Hämta Signal-protokollinställningar |
| POST | `/api/signal-config` | Spara Signal-protokollinställningar |
