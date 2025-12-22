# Flödesskiss för Oden

Det här dokumentet beskriver flödet för hur ett inkommande Signal-meddelande hanteras och arkiveras av applikationen.

```mermaid
sequenceDiagram
    participant Externt as Användare (Externt)
    participant Signal as signal-cli
    participant Watcher as s7_watcher.py
    participant Processor as processing.py
    participant Valv as Vault (Filsystem)

    Note over Externt, Valv: Flöde för ett vanligt meddelande

    Externt->>+Signal: Skickar meddelande (text/bilaga/plats)
    Signal->>+Watcher: Förmedlar meddelande (JSON via TCP)
    Watcher->>+Processor: Anropar process_message() med JSON-data
    
    Note over Processor: Behandlar meddelandet
    Processor-->>Signal: Hämtar ev. stor bilaga (getAttachment)
    Signal-->>-Processor: Returnerar bilaga (base64)
    
    Processor->>+Valv: Skriver/bifogar .md-fil med metadata
    Processor->>Valv: Sparar bilagor i undermapp
    
    deactivate Processor
    deactivate Watcher
    deactivate Signal
    
    Note over Externt, Valv: Flöde för ett kommando

    Externt->>+Signal: Skickar kommando (t.ex. "#help")
    Signal->>+Watcher: Förmedlar meddelande (JSON via TCP)
    Watcher->>+Processor: Anropar process_message() med JSON-data
    
    Note over Processor: Tolkar kommandot
    Processor->>Valv: Läser svarsfil (t.ex. /responses/help.md)
    Valv-->>-Processor: Returnerar innehåll
    
    Processor->>+Signal: Skickar svar (send-anrop via JSON-RPC)
    Signal->>-Externt: Levererar svar till användaren
    
    deactivate Processor
    deactivate Watcher
    deactivate Signal

```

## Detaljerad beskrivning

### Komponenter

*   **Externt (Utanför):** En person som skickar ett meddelande via Signal-appen till det nummer som applikationen bevakar.
*   **`signal-cli`:** Körs som en bakgrundsprocess (daemon) och hanterar den direkta kommunikationen med Signals servrar. Den tar emot meddelanden och exponerar ett lokalt JSON-RPC API över en TCP-socket. Den kan också ta emot anrop för att skicka meddelanden eller hämta data.
*   **`s7_watcher.py` (Watcher):** En Python-process som kontinuerligt är ansluten till `signal-cli`-daemonen. Dess enda syfte är att lyssna efter inkommande meddelanden, och när ett tas emot, skicka det vidare till `processing.py` för behandling.
*   **`processing.py` (Processor):** Applikationens kärna. Detta skript innehåller all logik för att tolka, formatera och agera på ett meddelande.
*   **Vault (Filsystem):** En mappstruktur (`/vault`) på datorn där meddelanden och deras bilagor sparas som Markdown-filer i ett [Obsidian](https://obsidian.md)-kompatibelt format.

### Flöde 1: Vanligt meddelande

1.  En användare skickar ett meddelande (som kan innehålla text, en bild, en fil eller en plats) till en grupp där boten är medlem.
2.  `signal-cli` tar emot meddelandet och skickar det som ett JSON-objekt till `s7_watcher.py`.
3.  `s7_watcher.py` tar emot JSON-objektet och anropar `process_message`-funktionen i `processing.py`.
4.  `processing.py` parsar meddelandet:
    *   Extraherar text, avsändare, grupp, tidsstämpel och eventuella bilagor.
    *   Om en bilaga är för stor för att ha skickats med direkt i JSON, görs ett anrop tillbaka till `signal-cli` för att hämta den.
    *   Textinnehållet analyseras för specifika mönster (definierade i `config.ini`) som automatiskt omvandlas till Obsidian-länkar (`[[länk]]`).
    *   En sökväg till en Markdown-fil bestäms baserat på gruppnamn och datum.
5.  Processorn sparar bilagor i en unik undermapp i valvet.
6.  Processorn skriver eller lägger till det formaterade innehållet (metadata, text, länkar till bilagor) i rätt `.md`-fil i valvet.

### Flöde 2: Kommando

1.  En användare skickar ett meddelande som börjar med `#`, t.ex. `#help` eller `#ok`.
2.  `signal-cli` och `s7_watcher.py` hanterar meddelandet precis som i flöde 1 och skickar det till `processing.py`.
3.  `processing.py` upptäcker att meddelandet är ett kommando.
4.  Processorn letar efter en fil med motsvarande namn i mappen `/responses` (t.ex. `/responses/help.md`).
5.  Om filen finns, läses dess innehåll in.
6.  Processorn gör ett `send`-anrop till `signal-cli`:s API med innehållet från svarsfilen.
7.  `signal-cli` skickar innehållet som ett vanligt Signal-meddelande tillbaka till gruppen som en respons.
