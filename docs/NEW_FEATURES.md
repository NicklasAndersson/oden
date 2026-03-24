# Nya funktioner — Implementeringsspecifikation

Oden använder idag 10 av signal-cli:s 49 JSON-RPC-metoder. Det här dokumentet beskriver 7 nya funktioner som utnyttjar oanvända metoder. Varje funktion har komplett teknisk specifikation, integrationspunkter och JSON-RPC-parametrar.

---

## Innehåll

| # | Funktion | signal-cli-metod | Status |
|---|----------|-------------------|-----------|
| 1 | [Auto-reaktion vid sparad rapport](#1-auto-reaktion-vid-sparad-rapport) | `sendReaction` | ✅ Implementerad |
| 2 | [Läskvitton för bearbetade meddelanden](#2-läskvitton-för-bearbetade-meddelanden) | `sendReceipt` | ✅ Implementerad |
| 3 | [Kontaktlista och namnupplösning](#3-kontaktlista-och-namnupplösning) | `listContacts` | Hög |
| 4 | [Enhetslista i webbgränssnitt](#4-enhetslista-i-webbgränssnitt) | `listDevices` | Medel |
| 5 | [Signal-inställningar i Avancerat-fliken](#5-signal-inställningar-i-avancerat-fliken) | `updateConfiguration` | Medel |
| 6 | [Gruppadministration från webbgränssnitt](#6-gruppadministration-från-webbgränssnitt) | `updateGroup` | Medel |
| 7 | [Kontakthantering från webbgränssnitt](#7-kontakthantering-från-webbgränssnitt) | `updateContact` | Medel |

---

## 1. Auto-reaktion vid sparad rapport

### Beskrivning

Oden reagerar automatiskt med en ✅-emoji på varje meddelande som sparats till vault. Detta ger avsändaren omedelbar visuell feedback direkt i Signal-chatten att rapporten har tagits emot och bearbetats.

### Konfiguration

| Nyckel | Typ | Default | Beskrivning |
|--------|-----|---------|-------------|
| `auto_reaction_enabled` | bool | `false` | Aktivera/avaktivera auto-reaktioner |
| `auto_reaction_emoji` | str | `"✅"` | Valfri emoji att reagera med |

### signal-cli JSON-RPC

**Metod:** `sendReaction`

```json
{
  "jsonrpc": "2.0",
  "method": "sendReaction",
  "id": "reaction-1",
  "params": {
    "account": "+46701234567",
    "emoji": "✅",
    "targetAuthor": "+46709876543",
    "targetTimestamp": 1643461800000,
    "groupId": ["base64-encoded-group-id"],
    "remove": false
  }
}
```

**Parametrar:**

| Parameter | Typ | Obligatorisk | Beskrivning |
|-----------|-----|--------------|-------------|
| `emoji` | string | ✓ | Unicode-emoji (en grafem-kluster) |
| `targetAuthor` | string | ✓ | Avsändarens telefonnummer |
| `targetTimestamp` | long | ✓ | Tidsstämpel (ms) på meddelandet att reagera på |
| `recipient` | string[] | — | Telefonnummer (för DM) |
| `groupId` | string[] | — | Grupp-ID (för gruppmeddelanden) |
| `remove` | boolean | — | `true` för att ta bort reaktion |

**Svar:** `SendMessageResults` (tidsstämpel + leveransstatus)

### Integrationspunkter i kodbasen

Reaktionen ska triggas på **exakt två ställen** i `processing.py` — efter lyckad filskrivning:

**Punkt 1 — Ny fil skapad** (efter `WROTE:`-loggen, ~L378):
```
Tillgängliga variabler:
- source_number  → targetAuthor
- envelope["timestamp"]  → targetTimestamp (redan i ms)
- group_id  → groupId (eller None för DM)
```

**Punkt 2 — Append lyckad** (efter `APPENDED`-loggen, ~L275):
```
Tillgängliga variabler:
- source_number  → targetAuthor
- envelope["timestamp"]  → targetTimestamp
- group_id  → groupId
```

### Implementeringsdetaljer

1. **Ny config:** Lägg till `auto_reaction_enabled` (bool) och `auto_reaction_emoji` (str) i:
   - `config_db.py` → `DEFAULT_CONFIG` och `TYPE_MAP`
   - `config.py` → exportera som `AUTO_REACTION_ENABLED` och `AUTO_REACTION_EMOJI`
   - `config.py` → `reload_config()` globala deklarationer

2. **Ny hjälpfunktion** i `processing.py`:
   ```python
   async def _send_reaction(source_number, timestamp, group_id):
       if not cfg.AUTO_REACTION_ENABLED:
           return
       params = {
           "account": cfg.SIGNAL_NUMBER,
           "emoji": cfg.AUTO_REACTION_EMOJI,
           "targetAuthor": source_number,
           "targetTimestamp": timestamp,
       }
       if group_id:
           params["groupId"] = [group_id]
       else:
           params["recipient"] = [source_number]
       
       await get_app_state().send_jsonrpc("sendReaction", params=params)
   ```

3. **Fire-and-forget:** Reaktionen bör köras utan att blockera meddelandeflödet. Använd `asyncio.create_task()` och fånga eventuella fel tyst (logga som warning).

4. **GUI-konfiguration:** Lägg till toggle + emoji-fält i Avancerat-fliken i `dashboard.html`.

### Begränsningar och kantfall

- Kommando-meddelanden (`#help` etc.) ska **inte** trigga reaktion — de bearbetas separat och sparas inte till vault
- Meddelanden som börjar med `--` (ignorerade) triggar inte heller
- Om signal-cli-anslutningen är nere vid reaktionstillfället ska felet loggas som warning, inte krascha
- Tidsstämpeln `envelope["timestamp"]` är redan i millisekunder — **skicka den direkt**, konvertera inte

---

## 2. Läskvitton för bearbetade meddelanden

### Beskrivning

Oden skickar läskvitton (read receipts) till avsändaren när ett meddelande har bearbetats. I Signal visas detta som "Läst" under meddelandet. Kompletterar auto-reaktionen med en mer diskret bekräftelse.

### Konfiguration

| Nyckel | Typ | Default | Beskrivning |
|--------|-----|---------|-------------|
| `auto_read_receipt_enabled` | bool | `false` | Aktivera/avaktivera läskvitton |

### signal-cli JSON-RPC

**Metod:** `sendReceipt`

```json
{
  "jsonrpc": "2.0",
  "method": "sendReceipt",
  "id": "receipt-1",
  "params": {
    "account": "+46701234567",
    "recipient": "+46709876543",
    "targetTimestamp": [1643461800000],
    "type": "read"
  }
}
```

**Parametrar:**

| Parameter | Typ | Obligatorisk | Beskrivning |
|-----------|-----|--------------|-------------|
| `recipient` | string | ✓ | Avsändarens telefonnummer |
| `targetTimestamp` | long[] | ✓ | Lista med tidsstämplar (1+ meddelanden) |
| `type` | string | — | `"read"` (default) eller `"viewed"` |

**Svar:** `SendMessageResults`

### Integrationspunkter

Samma två punkter som auto-reaktion i `processing.py`:
- Ny fil skapad (~L378, efter `WROTE:`)
- Append lyckad (~L275, efter `APPENDED`)

### Implementeringsdetaljer

1. **Ny config:** Lägg till `auto_read_receipt_enabled` (bool) i `config_db.py` och `config.py`.

2. **Ny hjälpfunktion** i `processing.py`:
   ```python
   async def _send_read_receipt(source_number, timestamp):
       if not cfg.AUTO_READ_RECEIPT_ENABLED:
           return
       await get_app_state().send_jsonrpc("sendReceipt", params={
           "account": cfg.SIGNAL_NUMBER,
           "recipient": source_number,
           "targetTimestamp": [timestamp],
           "type": "read",
       })
   ```

3. **Fire-and-forget:** Samma mönster som reaktioner — `asyncio.create_task()` med felhantering.

4. **Batch-möjlighet (framtida):** `targetTimestamp` accepterar en lista, så man kunde samla kvitton och skicka i bulk. Inte nödvändigt i v1.

### Relation till updateConfiguration

`updateConfiguration` (funktion #5) har en `readReceipts`-inställning som styr om signal-cli skickar läskvitton automatiskt. Om den är `true` hanterar signal-cli det själv — men den täcker inte Odens specifika behov (kvitto vid bearbetning, inte vid mottagning). De två funktionerna kompletterar varandra.

### Begränsningar

- Kvitton skickas alltid till en **individ** (recipient), inte till en grupp
- Samma kantfall som auto-reaktion gäller (kommando-meddelanden, `--`-prefix, anslutningsfel)

---

## 3. Kontaktlista och namnupplösning

### Beskrivning

Hämta kontakter från signal-cli för att:
- Förbättra namnupplösning i rapporter (idag beroende av `sourceName` i envelope-data som kan vara tom)
- Visa en kontaktlista i webbgränssnittet
- Mappa telefonnummer till namn i gruppmedlemslistor

### Konfiguration

Ingen ny konfiguration krävs — funktionen är alltid tillgänglig.

### signal-cli JSON-RPC

**Metod:** `listContacts`

```json
{
  "jsonrpc": "2.0",
  "method": "listContacts",
  "id": "contacts-1",
  "params": {
    "account": "+46701234567"
  }
}
```

**Parametrar:**

| Parameter | Typ | Obligatorisk | Beskrivning |
|-----------|-----|--------------|-------------|
| `recipient` | string[] | — | Filtrera på specifika nummer |
| `allRecipients` | boolean | — | Inkludera alla kända (även icke-kontakter) |
| `blocked` | boolean | — | Filtrera blockerade (true/false/utelämna) |
| `name` | string | — | Filtrera på namn (delsträng) |

**Svar:** Array av kontaktobjekt:
```json
[
  {
    "number": "+46701234567",
    "uuid": "550e8400-...",
    "username": "nicklas.01",
    "name": "Nicklas Andersson",
    "givenName": "Nicklas",
    "familyName": "Andersson",
    "nickName": "Nicke",
    "note": "",
    "blocked": false,
    "hidden": false,
    "messageExpirationTime": 0,
    "profileSharingEnabled": true,
    "profile": {
      "lastUpdateTimestamp": 1643461800000,
      "givenName": "Nicklas",
      "familyName": "A",
      "about": "",
      "aboutEmoji": ""
    }
  }
]
```

### Integrationspunkter

**A) Namnupplösning i processing.py:**

Idag används `source_name = envelope.get("sourceName", "Okänd")`. Med kontaktlistan kan man falla tillbaka till kontaktnamn:

```
Löser namn i ordning:
1. envelope.sourceName (Signal-profilnamn, sätts av avsändaren)
2. Kontaktnamn från listContacts-cache (sätts av Oden-användaren)
3. "Okänd" som sista utväg
```

**B) Webbgränssnitt:**

- Ny API-endpoint: `GET /api/contacts` → hämta cachad kontaktlista
- Ny API-endpoint: `POST /api/contacts/refresh` → hämta från signal-cli
- Visa kontaktnamn bredvid telefonnummer i gruppmedlemslistor

### Implementeringsdetaljer

1. **Kontaktcache i app_state:** Lägg till `contacts: dict[str, dict]` i `AppState`. Nyckel: telefonnummer, värde: kontaktobjekt. Cacheas i minnet och uppdateras vid startup + manuell refresh.

2. **Startup-hämtning** i `signal_listener.py` (efter `listGroups`-anropet, ~L107):
   ```python
   contacts = await app_state.send_jsonrpc("listContacts", params={
       "account": cfg.SIGNAL_NUMBER,
       "allRecipients": True,
   })
   app_state.update_contacts(contacts)
   ```

3. **Namnupplösnings-hjälpfunktion:**
   ```python
   def resolve_name(source_number: str, envelope_name: str) -> str:
       if envelope_name and envelope_name != source_number:
           return envelope_name
       contact = app_state.contacts.get(source_number)
       if contact:
           return contact.get("name") or contact.get("nickName") or contact["number"]
       return "Okänd"
   ```

4. **Webb-handler** i ny fil `contact_handlers.py`:
   - `GET /api/contacts` → returnerar `app_state.contacts` som JSON
   - `POST /api/contacts/refresh` → kör `listContacts` RPC, updaterar cache

5. **Gruppmedlemmar:** I `groups_handler()` kan kontaktcachen användas för att berika `members`-listan med namn istället för bara telefonnummer.

### Begränsningar

- Kontaktlistan innehåller bara kända kontakter — okända nummer returnerar inga namn
- `allRecipients: True` ger alla som signal-cli har sett, inte bara sparade kontakter
- Profilnamn styrs av avsändaren och kan ändras när som helst

---

## 4. Enhetslista i webbgränssnitt

### Beskrivning

Visa länkade enheter (devices) i Signal-konton-fliken. Hjälper användaren att verifiera att Oden är korrekt länkad och diagnostisera problem med enhetsanslutning.

### signal-cli JSON-RPC

**Metod:** `listDevices`

```json
{
  "jsonrpc": "2.0",
  "method": "listDevices",
  "id": "devices-1",
  "params": {
    "account": "+46701234567"
  }
}
```

**Parametrar:** Inga utöver `account`.

**Svar:**
```json
[
  {
    "id": 1,
    "name": "iPhone",
    "createdTimestamp": 1600000000000,
    "lastSeenTimestamp": 1643461800000
  },
  {
    "id": 2,
    "name": "Oden Bridge",
    "createdTimestamp": 1643000000000,
    "lastSeenTimestamp": 1643461800000
  }
]
```

### Integrationspunkter

**Signal-konton-fliken** i `dashboard.html` (tab `accounts`). Lägg till en "Enheter"-sektion under kontolistan.

### Implementeringsdetaljer

1. **Ny API-endpoint** i `account_handlers.py`:
   ```python
   async def devices_handler(request):
       response = await get_app_state().send_jsonrpc("listDevices", params={
           "account": cfg.SIGNAL_NUMBER,
       })
       return web.json_response(response or [])
   ```

2. **Route-registrering** i `web_server.py`:
   ```python
   app.router.add_get("/api/devices", devices_handler)
   ```

3. **Frontend** i `accounts.js`:
   - Lägg till `loadDevices()`-funktion som anropas vid lazy-load av konton-fliken
   - Rendrera tabell med kolumner: Namn, Skapad, Senast sedd
   - Formatera tidsstämplar till lokalt datumformat

4. **HTML:** Lägg till `<div id="devices-section">` i konton-fliken med rubrik "Länkade enheter" och en uppdatera-knapp.

### Visning

```
┌─────────────────────────────────────────────────────┐
│ Länkade enheter                    [Uppdatera]      │
├────┬──────────────┬────────────┬───────────────────┤
│ ID │ Namn         │ Skapad     │ Senast sedd       │
├────┼──────────────┼────────────┼───────────────────┤
│ 1  │ iPhone       │ 2020-09-13 │ 2022-01-29 14:30  │
│ 2  │ Oden Bridge  │ 2022-01-24 │ 2022-01-29 14:30  │
└────┴──────────────┴────────────┴───────────────────┘
```

### Begränsningar

- Oden kör som länkad enhet (device) — den kan bara **lista** enheter, inte ta bort dem (det kräver primärkontots behörighet)
- `lastSeenTimestamp` uppdateras inte i realtid — det är signal-serverns senaste registrering

---

## 5. Signal-inställningar i Avancerat-fliken

### Beskrivning

Exponera signal-cli:s Signal-protokollinställningar i webbgränssnittets Avancerat-flik. Dessa inställningar kontrollerar vad Oden-kontot delar med andra användare.

### signal-cli JSON-RPC

**Metod:** `updateConfiguration`

```json
{
  "jsonrpc": "2.0",
  "method": "updateConfiguration",
  "id": "config-1",
  "params": {
    "account": "+46701234567",
    "readReceipts": false,
    "typingIndicators": false,
    "linkPreviews": false,
    "unidentifiedDeliveryIndicators": false
  }
}
```

**Parametrar:**

| Parameter | Typ | Default | Beskrivning |
|-----------|-----|---------|-------------|
| `readReceipts` | boolean | — | Skicka automatiska läskvitton |
| `typingIndicators` | boolean | — | Visa "skriver..."-indikator |
| `linkPreviews` | boolean | — | Generera länkförhandsgranskningar |
| `unidentifiedDeliveryIndicators` | boolean | — | Visa sealed sender-indikatorer |

**Svar:** Tomt (void) — inställningarna sparas direkt.

**Obs:** Alla parametrar är valfria. Utelämnade parametrar ändras inte.

### Integrationspunkter

**Avancerat-fliken** i `dashboard.html` (formulär `#config-form-advanced`). Nuvarande innehåll:
- signal-cli-inställningar (host, port, path, unmanaged)
- Web server (enabled, port)
- Loggning (nivå)
- Regex-mönster

Lägg till en ny sektion **"Signal-protokoll"** efter loggning-sektionen.

### Implementeringsdetaljer

1. **Ingen persistent config i Oden:** Dessa inställningar lagras i signal-cli:s egen data, inte i Odens config.db. De behöver inte sparas i config_db.

2. **Läsning av nuvarande värden:** signal-cli har ingen `getConfiguration`-metod. Alternativ:
   - Spara senast satta värden i config_db som referens
   - Eller visa toggle-knappar utan att indikera nuvarande tillstånd (enklare men sämre UX)
   - **Rekommendation:** Spara en kopia i config_db (`signal_read_receipts`, `signal_typing_indicators`, `signal_link_previews`) så att GUI:t kan visa aktuellt tillstånd

3. **Ny API-endpoint** i `config_handlers.py`:
   ```python
   async def signal_config_handler(request):
       data = await request.json()
       params = {"account": cfg.SIGNAL_NUMBER}
       
       for key in ["readReceipts", "typingIndicators", "linkPreviews"]:
           if key in data:
               params[key] = bool(data[key])
       
       await get_app_state().send_jsonrpc("updateConfiguration", params=params)
       
       # Spara kopia i config_db
       for key, value in data.items():
           set_config_value(CONFIG_DB, f"signal_{to_snake_case(key)}", value)
       
       return web.json_response({"success": True})
   ```

4. **Route-registrering:** Lägg till i `PROTECTED_ENDPOINTS` (kräver token).

5. **HTML:** Fyra checkboxar i Avancerat-fliken:
   ```
   ┌─────────────────────────────────────┐
   │ Signal-protokoll                    │
   │                                     │
   │ ☐ Läskvitton                       │
   │ ☐ Skrivindikator                   │
   │ ☐ Länkförhandsgranskning           │
   │ ☐ Sealed sender-indikatorer        │
   │                                     │
   │ [Spara Signal-inställningar]        │
   └─────────────────────────────────────┘
   ```

### Rekommenderade defaults för Oden

- **Läskvitton:** `false` — Oden hanterar egna kvitton (funktion #2)
- **Skrivindikator:** `false` — Oden "skriver" inte på samma sätt som en användare
- **Länkförhandsgranskning:** `false` — onödig nätverkstrafik, integritetskänsligt
- **Sealed sender:** `false` — ej relevant

### Begränsningar

- Inställningarna gäller hela kontot, inte per grupp/kontakt
- Ingen `getConfiguration`-metod finns — GUI:t kan inte läsa aktuella värden direkt från signal-cli

---

## 6. Gruppadministration från webbgränssnitt

### Beskrivning

Utöka grupphanteringen i webbgränssnittet med administratörsfunktioner: byta gruppnamn, lägga till/ta bort medlemmar, ändra behörigheter och hantera grupplänk. Särskilt användbart för Hemvärns-samordnare som administrerar rapporteringsgrupper.

### signal-cli JSON-RPC

**Metod:** `updateGroup`

```json
{
  "jsonrpc": "2.0",
  "method": "updateGroup",
  "id": "group-update-1",
  "params": {
    "account": "+46701234567",
    "groupId": "base64-group-id",
    "name": "7s-rapporter",
    "description": "Rapporteringsgrupp för 7:e skyttekompaniet",
    "member": ["+46709999888"],
    "removeMember": ["+46708888777"],
    "expiration": 604800,
    "setPermissionAddMember": "only-admins",
    "link": "enabled-with-approval"
  }
}
```

**Parametrar:**

| Parameter | Typ | Obligatorisk | Beskrivning |
|-----------|-----|--------------|-------------|
| `groupId` | string | ✓* | Grupp att uppdatera (utelämna för att skapa ny) |
| `name` | string | — | Nytt gruppnamn |
| `description` | string | — | Gruppbeskrivning |
| `avatar` | string | — | Sökväg till avatar-bild |
| `member` | string[] | — | Lägg till medlemmar |
| `removeMember` | string[] | — | Ta bort medlemmar |
| `admin` | string[] | — | Gör till administratör |
| `removeAdmin` | string[] | — | Ta bort administratörsbehörighet |
| `ban` | string[] | — | Banna medlemmar |
| `unban` | string[] | — | Avbanna medlemmar |
| `resetLink` | boolean | — | Återställ grupplänk |
| `link` | string | — | `"enabled"`, `"enabled-with-approval"`, `"disabled"` |
| `setPermissionAddMember` | string | — | `"every-member"` eller `"only-admins"` |
| `setPermissionEditDetails` | string | — | `"every-member"` eller `"only-admins"` |
| `setPermissionSendMessages` | string | — | `"every-member"` eller `"only-admins"` (meddelandegrupp) |
| `expiration` | int | — | Försvinnande meddelanden i sekunder |

**Svar:** `SendGroupMessageResults` + `{groupId}` om ny grupp.

### Integrationspunkter

**Gruppfliken** i `dashboard.html`. Utöka varje grupprad med en "Redigera"-knapp som öppnar en modal/expanderingsvy.

### Implementeringsdetaljer

1. **Nya API-endpoints** i `group_handlers.py`:

   ```python
   # POST /api/groups/update — uppdatera grupp
   # POST /api/groups/create — skapa ny grupp
   # POST /api/groups/{groupId}/members — lägg till medlemmar
   # DELETE /api/groups/{groupId}/members/{number} — ta bort medlem
   ```

2. **Huvudhandler:**
   ```python
   async def update_group_handler(request):
       data = await request.json()
       group_id = data.get("groupId")
       
       params = {"account": cfg.SIGNAL_NUMBER, "groupId": group_id}
       
       for field in ["name", "description", "expiration", "link",
                      "setPermissionAddMember", "setPermissionEditDetails",
                      "setPermissionSendMessages"]:
           if field in data:
               params[field] = data[field]
       
       for list_field in ["member", "removeMember", "admin", "removeAdmin",
                          "ban", "unban"]:
           if list_field in data and data[list_field]:
               params[list_field] = data[list_field]
       
       result = await get_app_state().send_jsonrpc("updateGroup", params=params)
       
       # Uppdatera lokal cache
       await refresh_groups_from_signal()
       
       return web.json_response({"success": True, "result": result})
   ```

3. **Route-registrering:** Alla endpoints i `PROTECTED_PREFIXES` (kräver token).

4. **Frontend — Gruppredigerings-modal:**
   ```
   ┌─────────────────────────────────────────────────────┐
   │ Redigera grupp: 7s-rapporter              [Stäng]   │
   ├─────────────────────────────────────────────────────┤
   │ Namn:        [7s-rapporter          ]               │
   │ Beskrivning: [Rapporteringsgrupp... ]               │
   │                                                     │
   │ Försvinnande meddelanden: [1 vecka ▼]               │
   │                                                     │
   │ Behörigheter:                                       │
   │   Lägg till medlemmar: (•) Alla  ( ) Bara admins   │
   │   Redigera detaljer:   (•) Alla  ( ) Bara admins   │
   │   Skicka meddelanden:  (•) Alla  ( ) Bara admins   │
   │                                                     │
   │ Grupplänk: (•) Av  ( ) På  ( ) Med godkännande     │
   │                                                     │
   │ Medlemmar (5):                                      │
   │   +46701234567 (Nicklas) — Admin          [Ta bort] │
   │   +46709876543 (Anna)                     [Ta bort] │
   │   +46708765432 (Erik)            [Gör admin]        │
   │                                                     │
   │ Lägg till medlem: [+46...        ] [Lägg till]      │
   │                                                     │
   │              [Spara ändringar]                       │
   └─────────────────────────────────────────────────────┘
   ```

5. **Kontaktintegration:** Använd kontaktcachen (funktion #3) för att visa namn bredvid telefonnummer i medlemslistan.

### Begränsningar

- Oden måste vara **administratör** i gruppen för att kunna ändra inställningar och ta bort medlemmar
- Gruppnamnsändring påverkar vault-mappnamnet — befintliga filer ligger kvar i den gamla mappen. Överväg att lägga till logik för att byta namn på vault-mappen automatiskt, eller dokumentera att användaren behöver göra det manuellt
- `avatar` kräver en lokal filsökväg — behöver filuppladdning i GUI (scope för framtida iteration)
- Att skapa ny grupp kräver minst en initial medlem

---

## 7. Kontakthantering från webbgränssnitt

### Beskrivning

Hantera kontakter direkt från webbgränssnittet: sätt visningsnamn, nick, anteckningar och timer för försvinnande meddelanden. Användbart för att märka kontakter med Hemvärns-befattningar och ställa in säkerhetstimer.

### signal-cli JSON-RPC

**Metod:** `updateContact`

```json
{
  "jsonrpc": "2.0",
  "method": "updateContact",
  "id": "contact-1",
  "params": {
    "account": "+46701234567",
    "recipient": "+46709876543",
    "name": "Anna Svensson",
    "givenName": "Anna",
    "familyName": "Svensson",
    "nickGivenName": "Plutch 1-1",
    "note": "Plutonchef 1:a plutonen",
    "expiration": 604800
  }
}
```

**Parametrar:**

| Parameter | Typ | Obligatorisk | Beskrivning |
|-----------|-----|--------------|-------------|
| `recipient` | string | ✓ | Kontaktens telefonnummer |
| `name` | string | — | Fullständigt namn (sätter givenName) |
| `givenName` | string | — | Förnamn |
| `familyName` | string | — | Efternamn |
| `nickGivenName` | string | — | Smeknamn (förnamn) |
| `nickFamilyName` | string | — | Smeknamn (efternamn) |
| `note` | string | — | Anteckning om kontakten |
| `expiration` | int | — | Försvinnande meddelanden i sekunder (0 = av) |

**Svar:** Tomt (void)

### Integrationspunkter

Bygg kontakthanteringen in i kontaktlista-funktionen (funktion #3). `listContacts` visar kontakter, klick på en kontakt öppnar redigeringsvy med `updateContact`.

### Implementeringsdetaljer

1. **Ny API-endpoint** i `contact_handlers.py`:
   ```python
   # GET /api/contacts → listContacts (funktion #3)
   # POST /api/contacts/refresh → hämta från signal-cli
   # PUT /api/contacts/{number} → updateContact
   ```

2. **Update-handler:**
   ```python
   async def update_contact_handler(request):
       number = request.match_info["number"]
       data = await request.json()
       
       params = {"account": cfg.SIGNAL_NUMBER, "recipient": number}
       
       for field in ["name", "givenName", "familyName",
                      "nickGivenName", "nickFamilyName", "note"]:
           if field in data:
               params[field] = str(data[field])
       
       if "expiration" in data:
           params["expiration"] = int(data["expiration"])
       
       await get_app_state().send_jsonrpc("updateContact", params=params)
       
       # Uppdatera lokal kontaktcache
       contacts = await get_app_state().send_jsonrpc("listContacts", params={
           "account": cfg.SIGNAL_NUMBER, "allRecipients": True,
       })
       app_state.update_contacts(contacts)
       
       return web.json_response({"success": True})
   ```

3. **Route-registrering:** `PUT /api/contacts/{number}` i `PROTECTED_PREFIXES`.

4. **Frontend — Kontaktlista med redigering:**
   ```
   ┌─────────────────────────────────────────────────────────┐
   │ Kontakter (23)                    [Uppdatera]           │
   ├─────────────────────────────────────────────────────────┤
   │ 🔍 [Sök namn eller nummer...              ]            │
   │                                                         │
   │ +46701234567 — Nicklas Andersson            [Redigera]  │
   │ +46709876543 — Anna Svensson (Plutch 1-1)   [Redigera]  │
   │ +46708765432 — (okänd)                      [Redigera]  │
   │ ...                                                     │
   └─────────────────────────────────────────────────────────┘

   ┌─────────────────────────────────────────────────────┐
   │ Redigera kontakt: +46709876543           [Stäng]    │
   ├─────────────────────────────────────────────────────┤
   │ Förnamn:     [Anna             ]                    │
   │ Efternamn:   [Svensson         ]                    │
   │ Smeknamn:    [Plutch 1-1       ]                    │
   │ Anteckning:  [Plutonchef 1:a plutonen    ]          │
   │                                                     │
   │ Försvinnande meddelanden: [1 vecka ▼]               │
   │   ( ) Av  ( ) 1 tim  ( ) 1 dag  (•) 1 vecka        │
   │                                                     │
   │              [Spara]                                 │
   └─────────────────────────────────────────────────────┘
   ```

5. **Exponeringstimer-presets:**
   - Av: `0`
   - 1 timme: `3600`
   - 1 dag: `86400`
   - 1 vecka: `604800`
   - 4 veckor: `2419200`

### Relation till funktion #3 (listContacts)

Funktion #3 och #7 bör implementeras tillsammans. `listContacts` ger läsningen, `updateContact` ger skrivningen. De delar:
- Samma kontaktcache i `app_state`
- Samma API-prefix (`/api/contacts/`)
- Samma frontend-komponent (kontaktlista)

### Begränsningar

- `name` sätter bara `givenName` (signal-cli tolkar `name` som given name)
- Anteckningar (`note`) synkroniseras till alla länkade enheter men visas bara i Signal Desktop
- Exponeringstimern ändrar timern för hela konversationen, inte bara framtida meddelanden
- Smeknamn (`nickGivenName`/`nickFamilyName`) är Oden-lokala — de synkroniseras inte till motparten

---

## Implementeringsordning och beroenden

```
Fas 1 — Backend-hooks (inga GUI-ändringar):
  ┌──────────────┐     ┌──────────────┐
  │ 1. sendReact │     │ 2. sendRecpt │  (parallella, oberoende)
  └──────────────┘     └──────────────┘

Fas 2 — Kontaktdata (grund för fas 3):
  ┌──────────────┐
  │ 3. listCntct │  (krävs av #6 och #7)
  └──────┬───────┘
         │ beroende
  ┌──────▼───────┐
  │ 7. updtCntct │  (utökar #3 med skrivning)
  └──────────────┘

Fas 3 — GUI-utbyggnad (oberoende sinsemellan):
  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
  │ 4. listDevic │  │ 5. updtConf  │  │ 6. updtGroup │
  └──────────────┘  └──────────────┘  └──────────────┘
  (parallella, oberoende)
```

### Berörda filer per funktion

| Fil | #1 | #2 | #3 | #4 | #5 | #6 | #7 |
|-----|----|----|----|----|----|----|-----|
| `config_db.py` (DEFAULT_CONFIG, TYPE_MAP) | ✓ | ✓ | — | — | ○ | — | — |
| `config.py` (konstanter, reload) | ✓ | ✓ | — | — | ○ | — | — |
| `processing.py` (hooks) | ✓ | ✓ | ✓ | — | — | — | — |
| `app_state.py` (contacts cache) | — | — | ✓ | — | — | — | ✓ |
| `signal_listener.py` (startup) | — | — | ✓ | — | — | — | — |
| `web_server.py` (routes) | — | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `web_handlers/config_handlers.py` | — | — | — | — | ✓ | — | — |
| `web_handlers/group_handlers.py` | — | — | — | — | — | ✓ | — |
| `web_handlers/account_handlers.py` | — | — | — | ✓ | — | — | — |
| `web_handlers/contact_handlers.py` (ny) | — | — | ✓ | — | — | — | ✓ |
| `templates/web/dashboard.html` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `templates/web/js/dashboard/` | ✓ | — | ✓ | ✓ | ✓ | ✓ | ✓ |

○ = valfritt (sparar kopia av signal-cli-inställningar)
