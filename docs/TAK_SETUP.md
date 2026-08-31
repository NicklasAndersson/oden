# TAK-integration – operatörsguide

Kopplar Oden till en befintlig TAK Server så att 7S-rapporter med position blir
CoT-markörer, och (valfritt) inkommande CoT blir `TAK-OBSERVATION`-noter i valvet.

Designen finns i [PLAN_TAK.md](PLAN_TAK.md). Den här guiden är för driftsättning.
Verifierad mot TAK Server 5.7-RELEASE-8.

## Förutsättningar

- En TAK Server som körs någon annanstans, och en **TAK-admin** som kan ge dig
  klientåtkomst.
- TAK-stödet ingår i DMG/Windows/Docker-byggena. Kör du från källkod:
  `pip install "oden[tak]"` (drar in `pytak` + `cryptography`).
- Utgående nätåtkomst från Oden-värden till serverns CoT-port (normalt TCP
  **8089**). Inga inkommande portar behövs.
- **NTP aktiverat** på Oden-värden. CoT-tider är i UTC; fel klocka ger markörer
  som blir "stale" direkt eller hamnar i framtiden.

## Steg 1 – Skaffa klientidentitet

Fråga TAK-admin om **ett av** följande (enklast först):

1. **Data package (`.zip`)** – samma fil som laddas in i ATAK/WinTAK. Innehåller
   serveradress, server-CA och klientcert. Oden packar upp den själv.
2. **Enrollment-konto** – användarnamn + lösenord. Oden hämtar ett klientcert
   från servern (port 8446) vid start.
3. **Lösa filer** – klientcertifikat (`.p12` eller PEM) + lösenord + serverns
   CA-cert (PEM).

Lägg filerna där bara Oden-användaren kan läsa dem:

```bash
mkdir -p ~/.config/oden/tak && chmod 700 ~/.config/oden/tak
cp ~/Downloads/mitt-tak-paket.zip ~/.config/oden/tak/
chmod 600 ~/.config/oden/tak/*
```

## Steg 2 – Konfigurera

Öppna web-GUI:t → fliken **TAK**. Fyll i formuläret och spara — Oden återansluter
direkt med de nya värdena och statusraden visar om det gick.

Har du en data package: klicka **Välj fil…** vid `pref_package`. Zip:en laddas
upp till `ODEN_HOME/tak/` (rättigheter `0600`) och sökvägen fylls i automatiskt.
Du kan också skriva sökvägen direkt om filen redan ligger på Oden-värden.

Alternativt från skript (inställningarna lagras som `tak_settings` i config-db):

```python
from pathlib import Path
from oden import config as cfg
from oden.config_db import set_config_value

set_config_value(
    cfg.CONFIG_DB,
    "tak_settings",
    {
        "enabled": True,
        "pref_package": str(Path.home() / ".config/oden/tak/mitt-tak-paket.zip"),
        "callsign": "ODEN",
    },
)
```

### Inställningar

| Nyckel | Default | Betydelse |
|---|---|---|
| `enabled` | `false` | Slår på TAK-integrationen |
| **Anslutning – välj EN väg** | | |
| `pref_package` | – | Sökväg till data-package-`.zip`. Fyller själv i URL, cert, nyckel och CA |
| `cot_url` | – | `tls://host:8089` (mTLS) eller `tcp://host:8087` (plain, betrott nät) |
| `enroll_username` | – | Enrollment: användarnamn. Lösenord läses ur env-var enligt `enroll_password_env` |
| `tls_client_cert` | – | `.p12` eller PEM (lösa filer). Lösenord ur env-var enligt `tls_client_password_env` |
| `tls_client_key` | – | Separat PEM-nyckel om certet saknar den |
| `tls_ca_cert` | – | Serverns CA (PEM). Behövs inte med `pref_package` |
| **TLS** | | |
| `tls_client_password_env` | `ODEN_TAK_CERT_PASSWORD` | Env-var som certlösenordet läses ur |
| `enroll_password_env` | `ODEN_TAK_ENROLL_PASSWORD` | Env-var som enrollment-lösenordet läses ur |
| `tls_verify` | `true` | CA-verifiering av servern. `false` bara i labb |
| `tls_check_hostname` | `false` | Kräv att cert-namnet matchar adressen. TAK-cert matchar sällan DNS-namnet – lämna av |
| **Utgående markörer** | | |
| `callsign` | `ODEN` | Vår identitet på servern |
| `cot_stale_seconds` | `3600` | Hur länge en markör är giltig |
| `cot_archive` | `true` | Sätter `<archive/>` så markören överlever att Oden kopplar ner |
| **Inkommande CoT** | | |
| `inbound_enabled` | `false` | Ta emot CoT och skapa `TAK-OBSERVATION`-noter |
| `inbound_types` | `a-h-*, a-u-*, b-a-*` | CoT-typer att släppa in (`*` som suffix). Inte `a-f-*` = ingen egen lägesrapportering |
| `inbound_callsign_allow` / `_deny` | tom | Vitlista / svartlista på callsign |
| `inbound_min_move_m` | `100` | Känd enhet som rört sig mindre → ingen ny not |
| `inbound_max_per_minute` | `60` | Hårt tak; resten loggas och släpps |
| `inbound_group_name` | `TAK Inkommande` | Gruppnamn noterna hamnar under |

Lösenord sätts som miljövariabel, aldrig i config-db eller GUI:

```bash
export ODEN_TAK_CERT_PASSWORD='...'      # eller ODEN_TAK_ENROLL_PASSWORD
```

macOS-app / systemd: lägg variabeln i launchd/unit-miljön.

### Server-CA och cert-namn

En TAK Server signerar sina egna certifikat:

- `pref_package` innehåller serverns `truststore-root` – inget mer behövs.
- Lösa filer utan `tls_ca_cert` → `self-signed certificate in certificate chain`.
  Exportera CA:t från TAK-admin/CloudTAK, eller `tls_verify = false` i labb.
- Serverns cert-namn är ofta inte DNS-namnet du ringer →
  `Hostname mismatch`. `tls_check_hostname` är av som standard; CA-koll kvar på.

### Inkommande CoT – noter i valvet

En not får rubriken `TAK-OBSERVATION` (medvetet *inte* `… RAPPORT`, så den inte
studsar tillbaka till TAK) i gruppen `TAK Inkommande`. Noterna passerar
**gruppfiltret** som allt annat – kör du whitelist-läge måste `TAK Inkommande`
finnas med i listan.

Filtren är staplade billigast först: typ → callsign → eko-vakt (`ODEN.*`) → dedup
per uid → tak per minut. Börja snävt och vidga; servern pushar hela lägesbilden
till varje ansluten klient.

## Steg 3 – Testa lokalt (valfritt)

Innan skarp server, kör [`taky`](https://pypi.org/project/taky/) (ren Python):

```bash
pipx install taky
taky_setup            # genererar CA + servercert
takyd                 # lyssnar på :8089
```

FreeTAKServer istället? Sätt `FTS_COMPAT=1` i miljön.

## Steg 4 – Starta och verifiera

1. Starta Oden. Loggen visar `TAK-bryggan startad (...)`.
2. Web-GUI → **TAK**: status 🟢 **Ansluten**. Med `pref_package` visas ingen
   cert-utgång (certet ligger i zip:en); med `tls_client_cert` visas den med
   varning < 30 dygn.
3. Ange en MGRS, klicka **Skicka testmarkör** → `ODEN.TEST.DDHHMM` ska synas i
   CloudTAK/ATAK. Terminalvariant: `python scripts/tak_send_test.py 34VCM7934926095`.
4. Skicka en riktig `7S RAPPORT` med MGRS i `Ställe` i din Signal-grupp:
   - markdown-noten skapas i valvet som vanligt, **och**
   - en markör `7S <TNR>` dyker upp på TAK-kartan.
5. (Om `inbound_enabled`) Skapa en markör i ATAK → en `TAK-OBSERVATION`-not ska
   dyka upp i Odens meddelandevy under `TAK Inkommande`.

## Felsökning

| Symptom | Trolig orsak |
|---|---|
| `self-signed certificate in certificate chain` | `tls_ca_cert` saknas/fel. Använd `pref_package` eller serverns `truststore-root.pem` |
| `Hostname mismatch, certificate is not valid for ...` | Serverns cert-namn ≠ adressen. `tls_check_hostname` ska vara av |
| `pytak saknas` i loggen | `pip install "oden[tak]"` |
| Ansluter men inget syns i ATAK | Markören redan stale, eller fel klocka. Kolla `cot_stale_seconds` + NTP |
| Markör försvinner efter en stund | `cot_archive = false` och Oden tappade anslutningen |
| Markör i havet (0,0) | MGRS i `Ställe` gick inte att tolka |
| Dubbla markörer för samma rapport | uid-härledning matchar inte mellan original och `++` – buggrapport |
| Översvämmas av inkommande noter | `inbound_types` för brett, eller höj `inbound_min_move_m` |
| Markörer syns för dig men inte andra | Servern kräver data marking / mission – prata med TAK-admin |

## Säkerhet

- Cert-filer och data package: `chmod 600`, ägs av Oden-användaren.
- Cert-/enrollment-lösenord i miljövariabel eller OS-nyckelring – aldrig i
  config-db (den visas i GUI:t).
- `tls_verify = false` bara i labb.
- Inkommande CoT behandlas som osäker indata (callsign/uid saneras, koordinater
  klampas, remarks trunkeras). Slå på `inbound_enabled` bara på ett nät du litar på.
- Klientcert går ut – GUI:t varnar < 30 dygn innan (gäller `tls_client_cert`;
  med `pref_package` håll koll via TAK-admin).
