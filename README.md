# Oden S7 Watcher

## For Users (Recommended Usage)

If you simply want to run the application, you should download the latest release, not clone this repository.

1.  Go to the **[Releases Page](../../releases)**.
2.  Download the `s7_watcher-release.zip` file from the most recent release.
3.  Unzip the package and follow the instructions in the `HOW_TO_RUN.md` file you will find inside.

---

## For Developers

This README is for developers who have cloned the repository to build from source or contribute. If you are an end-user, please see the section above.

For instructions on running the pre-packaged release, please see `HOW_TO_RUN.md`.

## Installation (macOS)

For a quick setup on macOS, run the interactive installation script. This will help you install dependencies and link your Signal account.

```bash
./install_mac.sh
```

## Manual Operation

These steps describe how to run the components manually after setup.

### Starta signal-cli

```bash
./signal-cli-0.13.22/bin/signal-cli -u <ditt-nummer> daemon --tcp 127.0.0.1:7583
```

### Kör watcher

```bash
# På macOS/Linux
./s7_watcher

# På Windows
.\s7_watcher.exe
```

## Konfiguration

Redigera `config.ini` enligt HOW_TO_RUN.md. Se till att tidszon och regex är korrekt inställda för din miljö.

## Flödesdiagram

[Flödesdiagram för applikationen](Flow.md)

