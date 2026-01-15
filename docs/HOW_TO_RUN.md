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

## Vad skriptet gör

1. **Kontrollerar beroenden** - Java 21+, qrencode (valfritt)
2. **Installerar signal-cli** - Laddar ner automatiskt om det behövs
3. **Konfigurerar Signal** - Länka befintligt konto eller registrera nytt nummer
4. **Skapar config.ini** - Frågar efter vault-sökväg och andra inställningar
5. **Startar Oden** - Applikationen körs tills du stoppar den med Ctrl+C

## Nästa gång

Kör samma skript igen! Det hoppar över steg som redan är klara och startar applikationen direkt.

## Funktioner

### Komplettera rapporter

- **Svara på ett meddelande** - Svaret läggs till i din senaste rapport (inom 30 min)
- **Skriv `++`** - Meddelanden som börjar med `++` läggs till i senaste rapporten

## Manuell konfiguration

Om du behöver ändra inställningar, redigera `config.ini`:

```ini
[Vault]
path = /sökväg/till/ditt/obsidian-valv

[Signal]
number = +46701234567

[Timezone]
timezone = Europe/Stockholm
```

## Stoppa applikationen

Tryck `Ctrl+C` i terminalen.
