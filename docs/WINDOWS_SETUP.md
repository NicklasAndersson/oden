# Windows — Installationsguide

Den här guiden beskriver hur du installerar och kör Oden på Windows med hjälp av Docker Desktop.

> **Kort om Oden:** Oden tar emot Signal-meddelanden via `signal-cli` och sparar dem som Markdown-filer i ditt Obsidian-valv.

---

## Förutsättningar

| Programvara | Beskrivning | Länk |
|-------------|-------------|------|
| **Docker Desktop** | Container-runtime för Windows | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) |
| **Obsidian** | Markdown-editor för att läsa rapporter | [obsidian.md/download](https://obsidian.md/download) |
| **Signal Desktop** | För att administrera grupper (valfritt) | [signal.org/download](https://signal.org/download/) |

### Installera Docker Desktop

1. Ladda ner Docker Desktop från [docker.com](https://www.docker.com/products/docker-desktop/)
2. Kör installationsprogrammet och följ instruktionerna
3. Starta om datorn om det krävs
4. Starta Docker Desktop och vänta tills det visar **"Docker Desktop is running"**

> **Tips:** Docker Desktop kräver WSL 2 (Windows Subsystem for Linux). Installationsprogrammet erbjuder att installera det automatiskt. Om du stöter på problem, se [Microsofts WSL-guide](https://learn.microsoft.com/en-us/windows/wsl/install).

---

## Installation

### Alternativ A: Docker Compose (rekommenderat)

1. Skapa en ny mapp för Oden, till exempel `C:\oden`

2. Öppna **PowerShell** och kör:

```powershell
mkdir C:\oden
cd C:\oden
```

3. Ladda ner `docker-compose.yml`:

```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/NicklasAndersson/oden/main/docker-compose.yml" -OutFile "docker-compose.yml"
```

4. Skapa en mapp för ditt Obsidian-valv (om den inte redan finns):

```powershell
mkdir vault
```

5. Starta Oden:

```powershell
docker compose up -d
```

### Alternativ B: Docker Run

Om du föredrar att köra utan Docker Compose:

```powershell
docker run -d `
  --name oden `
  -p 8080:8080 `
  -v oden-data:/data `
  -v ${PWD}/vault:/vault `
  ghcr.io/nicklasandersson/oden:latest
```

---

## Volymer och sökvägar

Oden i Docker använder två volymer — en för konfiguration och en för rapporter. Sökvägarna i Odens webbgränssnitt är **containerns interna sökvägar** (t.ex. `/data`, `/vault`). Det är `volumes:`-sektionen i `docker-compose.yml` som bestämmer var dessa mappar faktiskt hamnar på din Windows-dator.

### Standardkonfiguration

```yaml
volumes:
  - oden-data:/data       # Config (config.db, signal-data) → namngiven Docker-volym
  - ./vault:/vault        # Rapporter → mappen "vault" bredvid docker-compose.yml
```

| Container-sökväg | Vad den innehåller | Var det hamnar på Windows (standard) |
|-------------------|--------------------|--------------------------------------|
| `/data` | Konfiguration (`config.db`), signal-cli-data, loggar | Namngiven Docker-volym `oden-data` (hanteras av Docker) |
| `/vault` | Markdown-rapporter organiserade per grupp | `.\vault` relativt till `docker-compose.yml` (t.ex. `C:\oden\vault`) |

### Anpassa sökvägar

Du kan ändra var data lagras på din Windows-dator genom att redigera `volumes:` i `docker-compose.yml`. Container-sökvägarna (`/data` och `/vault`) ska **inte** ändras — det är bara vänstersidan (host-sökvägen) du justerar.

**Exempel — lagra config i en specifik mapp istället för en Docker-volym:**

```yaml
volumes:
  - C:/oden-config:/data    # Config hamnar i C:\oden-config
  - ./vault:/vault
```

**Exempel — peka vault mot en befintlig Obsidian-mapp:**

```yaml
volumes:
  - oden-data:/data
  - D:/Obsidian/Rapporter:/vault    # Rapporter sparas direkt i D:\Obsidian\Rapporter
```

**Exempel — båda på egna platser:**

```yaml
volumes:
  - C:/oden-config:/data
  - D:/Obsidian/Rapporter:/vault
```

> **Obs:** Använd framåtsnedstreck (`/`) i sökvägar i `docker-compose.yml`, även på Windows. Docker Desktop hanterar konverteringen automatiskt.

Efter att du ändrat `docker-compose.yml`, starta om containern:

```powershell
docker compose down
docker compose up -d
```

---

## Konfiguration

Efter att containern har startats:

1. Öppna webbläsaren och gå till **http://localhost:8080** — Oden startar direkt i dashboarden.
2. **Obsidian**-fliken: valvet är redan `/vault` (containerns interna sökväg, mappas till din Windows-mapp via `volumes:` i `docker-compose.yml`). Klicka gärna *Installera Obsidian-inställningar* (grundinställningar och Map View).
3. **Signal → Konton**: *Visa QR-kod* och skanna med Signal-appen på telefonen (*Inställningar → Länkade enheter → Lägg till enhet*).
4. Starta om containern (`docker compose restart`) så börjar Oden lyssna efter meddelanden.

> **Viktigt:** Ändra inte `/data` och `/vault` inne i Oden — använd `volumes:` i `docker-compose.yml` för att styra var filerna hamnar på din Windows-dator.

> **Viktigt:** Använd inte ditt privata Signal-nummer! Skaffa ett dedikerat nummer för Oden (t.ex. ett billigt kontantkort).

---

## Öppna rapporter i Obsidian

1. Starta **Obsidian**
2. Välj **"Open folder as vault"** och peka på din `vault`-mapp (t.ex. `C:\oden\vault`)
3. Rapporter från Signal dyker upp som Markdown-filer organiserade per grupp

---

## Hantera Oden

### Webbgränssnitt

Odens dashboard nås på **http://localhost:8080** och ger dig tillgång till:

- Konfiguration (visa och redigera)
- Live-loggar
- Grupphantering (ignorera, whitelist, gå med via inbjudningslänk)
- Template-editor med förhandsvisning
- Signal-kontohantering

### Docker-kommandon

Kör dessa i **PowerShell** från mappen där `docker-compose.yml` ligger:

```powershell
# Visa status
docker compose ps

# Visa loggar
docker compose logs -f

# Stoppa Oden
docker compose stop

# Starta igen
docker compose up -d

# Uppdatera till senaste version
docker compose pull
docker compose up -d

# Ta bort containern (data bevaras i volymen)
docker compose down
```

---

## Autostart vid inloggning

Docker Desktop kan konfigureras att starta automatiskt:

1. Öppna **Docker Desktop → Settings → General**
2. Bocka i **"Start Docker Desktop when you sign in to Windows"**
3. Under **Settings → Resources → Advanced**, bocka i **"Start Docker Desktop when you sign in"**

Containern startar automatiskt tack vare `restart: unless-stopped` i `docker-compose.yml`.

---

## Felsökning

### Docker Desktop startar inte

- Kontrollera att **WSL 2** är installerat: öppna PowerShell och kör `wsl --status`
- Om WSL saknas: `wsl --install` och starta om datorn
- Kontrollera att **virtualisering** är aktiverat i BIOS/UEFI

### Kan inte nå http://localhost:8080

- Kontrollera att containern körs: `docker compose ps`
- Kontrollera loggarna: `docker compose logs`
- Se till att port 8080 inte används av ett annat program

### QR-kod visas inte vid länkning

- Vänta några sekunder — signal-cli behöver tid att starta (Java-baserat)
- Kontrollera containerns loggar: `docker compose logs -f`
- Prova att starta om containern: `docker compose restart`

### Meddelanden sparas inte

- Kontrollera att `vault`-mappen är korrekt mappad: `docker compose exec oden ls /vault`
- Kontrollera att Signal-kontot är aktivt i dashboard-vyn
- Se live-loggarna i webbgränssnittet för felmeddelanden

---

## Avinstallation

```powershell
# Stoppa och ta bort containern
docker compose down

# Ta bort data-volymen (raderar konfiguration och signal-data)
docker volume rm oden_oden-data

# Ta bort lokala filer
cd ..
Remove-Item -Recurse -Force C:\oden
```

> **Obs:** Ditt Obsidian-valv (`vault`-mappen) raderas bara om det ligger i `C:\oden\vault`. Om du har det på en annan plats bevaras det.

---

## Rekommenderad programvara

| Programvara | Beskrivning | Länk |
|-------------|-------------|------|
| **Signal Desktop** | Administrera grupper och se meddelanden | [signal.org/download](https://signal.org/download/) |
| **Obsidian** | Markdown-editor för rapporter | [obsidian.md/download](https://obsidian.md/download) |
| **Obsidian Map View** | Visa positioner på en karta i Obsidian | [GitHub](https://github.com/esm7/obsidian-map-view) |
| **Syncthing** | Synkronisera valvet mellan enheter | [syncthing.net/downloads](https://syncthing.net/downloads/) |
