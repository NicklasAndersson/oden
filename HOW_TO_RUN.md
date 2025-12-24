# Oden S7 Watcher

Oden S7 Watcher är ett verktyg som övervakar en mapp för nya filer och bearbetar dem baserat på din konfiguration.

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

### 4. Kör Applikationen

När din installation och konfiguration är klar kan du köra applikationen. Se avsnittet **Köra Applikationen** nedan för instruktioner.

## Funktioner

### Komplettera rapporter

Det finns två sätt att lägga till information i en rapport som du nyligen har skickat:

1.  **Svara på ditt eget meddelande:** Om du svarar på ett av dina egna meddelanden kommer texten i ditt svar att läggas till i den ursprungliga filen, förutsatt att det ursprungliga meddelandet inte är äldre än 30 minuter.

2.  **Använd kommandot `++`:** Om du skickar ett meddelande som börjar med `++`, kommer dess innehåll att läggas till i det senaste meddelandet du skickade (även här inom 30 minuter).

Detta gör det möjligt att enkelt lägga till fler detaljer, korrigeringar eller bilagor i en rapport i efterhand.

## Konfiguration (`config.ini`)

Applikationen kräver att en `config.ini`-fil finns i samma mapp. Denna fil innehåller de nödvändiga inställningarna för att applikationen ska fungera korrekt.

### Mall

Din `config.ini` bör se ut så här:

```ini
[Vault]
path = ./vault

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

   ```bash
   ./s7_watcher
   ```

### På Windows

Kör den körbara filen direkt från Command Prompt eller PowerShell.

```powershell
.\s7_watcher.exe
```
