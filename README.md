# Oden S7 Watcher

![logotyp](images/logo_small.jpg)

## För Användare (Rekommenderad Användning)

Om du bara vill köra applikationen bör du ladda ner den senaste releasen, inte klona detta repo.

1. Gå till **[Releases-sidan](../../releases)**.
2. Ladda ner `s7_watcher-release.zip`-filen från den senaste releasen.
3. Packa upp paketet och följ instruktionerna i `docs/HOW_TO_RUN.md`-filen som du hittar inuti.

---

## För Utvecklare

Denna README är för utvecklare som har klonat repot för att bygga från källkod eller bidra. Om du är slutanvändare, se avsnittet ovan.

För instruktioner om hur man kör den förpaketerade releasen, se `docs/HOW_TO_RUN.md`.

### Funktioner

Det finns två sätt att lägga till information i en rapport som du nyligen har skickat:

1. **Svara på ditt eget meddelande:** Om du svarar på ett av dina egna meddelanden kommer texten i ditt svar att läggas till i den ursprungliga filen, förutsatt att det ursprungliga meddelandet inte är äldre än 30 minuter.

2. **Använd kommandot `++`:** Om du skickar ett meddelande som börjar med `++`, kommer dess innehåll att läggas till i det senaste meddelandet du skickade (även här inom 30 minuter).

Detta gör det möjligt att enkelt lägga till fler detaljer, korrigeringar eller bilagor i en rapport i efterhand.

## Konfiguration

Redigera `config.ini` enligt `docs/HOW_TO_RUN.md`. Se till att tidszon, regex och Signal-relaterade inställningar är korrekt inställda för din miljö.

## Flödesdiagram

[Flödesdiagram för applikationen](docs/Flow.md)
