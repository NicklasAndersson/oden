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
  som blir "stale" direkt eller hamnar i framtiden. Det gäller pollningen av
  filarkivet också: `?startTime=` räknas ut ur Odens egen klocka, så går den fel
  frågar Oden efter fel tidsfönster och missar paket.

## Steg 1 – Skaffa klientidentitet

**Ge Oden ett eget konto/cert** — inte samma som du själv loggar in i ATAK/CloudTAK
med. En TAK Server skickar normalt inte tillbaka en klients egna events till samma
klients andra anslutningar, så använder Oden ditt konto ser den inte punkterna du
placerar. Be TAK-admin om ett dedikerat cert (t.ex. `oden`).

Fråga TAK-admin om **ett av** följande (enklast först):

1. **Data package (`.zip`)** – samma fil som laddas in i ATAK/WinTAK. Oden
   packar upp den själv. Det finns **två sorter**, och de kräver olika saker:
   - **med klientcertifikat** (`.pref`-filen har `certificateLocation` +
     `clientPassword`): allt som behövs ligger i zip:en. Ladda upp och spara.
   - **enrollment-paket** (`.pref`-filen har `caLocation0` + `caPassword0` och
     `enrollForCertificateWithTrust0 = true`, men **inget** `certificateLocation`):
     zip:en innehåller bara serverns CA. Du behöver dessutom ett
     enrollment-konto enligt punkt 2. TAK-fliken säger vilken sort din zip är
     när du laddar upp den.
2. **Enrollment-konto** – användarnamn + lösenord. Oden hämtar ett klientcert
   från servern (port 8446) första gången, sparar det under `ODEN_HOME/tak/`
   (`enrolled-*.p12`, rättigheter `0600`) och återanvänder det vid varje
   anslutning; certet förnyas av sig självt när mindre än 7 dygn återstår, och
   utgången syns i TAK-fliken. **Förnyelsen kräver att enrollment-lösenordet
   fortfarande gäller** — TAK Server ger typiskt 30-dygnscert, så byts lösenordet
   måste det uppdateras i TAK-fliken (eller env-varen) före nästa förnyelse,
   annars slutar TAK fungera vid utgången med ett `401` i loggen. Kombineras med
   ett enrollment-paket, eller med `cot_url` + `tls_ca_cert` om du fått CA:t som
   lös PEM-fil.
3. **Lösa filer** – klientcertifikat (`.p12` eller PEM) + lösenord + serverns
   CA-cert (PEM).
4. **QR-kod för ATAK eller iTAK** – t.ex. den OpenTAKServer visar under
   användarens profil. Skanna koden med mobilkameran, kopiera texten och klistra
   in den under **Anslut med QR-kod** i TAK-fliken (i Chrome/Edge går det också
   att läsa in en skärmbild av koden). Två format stöds:
   - `tak://com.atakmap.app/enroll?host=…&username=…&token=…` (ATAK, nyare iTAK):
     fyller i `cot_url` (`tls://<host>:8089`), `enroll_username` och
     `enroll_password` (token fungerar som enrollment-lösenord). Resten är som
     punkt 2. Serverns CA skickas med certet vid enrollment, och Oden verifierar
     servern mot den när inget `tls_ca_cert` är satt, precis som ATAK.
     **Token är ett lösenord** — dela inte skärmbilder av koden.
   - `namn,server,port,protokoll` (iTAK:s serverkod): fyller bara i `cot_url`;
     användarnamn och lösenord (eller ett data-paket) behövs fortfarande.

   Ingenting sparas förrän du klickar **Spara**.

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

Har du lösa filer i stället: **Välj fil…** finns också vid klientcertifikat
(`.p12`/`.pfx` eller PEM), separat nyckelfil (PEM) och server-CA (PEM). Filen
laddas upp till `ODEN_HOME/tak/` (`0600`), kontrolleras (ett cert ska vara ett
cert, en nyckel en nyckel) och fältet fylls i med sökvägen; klicka **Spara**.

En `.p12` utan lösenord fungerar direkt (Oden gör om den till PEM åt pytak). Är
den lösenordsskyddad: skriv lösenordet i **Certlösenord** (från ATAK ofta
`atakatak`) och klicka **Spara**, eller sätt miljövariabeln under
**Miljövariabel för certlösenord** (standard `ODEN_TAK_CERT_PASSWORD`), som har
företräde när den är satt. Saknas lösenordet säger TAK-fliken det under
*Senaste fel*.

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
| `pref_package` | – | Sökväg till data-package-`.zip`. Fyller själv i URL och CA, plus klientcert om paketet har ett |
| `cot_url` | – | `tls://host:8089` (mTLS) eller `tcp://host:8087` (plain, betrott nät) |
| `enroll_username` | – | Enrollment: användarnamn |
| `enroll_password` | – | Enrollment: lösenord, skrivs i TAK-fliken. Skickas aldrig tillbaka av API:t |
| `tls_client_cert` | – | `.p12` eller PEM (lösa filer). Lösenord i `tls_client_password` eller env-var enligt `tls_client_password_env` |
| `tls_client_password` | – | Certlösenord, skrivs i TAK-fliken. Skickas aldrig tillbaka av API:t |
| `tls_client_key` | – | Separat PEM-nyckel om certet saknar den |
| `tls_ca_cert` | – | Serverns CA (PEM). Behövs inte med `pref_package` |
| **TLS** | | |
| `tls_client_password_env` | `ODEN_TAK_CERT_PASSWORD` | Env-var som certlösenordet läses ur när den är satt |
| `enroll_password_env` | `ODEN_TAK_ENROLL_PASSWORD` | Env-var som enrollment-lösenordet läses ur när den är satt |
| `tls_verify` | `true` | CA-verifiering av servern. `false` bara i labb |
| `tls_check_hostname` | `false` | Kräv att cert-namnet matchar adressen. TAK-cert matchar sällan DNS-namnet – lämna av |
| **Utgående markörer** | | |
| `callsign` | `ODEN` | Vår identitet på servern |
| `cot_stale_seconds` | `3600` | Hur länge en markör är giltig |
| `cot_archive` | `true` | Sätter `<archive/>` så markören överlever att Oden kopplar ner |
| **Egen position (PLI)** | | |
| `pli_enabled` | `false` | Rapportera Odens egen position, så den syns som kontakt i ATAK |
| `pli_lat` / `pli_lon` | – | Var Oden står. Krävs — utan position startar inte rapporteringen |
| `pli_team` / `pli_role` | `Cyan` / `Team Member` | Lag och roll. Rapporter adresserade till laget når då Oden |
| `pli_interval_seconds` | `60` | Hur ofta. Markören är giltig två intervall, så ett missat utskick släcker inte kontakten |
| **Inkommande CoT** | | |
| `inbound_enabled` | `false` | Ta emot CoT och skapa `TAK-OBSERVATION`-noter |
| `inbound_types` | `a-f-G, a-h-*, a-n-G, a-u-*, a-x-X, b-m-p-*, b-a-*` | CoT-typer att släppa in (`*` som suffix). Fångar manuellt placerade markörer/punkter, inte den automatiska lägesrapporteringen (`a-f-*` med undertyper). `a-x-X` är exakt, inte `a-x-*` — det är där HV Rapporter lägger sina 8S |
| `inbound_callsign_allow` / `_deny` | tom | Vitlista / svartlista på **avsändarens** callsign — samma värde som står som `Avsändare:` på noten, inte markörens namn. Delsträngsmatchning, skiftlägesokänslig |
| `inbound_min_move_m` | `100` | Känd enhet som rört sig mindre → ingen ny not |
| `inbound_max_per_minute` | `60` | Hårt tak; resten loggas och släpps |
| `inbound_group_name` | `TAK Inkommande` | Mappen i valvet som TAK-noterna hamnar i (och kanalen Flöde visar). Visas inte längre i TAK-fliken: vart TAK går styrs med källan TAK under Vägval, och mappar under den med grenens steg. Ett tidigare sparat namn gäller fortfarande |
| `inbound_reports_only` | `false` | Bara händelser som bär ett ifyllt rapportblock. Typfiltret kan inte skilja en 8S från en lös fiendemarkör — båda är `a-h-G` |
| **Uppdragspaket (rapporter med bilaga)** | | |
| `inbound_fetch_packages` | `false` | Hämta *mission packages* ur serverns filarkiv. **Utan det tappas hela rapporten** när en 8S skickas med bild – inte bara bilden |
| `inbound_package_poll_seconds` | `60` | Hur ofta filarkivet frågas. Golv på 15 s. Stödjer servern `startTime` hämtas bara det som tillkommit sedan förra rundan, och då är korta intervall billiga |
| `marti_port` | `8443` | Marti-API:ts port. Inte samma som CoT-anslutningens |

**En 8S med bifogad bild syns aldrig på CoT-strömmen.** ATAK packar då händelsen och
bilden i ett *mission package*, laddar upp det till serverns filarkiv och skickar
ingenting på kanalen. Oden ser alltså inte rapporten alls, och eftersom den aldrig
kommer fram loggas heller ingenting om den. Slå på `inbound_fetch_packages` för att
få med dem.

Rapporter **utan** bilaga kommer via CoT-strömmen och syns direkt. Bara de med
bilaga går via filarkivet, och för dem är fördröjningen som mest ett pollningsintervall.

Hela listningen är ~400 kB för ~950 rader och växer under övningen, så att hämta
allt varje minut är det som annars sätter golvet för intervallet. Oden provar därför
`?startTime=` vid start: honoreras den frågas bara det som tillkommit sedan förra
rundan (typiskt noll rader, några hundra byte), annars hämtas hela listan som förut.
Vilket det blev står i loggraden när pollningen startar.

Första gången pollningen kör **importeras ingenting** – filarkivet innehåller ofta
hundratals gamla paket, och de skulle begrava valvet. Den rundan antecknar bara vad
som redan finns, och först paket som dyker upp därefter blir noter. Vill du tvinga
fram en återimport: töm tabellen `tak_package_seen` i `config.db`.

Bilagan hamnar i valvet och länkas från noten under `## Bilagor`, precis som en
Signal-bilaga. Poster på 0 byte hoppas över och loggas som varning – ATAK kan
deklarera en bild i manifestet och ändå packa en tom fil, och en tom fil i valvet
är sämre än ingen.

### Två 8S-format

Samma rapporttyp kommer i två oförenliga former, eftersom två olika ATAK-plugins är
igång samtidigt i förbandet och båda skriver en 8S:

| plugin | CoT-typ | form |
|---|---|---|
| **8S** (`com.atakmap.android.eights.plugin`) | `a-h-G` | engelska fältnamn som attribut på `<_8S_>` |
| **HV Rapporter** (`com.atakmap.android.hvreports.plugin`) | `a-x-X` | svenska fältnamn som elementtext, inlindade i `<HVSS_DOCUMENTS>`, tid i ISO 8601 (UTC) |

Oden hanterar båda och skriver samma 7S-not oavsett vilken operatören använde. Det
kräver att **`a-x-X` finns i `inbound_types`** — utan den kastas HV Rapporter-rapporten
innan den ens parsas, och eftersom den aldrig kommer fram loggas ingenting om den.

Fältnamnen slås upp normaliserat (versaler, utan skiljetecken) mot en alias-lista, så
`STÄLLE` och `POSITION` landar i samma 7S-fält. Det finns alltså ingen "rätt" form att
ställa om terminalerna till — båda fungerar.

### Att kunna adressera rapporter till Oden

En TAK-server levererar **riktad** CoT bara till de callsign som står i
`<marti><dest>`, och ATAK bygger den mottagarlistan ur de positionsrapporter den
sett. Oden skickade tidigare ingen egen position och gick därför inte att välja som
mottagare: allt som skickades till en person eller ett lag i stället för som
broadcast kom aldrig fram — och eftersom servern aldrig skickade det loggades
ingenting heller.

Skarp verifiering: avsändarens egna positionsrapporter kom fram medan deras riktade
rapport inte gjorde det.

Slå på `pli_enabled` och ange `pli_lat`/`pli_lon`, så dyker Oden upp i kontaktlistan
och går att adressera. Sätt `pli_team` till det lag rapporterna skickas till om
avsändarna adresserar lag snarare än enskilda.

Priset är att Oden syns som en ikon på allas karta. Vill du undvika det är
alternativet att avsändarna använder Broadcast.

**Lösenord.** Enrollment-lösenordet och certlösenordet kan skrivas direkt i
TAK-fliken — det är den enkla vägen, och det är enda sättet att komma igång utan
att pilla med miljövariabler. Tomt fält vid Spara behåller det sparade; **Rensa**
tar bort det. API:t returnerar det aldrig; GUI:t visar bara att
ett lösenord finns sparat.

Vill du hellre hålla det utanför config-db går miljövariabeln fortfarande att
använda, och **den har företräde när den faktiskt är satt i miljön**:

```bash
export ODEN_TAK_CERT_PASSWORD='...'      # eller ODEN_TAK_ENROLL_PASSWORD
```

macOS-app / systemd: lägg variabeln i launchd/unit-miljön. Startar du Oden.app
från Finder ärvs **inte** din terminals `export` — använd fältet i TAK-fliken,
eller `launchctl setenv`.

### Server-CA och cert-namn

En TAK Server signerar sina egna certifikat:

- `pref_package` innehåller serverns CA – Oden konverterar den till PEM åt dig.
  Har paketet även ett klientcert behövs inget mer; är det ett enrollment-paket
  behövs dessutom `enroll_username` + `enroll_password`.
- Enrollment (konto eller QR-kod) utan `tls_ca_cert`: servern skickar sin CA
  tillsammans med klientcertet, Oden sparar den som `enrolled-*-ca.pem` bredvid
  certet och verifierar servern mot den.
- Lösa filer utan `tls_ca_cert` → `self-signed certificate in certificate chain`.
  Exportera CA:t från TAK-admin/CloudTAK, eller `tls_verify = false` i labb.
- Serverns cert-namn är ofta inte DNS-namnet du ringer →
  `Hostname mismatch`. `tls_check_hostname` är av som standard; CA-koll kvar på.

### Omstart importerar inte om det som redan kommit in

En TAK Server återutsänder varje levande markör, och ATAK kan göra det så ofta
som var tionde sekund. Dedup-skyddet håller reda på vad som redan blivit en not,
och det tillståndet sparas i tabellen `tak_inbound_seen` i `config.db` så att en
omstart av Oden inte gör om serverns lägesbild till nya noter. Tabellen innehåller
uid, position och en textsignatur per markör.

Den skrivs var trettionde sekund när något ändrats, och vid nedstängning. Poster
som inte setts på trettio dygn glöms, så en markör som togs bort för länge sedan
inte blockerar en legitim återimport. Töms tabellen är enda följden att det som
fortfarande är levande på servern importeras en gång till.

### Vilka kanaler är Oden med i?

TAK Servers *channels* (internt *groups*) bestämmer vem som får se vad, och de
sitter på servern knutna till certifikatet. Listan skickas aldrig till klienten,
och Oden läser inte ens `__group` i inkommande CoT — Oden kan alltså inte visa
den. Får du inga noter fast kontot är eget och typen borde matcha, fråga servern
direkt med Odens eget cert:

```bash
python scripts/tak_channels.py ~/.config/oden/tak/paket.zip --user 25HVBAT675
```

Den listar kanalerna för det kontot med riktning och om de är aktiva, plus vilka
klienter servern ser. Oden får bara trafik i kanaler som är aktiva och omfattar
IN. Skickar din ATAK-enhet i en kanal som inte står i listan kommer ingenting
fram, hur vid `inbound_types` än är. Certet måste redan vara hämtat, så kör en
anslutning först. Marti-API:t ligger normalt på 8443 (`--port` för annat).

### Inkommande CoT – noter i valvet

En not får rubriken `TAK-OBSERVATION` (medvetet *inte* `… RAPPORT`, så den inte
studsar tillbaka till TAK) i gruppen `TAK Inkommande`. Vart TAK-meddelanden går
väljs med källan **TAK** under Vägval i Pipelines-fliken (inte med gruppnamnet).

**Steget TAK → text.** TAK skickar XML (CoT), inte text. Den råa CoT:en sparas
med meddelandet (`_cot_xml` i kuvertet), och första steget i grenen, *TAK →
text*, gör om den till text som stegen efter läser. Det syns i Flöde som
*Omvandlad* med vad det blev (t.ex. ”8S omgjord till 7S RAPPORT”), och har egna
inställningar per gren: gör om 8S till 7S (på/av), gör om SCRIM (på/av), övriga
markörer som observation eller hoppa över (sparas då bara i Flöde), och om
formuläret ska följa med i `%%`-blocket. Med standardinställningarna blir texten
exakt densamma som tidigare. I Testrutan kan man klistra in en CoT (`<event …>`)
och se hela vägen (källan sätts till TAK).

**Nödlarm.** Ett `<emergency>` (911, In Contact m.fl.) läses som formuläret
*Nödlarm* med fälten Larmtyp, Beskrivning, Avbrutet (ja/nej, `cancel="true"`
när larmet dras tillbaka) och Larmat av. Det syns i observationen, och med
*formulärets namn som rubrik* börjar texten med `Nödlarm`. Larm släpps igenom av
`inbound_reports_only` och av standardtyperna (`b-a-*`).

**Rutter.** En rutt (`b-m-r`) blir formuläret *Rutt* med waypointerna i ordning
som `Punkter: A → B → C` och ruttens egna uppgifter (typ, metod, riktning).
Waypointernas koordinater finns inte i rutten (de är egna CoT:er). Rutter
släpps inte igenom av standardtyperna; lägg till `b-m-r` i `inbound_types`.

Fält med samma namn i ett formulär numreras (`namn`, `namn 2`, …) i stället för
att bara det första behålls.

**Andra ATAK-formulär än 8S och SCRIM.** Fälten läses generellt, oavsett hur
formuläret är uppbyggt. Som standard blir ett okänt formulär en
`TAK-OBSERVATION` med alla fält. Välj *Formulärets namn som rubrik* i steget TAK
→ text så blir första raden formulärets namn; skapa sedan ett rapportformat med
den rubriken (Pipelines → Rapportformat). Klistra in formulärets CoT i
rapportformatets testruta och klicka *Fyll i rubrik och fält från formuläret*
så fylls rubrik och fält i åt dig. Kontrollera att CoT-typen släpps igenom av
`inbound_types`.

**Undantag – 8S-rapporter:** bär händelsen en 8S-rapport från ATAK:s
Reports-plugin mappas den istället till en vanlig `7S RAPPORT` och skrivs som en
7S-fil (samma frontmatter och kropp som Signal-inmatade 7S). De oförändrade
8S-fälten och exakta koordinater följer med i ett dolt `%%`-block sist i filen
så inget tappas. Eko-skyddet gör att filen inte publiceras tillbaka till TAK.
`Ställe` blir markörens exakta punkt; skriver operatören en annan MGRS-ruta i
POSITION (mer än ~20 m från markören) är det den som gäller. Fritext i POSITION
blir platsnamn.

Avsändaren på en inkommande not är operatörens enhet (`tak:ANDROID-…`) när
CoT:en anger den (`<creator>`/`<link relation="p-p">`), annars markörens uid.
ATAK:s Reports-plugin anger ingen enhet, så 8S-rapporter får ett uid per rapport.

Filtren är staplade billigast först: eko-vakt (`ODEN.*`) → typ → callsign → dedup
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

### Kontrollera ett data-paket från terminalen

`scripts/tak_check_package.py` säger vad ett paket innehåller och kan testa
anslutningen utan att röra config-db:n — går att köra medan Oden är igång:

```bash
# vad är det här för paket?
python scripts/tak_check_package.py ~/.config/oden/tak/mitt-paket.zip

# enrollment-paket: hämta cert och anslut på riktigt
export ODEN_TAK_ENROLL_PASSWORD='...'
python scripts/tak_check_package.py ~/.config/oden/tak/mitt-paket.zip --connect --user oden

# ... och skicka en markör när anslutningen är uppe
python scripts/tak_check_package.py ~/.config/oden/tak/mitt-paket.zip \
    --connect --user oden --send 34VCM7934926095
```

Utpackade certifikat hamnar i en temporärkatalog som tas bort när skriptet slutar.

## Felsökning

| Symptom | Trolig orsak |
|---|---|
| `self-signed certificate in certificate chain` | `tls_ca_cert` saknas/fel. Använd `pref_package` eller serverns `truststore-root.pem` |
| `Hostname mismatch, certificate is not valid for ...` | Serverns cert-namn ≠ adressen. `tls_check_hostname` ska vara av |
| `pytak saknas` i loggen | `pip install "oden[tak]"` |
| `TypeError('stat: path should be ... not NoneType')` vid anslutning | Gammal version (≤ 4.0.1) med ett **enrollment-paket**: paketet saknar klientcert och den dåvarande inläsningen klarade bara paket med cert. Uppgradera; Oden säger nu istället vilka enrollment-uppgifter som fattas |
| `data-paketet innehåller bara serverns CA och kräver enrollment` | Rätt sorts paket, men fyll i enrollment-användarnamn och lösenord i TAK-fliken |
| `enrollment mot host:8446 som … misslyckades — Error generating CSR: 401` | Fel användarnamn/lösenord. Fungerade det nyss: kontrollera att env-varen fortfarande är satt i **den här** terminalen (`printenv ODEN_TAK_ENROLL_PASSWORD \| wc -c`) och att lösenordet inte roterats sedan certet förnyades sist. `Cannot connect`/timeout i samma rad → port 8446 nås inte från Oden-värden |
| TAK slutade fungera ~30 dygn efter driftsättning, `401` i loggen | Det enrollade certet gick ut och förnyelsen nekades — enrollment-lösenordet har bytts. Uppdatera det i TAK-fliken och spara |
| Ansluter men inget syns i ATAK | Markören redan stale, eller fel klocka. Kolla `cot_stale_seconds` + NTP |
| Markör försvinner efter en stund | `cot_archive = false` och Oden tappade anslutningen |
| Status 🔴 fast servern är uppe | Oden återansluter själv med ökande intervall (5 s → 5 min); `Senaste fel` visar orsaken. Spara inställningarna igen för att tvinga ett försök direkt |
| Markör i havet (0,0) | MGRS i `Ställe` gick inte att tolka |
| Dubbla markörer för samma rapport | uid-härledning matchar inte mellan original och `++` – buggrapport |
| Översvämmas av inkommande noter | `inbound_types` för brett, eller höj `inbound_min_move_m` |
| Inget loggas när du placerar punkter i TAK | (1) `inbound_enabled` av? (2) **Oden och du använder samma TAK-konto** — servern skickar inte tillbaka dina egna events till din andra anslutning; ge Oden ett eget cert/konto. (3) **Olika kanaler** — servern levererar bara CoT i kanaler kontot är med i; se nedan. (4) Punkttypen matchar inte `inbound_types`. Statusraden i TAK-fliken visar `N mottagna / M filtrerade`, och sammanfattningsraden i loggen räknar upp vilka typer som kastades |
| Vet inte vilken kanal Oden är med i | Oden vet det inte själv — kanaltillhörighet sitter på servern, knuten till certifikatet, och skickas aldrig till klienten som en lista. Fråga servern: `python scripts/tak_channels.py <paket.zip> --user <namn>` |
| Markörer syns för dig men inte andra | Servern kräver data marking / mission – prata med TAK-admin |

## Säkerhet

- Cert-filer och data package: `chmod 600`, ägs av Oden-användaren.
- Cert-/enrollment-lösenord sparade i TAK-fliken ligger i klartext i config-db
  (skickas aldrig tillbaka av API:t). Vill du inte det: miljövariabel eller
  OS-nyckelring.
- `tls_verify = false` bara i labb.
- Enrollment-anropet mot port 8446 görs av `pytak`, som stänger av
  TLS-verifieringen för just det anropet (`trust_all` är hårdkodat i
  `CertificateEnrollment`). Användarnamn och lösenord går alltså över en kanal
  vars servercert inte verifieras — enrolla på ett nät du litar på, och använd
  ett konto som bara är till för Oden. Anropet görs bara när inget giltigt cert
  finns cachat, inte vid varje anslutning.
- Det enrollade certet (privat nyckel) ligger i `ODEN_HOME/tak/enrolled-*.p12`
  med passfrasen i `.pass` bredvid, båda `0600`. Ta bort dem om kontot byter
  ägare — Oden hämtar ett nytt vid nästa start.
- Inkommande CoT behandlas som osäker indata (callsign/uid saneras, koordinater
  klampas, remarks trunkeras). Slå på `inbound_enabled` bara på ett nät du litar på.
- Klientcert går ut – GUI:t varnar < 30 dygn innan (gäller `tls_client_cert`;
  med `pref_package` håll koll via TAK-admin).
