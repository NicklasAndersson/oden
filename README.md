# Oden S7 Watcher

## För Användare (Rekommenderad Användning)

Om du bara vill köra applikationen bör du ladda ner den senaste releasen, inte klona detta repo.

1. Gå till **[Releases-sidan](../../releases)**.
2. Ladda ner `s7_watcher-release.zip`-filen från den senaste releasen.
3. Packa upp paketet och följ instruktionerna i `HOW_TO_RUN.md`-filen som du hittar inuti.

---

## För Utvecklare

Denna README är för utvecklare som har klonat repot för att bygga från källkod eller bidra. Om du är slutanvändare, se avsnittet ovan.

För instruktioner om hur man kör den förpaketerade releasen, se `HOW_TO_RUN.md`.

## Installation (macOS)

För en snabb installation på macOS, kör det interaktiva installationsskriptet. Det hjälper dig att installera beroenden och länka ditt Signal-konto.

```bash
./install_mac.sh
```

## Manuell Hantering

Dessa steg beskriver hur man kör komponenterna manuellt efter installation.

### Starta signal-cli

```bash
./signal-cli-0.13.22/bin/signal-cli -u <ditt-nummer> daemon --tcp 127.0.0.1:7583
```

### Kör watcher

```bash
python3 s7_watcher.py
```

## Konfiguration

Redigera `config.ini` enligt HOW_TO_RUN.md. Se till att tidszon och regex är korrekt inställda för din miljö.

## Flödesdiagram

[Flödesdiagram för applikationen](Flow.md)
