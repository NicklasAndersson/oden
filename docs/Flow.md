# Flödesskiss för Oden

Det här dokumentet beskriver flödet för hur ett inkommande Signal-meddelande hanteras och arkiveras av applikationen.

```mermaid
sequenceDiagram
    participant Användare
    participant signal-cli
    participant oden/s7_watcher.py as Watcher
    participant oden/processing.py as Processor
    participant Vault

    Användare->>signal-cli: Skickar meddelande
    signal-cli->>Watcher: Förmedlar meddelande (JSON)
    Watcher->>Processor: process_message()

    activate Processor

    alt Meddelande börjar med --
        Processor-->>Watcher: Ignorerar meddelandet
    
    else Meddelande är ett svar eller börjar med ++
        Processor->>Vault: Finns en nylig fil från avsändaren?
        
        alt Ja (filen är < 30 min gammal)
            Vault-->>Processor: Ja, här är sökvägen
            opt Innehåller bilaga
                Processor->>signal-cli: Hämta bilaga
                signal-cli-->>Processor: Returnerar bilaga
                Processor->>Vault: Sparar bilaga
            end
            Processor->>Vault: Lägger till text i befintlig fil
        
        else Nej (ingen nylig fil)
            Note over Processor: Hanteras som ett vanligt meddelande
            opt Innehåller bilaga
                Processor->>signal-cli: Hämta bilaga
                signal-cli-->>Processor: Returnerar bilaga
                Processor->>Vault: Sparar bilaga
            end
            Processor->>Vault: Skapar ny .md-fil
        end

    else Meddelande börjar med # (kommando)
        Processor->>Vault: Läser svarsfil från /responses
        Vault-->>Processor: Returnerar filinnehåll
        Processor->>signal-cli: Skickar svar till gruppen
        signal-cli->>Användare: Visar svar
    
    else Vanligt meddelande
        opt Innehåller bilaga
            Processor->>signal-cli: Hämta bilaga
            signal-cli-->>Processor: Returnerar bilaga
            Processor->>Vault: Sparar bilaga i undermapp
        end
        Processor->>Vault: Skapar ny .md-fil med metadata och text
    end
    deactivate Processor
```

## Detaljerad beskrivning

### Komponenter

* **Externt (Utanför):** En person som skickar ett meddelande via Signal-appen till det nummer som applikationen bevakar.
* **System Tray (`tray.py`):** En ikon i systemfältet (macOS/Linux/Windows) via pystray. Ger knappar för att starta/stoppa signal-cli, öppna Web GUI i webbläsaren, och avsluta Oden. Vid första start öppnas istället en **setup-wizard** i webbläsaren som guidar genom konfigurationen (välja hemkatalog, länka Signal-konto via QR-kod, välja vault-sökväg).
* **`signal-cli`:** Körs som en bakgrundsprocess (daemon) och hanterar den direkta kommunikationen med Signals servrar. Den tar emot meddelanden och exponerar ett lokalt JSON-RPC API över en TCP-socket. Den kan också ta emot anrop för att skicka meddelanden eller hämta data.
* **`s7_watcher.py` (Watcher):** Applikationens huvudprocess. Startar tray-ikonen, hanterar signal-cli-processen, Web GUI, TCP-anslutningen och skickar meddelanden vidare till `processing.py` för behandling.
* **`processing.py` (Processor):** Applikationens kärna. Innehåller all logik för att tolka, formatera och agera på ett meddelande. Använder Jinja2-mallar (via `template_loader.py`) för att formatera rapporter.
* **`config_db.py` (Konfiguration):** All konfiguration lagras i en SQLite-databas (`config.db`). Modulen `config.py` läser in värden från databasen och exponerar dem som modulglobala konstanter.
* **Vault (Filsystem):** En mappstruktur (`/vault`) på datorn där meddelanden och deras bilagor sparas som Markdown-filer i ett [Obsidian](https://obsidian.md)-kompatibelt format.

### Flöde 1: Vanligt meddelande

1. En användare skickar ett meddelande (som kan innehålla text, en bild, en fil eller en plats) till en grupp där boten är medlem.
2. `signal-cli` tar emot meddelandet och skickar det som ett JSON-objekt till `s7_watcher.py`.
3. `s7_watcher.py` tar emot JSON-objektet och anropar `process_message`-funktionen i `processing.py`.
4. `processing.py` parsar meddelandet:
   * Extraherar text, avsändare, grupp, tidsstämpel och eventuella bilagor.
   * Om en bilaga är för stor för att ha skickats med direkt i JSON, görs ett anrop tillbaka till `signal-cli` för att hämta den.
   * Textinnehållet analyseras för specifika mönster (definierade i konfigurationsdatabasen) som automatiskt omvandlas till Obsidian-länkar (`[[länk]]`). Platslänkar (Google Maps, Apple Maps, OSM) extraheras till geo-koordinater.
   * En sökväg till en Markdown-fil bestäms baserat på gruppnamn och datum.
5. Processorn sparar bilagor i en unik undermapp i valvet.
6. Processorn skriver eller lägger till det formaterade innehållet (metadata, text, länkar till bilagor) i rätt `.md`-fil i valvet.

### Flöde 2: Kommando

1. En användare skickar ett meddelande som börjar med `#`, t.ex. `#help` eller `#ok`.
2. `signal-cli` och `s7_watcher.py` hanterar meddelandet precis som i flöde 1 och skickar det till `processing.py`.
3. `processing.py` upptäcker att meddelandet är ett kommando.
4. Processorn letar efter en fil med motsvarande namn i mappen `/responses` (t.ex. `/responses/help.md`).
5. Om filen finns, läses dess innehåll in.
6. Processorn gör ett `send`-anrop till `signal-cli`:s API med innehållet från svarsfilen.
7. `signal-cli` skickar innehållet som ett vanligt Signal-meddelande tillbaka till gruppen som en respons.

### Flöde 3: Särskilda Meddelanden

Vissa meddelanden som börjar med specifika prefix hanteras på ett unikt sätt.

*   **Svara på meddelande:**
    1. En användare svarar på ett meddelande i gruppen (oavsett vem som skrev originalet).
    2. Om originalmeddelandet är mindre än 30 minuter gammalt, tolkar `processing.py` detta som en signal att lägga till i en befintlig rapport.
    3. Systemet letar efter den senaste filen som skapats av *svararen* (den som skriver det nya meddelandet) och lägger till det nya innehållet där.

*   **Lägg till i föregående (`++`):**
    1. En användare skickar ett meddelande som börjar med `++`. Detta fungerar som ett alternativ till att svara, och letar också efter den senaste filen från avsändaren inom 30 minuter att lägga till i.
    2. Om ingen nylig fil hittas, behandlas meddelandet som ett vanligt meddelande (Flöde 1), men utan `++`-prefixet.

*   **Ignorera meddelande (`--`):**
    1. En användare skickar ett meddelande som börjar med `--`.
    2. `processing.py` identifierar prefixet och avbryter omedelbart all vidare bearbetning.
    3. Meddelandet ignoreras helt och sparas inte i valvet. Detta är användbart för informella kommentarer eller sidoanteckningar i en grupp som inte ska arkiveras.
