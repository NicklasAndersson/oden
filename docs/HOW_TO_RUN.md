> [!NOTE]
> Denna guide är avsedd för att köra en **paketerad release** av Oden. Om du är en utvecklare som arbetar med källkoden, vänligen se `README.md` i repots rot.

# Oden S7 Watcher

Oden S7 Watcher är ett verktyg som tar emot och bearbetar **Signal-meddelanden** baserat på din konfiguration.

## Installation och Inställningar

Följ dessa steg för att få applikationen att köra.

### 1. Kör Installationsskriptet (macOS)

Om du använder macOS är det enklaste sättet att komma igång att använda det interaktiva installationsskriptet.

1. Öppna en terminal.
2. Navigera till mappen där du packade upp release-filen.
3. Kör skriptet:

    ```bash
    ./install_mac.sh
    ```

Detta skript kommer att kontrollera beroenden (som Java) och guida dig genom att ansluta ditt Signal-konto.

### 2. Manuell Installation (Windows)

Tyvärr finns ett automatiserat installationsskript för Windows ännu inte tillgängligt. Vi ber om ursäkt för besväret. Windows-användare måste installera `signal-cli` manuellt. Vänligen se den officiella `signal-cli`-dokumentationen för instruktioner om hur man antingen [registrerar ett nytt nummer](https://github.com/AsamK/signal-cli/wiki/Register-a-new-signal-account) eller [länkar en befintlig enhet](https://github.com/AsamK/signal-cli/wiki/Link-a-second-device).

### 3. Redigera `config.ini`

Efter att ha konfigurerat Signal måste du konfigurera Oden. I samma mapp som den körbara filen hittar du en fil med namnet `config.ini`. Redigera värdena i den här filen för att matcha din installation. Se avsnittet **Konfiguration** nedan för detaljer.

### 4. Köra Applikationen

När din installation och konfiguration är klar kan du köra applikationen. Se avsnittet **Köra Applikationen** nedan för instruktioner.

## Funktioner

### Komplettera rapporter

Det finns två sätt att lägga till information i en rapport som du nyligen har skickat:

1.  **Svara på ett meddelande:** Om du svarar på ett meddelande i gruppen (oavsett vem som skrev originalet), kommer texten i ditt svar att läggas till i din senast skapade rapport, förutsatt att den inte är äldre än 30 minuter.

2.  **Använd kommandot `++`:** Om du skickar ett meddelande som börjar med `++`, kommer dess innehåll att läggas till i det senaste meddelandet du skickade (även här inom 30 minuter).

Detta gör det möjligt att enkelt lägga till fler detaljer, korrigeringar eller bilagor i en rapport i efterhand.

## Konfiguration (`config.ini`)

Applikationen kräver att en `config.ini`-fil finns i samma mapp. Denna fil innehåller de nödvändiga inställningarna för att applikationen ska fungera korrekt.

### Mall

Din `config.ini` bör se ut så här:

```ini
[Vault]
path = ./vault

[Signal]
# Ditt Signal-telefonnummer (t.ex. +46701234567)
number = YOUR_SIGNAL_NUMBER
# Sökväg till signal-cli-binären (valfritt, t.ex. /usr/local/bin/signal-cli)
# signal_cli_path = 
# Sätt till 'true' om du själv hanterar signal-cli-processen (valfritt, standard är 'false')
# unmanaged_signal_cli = false
# Host och port för signal-cli RPC (valfritt, standard är 127.0.0.1 och 7583)
# host = 127.0.0.1
# port = 7583

[Regex]
# Lista med regex som används för att automatiskt länka [[]] i markdown-filer
# Registreringsnummer (t.ex. ABC12D)
registration_number = [A-Z,a-z]{3}[0-9]{2}[A-Z,a-z,0-9]{1}

[Timezone]
# Tidszon för tidsstämplar (t.ex. Europe/Stockholm för Sverige)
timezone = Europe/Stockholm
```

### Förklaring av Inställningar

- `[Vault]`
  - **path**: Den fullständiga sökvägen till rotmappen för ditt Obsidian-valv.

- `[Signal]`
  - **number**: Ditt registrerade Signal-telefonnummer, inklusive landskod (t.ex. `+46701234567`).
  - **signal_cli_path**: (Valfritt) Den fullständiga sökvägen till din `signal-cli` körbara fil. Använd detta om `signal-cli` inte finns i din PATH eller i den medföljande katalogen.
  - **unmanaged_signal_cli**: (Valfritt, standard `false`) Om `true`, kommer s7_watcher *inte* att försöka starta eller stoppa `signal-cli` daemonen. Du förväntas hantera `signal-cli` daemonen själv.
  - **host**: (Valfritt, standard `127.0.0.1`) IP-adressen eller värdnamnet där `signal-cli` RPC-servern lyssnar.
  - **port**: (Valfritt, standard `7583`) Portnumret där `signal-cli` RPC-servern lyssnar.

- `[Regex]`
  - Lista över regex-mönster som används för att automatiskt skapa `[[...]]`-länkar i markdown-filer.
  - **registration_number**: Mönster för svenska registreringsnummer (t.ex. ABC12D).
  - Du kan lägga till fler mönster genom att lägga till nya rader med `mönsternamn = regex_mönster`.

- `[Timezone]`
  - **timezone**: Tidszonen för tidsstämplar. Använd standardnamn för tidszoner som `Europe/Stockholm` för Sverige, `Europe/London` för Storbritannien, etc.

## Köra Applikationen

När din körbara fil är på plats och `config.ini` är konfigurerad kan du köra applikationen.

### På macOS eller Linux

1. **Gör filen körbar:**

   ```bash
   chmod +x ./s7_watcher
   ```

2. **Kör watchern:**

   - **Om `unmanaged_signal_cli` är `false` (standard, s7_watcher hanterar `signal-cli`):**
     ```bash
     ./s7_watcher
     ```
   - **Om `unmanaged_signal_cli` är `true` (du hanterar `signal-cli` själv):**
     Se till att din `signal-cli` daemon körs i förväg:
     ```bash
     /path/to/signal-cli-executable -u YOUR_SIGNAL_NUMBER daemon --tcp YOUR_HOST:YOUR_PORT &
     ```
     Byt ut `/path/to/signal-cli-executable`, `YOUR_SIGNAL_NUMBER`, `YOUR_HOST`, och `YOUR_PORT` med dina faktiska värden. Sedan kan du starta s7_watcher:
     ```bash
     ./s7_watcher
     ```

### På Windows

Kör den körbara filen direkt från Command Prompt eller PowerShell.

```powershell
.\s7_watcher.exe
```
