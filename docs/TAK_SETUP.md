# TAK-integration – operatörsguide

Hur du kopplar Oden till en befintlig TAK Server så att rapporter blir
CoT-markörer och (valfritt) inkommande CoT blir noter i valvet.

Se `docs/PLAN_TAK.md` för designen. Den här guiden är för den som ska driftsätta.

## Förutsättningar

- En TAK Server som körs någon annanstans, och en **TAK-admin** som kan ge dig
  klientåtkomst.
- Oden byggd med TAK-stödet: `pip install "oden[tak]"` (drar in `pytak`).
- Utgående nätåtkomst från Oden-värden till serverns streaming-port
  (normalt TCP **8089**). Inga inkommande portar behövs – Oden ansluter ut.
- **NTP aktiverat** på Oden-värden. CoT-tider är i UTC; fel klocka ger markörer
  som är "stale" direkt eller ligger i framtiden.

## Steg 1 – Skaffa klientidentitet

Fråga din TAK-admin om **ett av** följande (i fallande ordning av bekvämlighet):

1. **Data package (`.zip`)** – samma fil som laddas in i ATAK/WinTAK. Innehåller
   serveradress, server-CA och ett klientcert. Enklast: peka Oden på zip-filen.
2. **Klientcertifikat `.p12`** + lösenord, plus serverns **CA-cert** (PEM) och
   `host:port`.
3. **Enrollment-konto** (användarnamn/lösenord) om servern kör
   certifikat-enrollment. `pytak` kan hämta certet självt.

Lägg filerna någonstans läsbart bara för Oden-användaren:

```bash
mkdir -p ~/.config/oden/tak && chmod 700 ~/.config/oden/tak
cp ~/Downloads/oden-tak.zip ~/.config/oden/tak/     # eller .p12 + ca.pem
chmod 600 ~/.config/oden/tak/*
```

## Steg 2 – Konfigurera `config.ini`

TAK-inställningarna lagras i Odens config-databas som nyckeln `tak_settings`
(en JSON-dict). Web-GUI-formuläret kommer i fas 4 — tills dess sätts de med en
engångssnutt:

```python
from pathlib import Path
from oden.config_db import set_config_value
from oden import config as cfg

set_config_value(cfg.CONFIG_DB, "tak_settings", {
    "enabled": True,
    "cot_url": "tls://tak.example.mil:8089",
    "tls_client_cert": str(Path.home() / ".config/oden/tak/oden.p12"),
    "tls_client_password_env": "ODEN_TAK_CERT_PASSWORD",
    "tls_ca_cert": str(Path.home() / ".config/oden/tak/ca.pem"),
    "callsign": "ODEN",
    "cot_stale_seconds": 3600,
    "cot_archive": True,
})
```

Fälten nedan visas som `[TAK]`-sektion för läsbarhet; nyckelnamnen är desamma i
JSON-dicten. Välj **A**, **B** eller **C**.

### A) Data package (rekommenderas)

```ini
[TAK]
enabled = true
pref_package = /Users/<du>/.config/oden/tak/oden-tak.zip
callsign = ODEN
cot_stale_seconds = 3600
cot_archive = true
publish_report_types = 7S, FORS, PEDARS
publish_require_coords = true
```

### B) Losa cert-filer

```ini
[TAK]
enabled = true
cot_url = tls://tak.example.mil:8089
tls_client_cert = /Users/<du>/.config/oden/tak/oden.p12
tls_client_password_env = ODEN_TAK_CERT_PASSWORD
tls_ca_cert = /Users/<du>/.config/oden/tak/ca.pem
tls_verify = true
callsign = ODEN
cot_stale_seconds = 3600
cot_archive = true
publish_report_types = 7S, FORS, PEDARS
publish_require_coords = true
```

Sätt lösenordet som miljövariabel (inte i filen):

```bash
export ODEN_TAK_CERT_PASSWORD='...'
```

macOS-app / tjänst: lägg den i din launchd/env-uppsättning, inte i `config.ini`.

### C) Inkommande CoT också

Lägg till (default: av). Inkommande lägesbild från en TAK Server kan vara
**mycket** trafik – filtren nedan är till för att bara släppa in det intressanta.

```ini
inbound_enabled = true
inbound_types = a-h-*, a-u-*, b-a-*     ; fiende, okänd, larm – inte egen PLI
inbound_callsign_allow =                ; tom = alla; annars kommaseparerad vitlista
inbound_callsign_deny =
inbound_min_move_m = 100                ; samma enhet som rört sig mindre → ignoreras
inbound_max_per_minute = 60             ; hårt tak; resten loggas och släpps
inbound_group_name = TAK Inkommande
```

Inkommande CoT blir en not med rubriken `TAK-OBSERVATION` i gruppen
`TAK Inkommande`. Noterna passerar **gruppfiltret** som allt annat — kör du
whitelist-läge måste `TAK Inkommande` finnas i listan, annars filtreras de bort.

Filtren är staplade i den ordning de är billigast: typ → callsign → eko-vakt
(vårt eget `ODEN.*`-uid) → dedup per uid (samma plats + samma text = ingen ny
not) → tak per minut. Börja snävt och vidga; en TAK Server pushar hela
lägesbilden till varje ansluten klient.

### Konvertera `.p12` → PEM (bara om `pytak` klagar på din `.p12`)

```bash
openssl pkcs12 -in oden.p12 -nodes -out oden.pem      # cert + nyckel i en fil
# peka tls_client_cert på oden.pem, ta bort lösenordet
```

## Steg 3 – Testa mot en lokal server (valfritt men rekommenderat)

Innan du pekar mot skarp server, kör [`taky`](https://pypi.org/project/taky/)
(ren Python) eller FreeTAKServer lokalt:

```bash
pipx install taky
taky_setup            # genererar självsignerad CA + servercert
takyd                 # lyssnar på :8089
./takd_client_cert    # (taky) generera ett klientcert.p12 att peka Oden på
```

Kör FreeTAKServer istället? Sätt även `FTS_COMPAT=1` i miljön (pytak lägger då in
slumpfördröjning som FTS vill ha).

## Steg 4 – Starta och verifiera

1. Starta Oden. Loggen ska visa `TAK: ansluten till tls://…:8089`.
2. Web-GUI → TAK-panelen: status **Ansluten**, certets utgångsdatum syns.
3. Klicka **Skicka test-CoT** (ange en MGRS). Markören ska dyka upp i ATAK/iTAK
   inom någon sekund.
4. Skicka en riktig `7S RAPPORT` i din Signal-grupp. Kontrollera att:
   - markdown-noten skapas i valvet som vanligt, **och**
   - en markör med callsign `7S <TNR>` dyker upp på TAK-kartan på rätt plats.
5. (Om inbound på) Skapa en markör i ATAK → en `TAK-OBSERVATION`-not ska dyka upp
   i Odens meddelandevy under gruppen "TAK Inkommande".

## Felsökning

| Symptom | Trolig orsak |
|---|---|
| `TLS handshake failed` / `certificate verify failed` | Fel `tls_ca_cert`, eller servern använder annan CA än du fått. Verifiera med `openssl s_client -connect host:8089`. |
| Ansluter men inget syns i ATAK | Fel affiliering/typ, eller markören redan "stale". Kolla `cot_stale_seconds` och Oden-värdens klocka (NTP). |
| Markör försvinner efter en stund | `cot_archive = false` och Oden tappade anslutningen. Sätt `cot_archive = true`. |
| Markör hamnar på fel plats / i havet (0,0) | MGRS-strängen i rapporten gick inte att tolka → ingen lat/lon. Kolla `Ställe`-fältet. |
| Dubbla markörer för samma rapport | `uid`-härledningen matchar inte mellan original och `++`-påfyllning. Buggrapport. |
| Översvämmas av inkommande noter | `inbound_types` för brett – ta bort `a-f-*`, snäva in, höj `inbound_min_move_m`. |
| `password is required` vid start | `ODEN_TAK_CERT_PASSWORD` inte satt i Odens miljö. |
| Markörer syns för dig men inte för andra på servern | Servern kräver data marking / mission-medlemskap. Prata med TAK-admin (se PLAN_TAK "Kolla med TAK-admin"). |

## Säkerhet

- Cert-filer och data package: `chmod 600`, ägs av Oden-användaren.
- Cert-lösenord i miljövariabel eller OS-nyckelring, **aldrig** i `config.ini`
  (den visas i web-GUI:t).
- `tls_verify = false` bara i labb – aldrig mot skarp server.
- Inkommande CoT behandlas som osäker indata (callsign/uid saneras, koordinater
  klampas, remarks trunkeras). Aktivera `inbound_enabled` bara om du litar på
  nätet du ansluter till.
- Klientcert går ut. Web-GUI:t varnar < 30 dygn innan – beställ nytt i tid.
