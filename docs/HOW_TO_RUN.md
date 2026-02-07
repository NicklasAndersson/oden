# Oden S7 Watcher

Oden S7 Watcher tar emot och bearbetar **Signal-meddelanden** till ditt Obsidian-valv.

## Snabbstart

Kör det skript som matchar ditt operativsystem. Skriptet hanterar **allt**: beroenden, Signal-konfiguration och start av applikationen.

### macOS

```bash
./run_mac.sh
```

### Linux (Ubuntu/Debian)

```bash
chmod +x ./run_linux.sh
./run_linux.sh
```

### Windows (PowerShell)

```powershell
.\run_windows.ps1
```

> **Tips:** Om du får ett fel om att skript inte får köras, kör först:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
> ```

### macOS: Oden.app

På macOS finns Oden även som `.app`-paket:

1. Ladda ner `.dmg` från [senaste releasen](https://github.com/NicklasAndersson/oden/releases)
2. Öppna DMG-filen och dra **Oden.app** till **Applications**
3. Kör `xattr -cr /Applications/Oden.app` i Terminal (krävs utan Apple-certifikat)
4. Dubbelklicka på Oden.app — setup-wizarden öppnas i webbläsaren

## Vad skriptet gör

1. **Kontrollerar beroenden** - Java 21+
2. **Installerar signal-cli** - Laddar ner automatiskt om det behövs
3. **Startar Oden** - Vid första start öppnas setup-wizarden i webbläsaren

## Setup-wizard

Vid första start öppnas en setup-wizard automatiskt i din webbläsare:

1. **Välj hemkatalog** - Var Oden ska lagra sin konfiguration
2. **Länka Signal-konto** - Skanna QR-kod med din telefon, eller registrera nytt nummer
3. **Välj vault-sökväg** - Peka på ditt Obsidian-valv
4. **Klart** - Oden startar och börjar ta emot meddelanden

All konfiguration sparas i en SQLite-databas (`config.db`). Ändringar kan göras i efterhand via Web GUI:ns konfigurationssida.

## Nästa gång

Kör samma skript igen — eller starta Oden.app. Det hoppar över steg som redan är klara och startar applikationen direkt.

## Funktioner

### Komplettera rapporter

- **Svara på ett meddelande** - Svaret läggs till i din senaste rapport (inom 30 min)
- **Skriv `++`** - Meddelanden som börjar med `++` läggs till i senaste rapporten

### System Tray

Oden visar en ikon i systemfältet (macOS/Linux/Windows) med knappar för:
- **Starta/Stoppa** signal-cli-processen
- **Öppna Web GUI** i webbläsaren
- **Avsluta** Oden helt

## Stoppa applikationen

Använd **Stoppa**-knappen i system tray, **Shutdown**-knappen i Web GUI, eller tryck `Ctrl+C` i terminalen.
