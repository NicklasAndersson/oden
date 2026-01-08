# Oden S7 Watcher

![logotyp](images/logo_small.jpg)

## För Utvecklare

Denna README är för utvecklare som har klonat repot för att bygga från källkod eller bidra.

För instruktioner om hur man kör en förpaketerad release, se [docs/HOW_TO_RUN.md](./docs/HOW_TO_RUN.md).

### Projektstruktur

```text
oden/
├── oden/           # Python-paket med källkod
├── tests/          # Enhetstester
├── scripts/        # Installationsskript (macOS/Windows)
├── docs/           # Dokumentation
├── responses/      # Svarsmallar för kommandon
└── images/         # Bilder
```

### Installation för utveckling

```bash
# Installera paketet i utvecklingsläge
pip install -e .

# Kör tester
python -m unittest discover -s tests

# Kör applikationen
python -m oden
```

### Funktioner

Det finns två sätt att lägga till information i en rapport som du nyligen har skickat:

1. **Svara på ett meddelande:** Om du svarar på ett meddelande i gruppen (oavsett vem som skrev originalet), kommer texten i ditt svar att läggas till i din senast skapade rapport, förutsatt att den inte är äldre än 30 minuter.

2. **Använd kommandot `++`:** Om du skickar ett meddelande som börjar med `++`, kommer dess innehåll att läggas till i det senaste meddelandet du skickade (även här inom 30 minuter).

Detta gör det möjligt att enkelt lägga till fler detaljer, korrigeringar eller bilagor i en rapport i efterhand.

## Konfiguration

Redigera `config.ini` enligt [docs/HOW_TO_RUN.md](./docs/HOW_TO_RUN.md). Se till att tidszon, regex och Signal-relaterade inställningar är korrekt inställda för din miljö.

## Flödesdiagram

[Flödesdiagram för applikationen](./docs/Flow.md)
