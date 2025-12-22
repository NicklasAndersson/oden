# Oden S7 Watcher

## Starta signal-cli

```bash
./signal-cli-0.13.22/bin/signal-cli -u <ditt-nummer> daemon --tcp 127.0.0.1:7583
```

## Kör watcher

```bash
python3 s7_watcher.py
```

## Konfiguration

Redigera `config.ini` enligt HOW_TO_RUN.md. Se till att tidszon och regex är korrekt inställda för din miljö.

## Flödesdiagram

[Flödesdiagram för applikationen](Flow.md)

