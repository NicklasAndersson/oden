# 7S-meddelandeformat — specifikation för den centrala applikationen

**Version:** 1.0
**Datum:** 2026-06-24
**Mottagare:** utvecklare av den centrala applikationen (Signal → formaterat 7S)

---

## 1. Syfte och avgränsning

Den centrala applikationen tar emot fritext-observationer (via Signal),
strukturerar dem enligt Försvarsmaktens 7S-mall och skriver ut en
Markdown-fil per meddelande till en delad mapp (en Obsidian-vault).

Detta dokument specificerar **utdataformatet** — exakt hur varje fil ska se ut.
Det specificerar **inte** hur tolkningen/extraktionen går till internt.

**Viktig avgränsning — vad applikationen INTE ska göra:**
Applikationen utför *enkel, regelbaserad* länkning av kännetecken (se §6). Den
ska **inte** göra analys: ingen återidentifiering (avgöra att två partiella
nummerplåtar är samma fordon), ingen klustring, inga aggregerade entitetsnoter,
ingen mönsterdetektering. Sådant sker i ett separat analyssteg (en
Obsidian-plugin) som läser dessa filer. Applikationens uppgift är att producera
*rena, korrekt länkade meddelanden* — varken mer eller mindre.

---

## 2. Filnamn

```text
TNR<DDHHMM>[_<n>].md
```

- `TNR` — fast prefix (versaler).
- `DDHHMM` — rapportens eget tidsnummer som kommer från fältet `TNR` i 7S-inmatningen.
  Formatet är dag-i-månad, timme, minut, nollutfyllt tvåsiffrigt. Det är ofta samma
  som observationstiden men behöver inte vara det, eftersom `Stund` avser när
  observationen gjordes medan `TNR` kan avse när rapporten skickades in.
- `_<n>` — kollisionssuffix. Om en fil med samma TNR redan finns läggs `_2`,
  `_3`, … till i ankomstordning. Första filen får inget suffix.
- Exempel: `TNR140755.md`, `TNR140755_2.md`.

> Notera: DDHHMM saknar månad/år. Inom en avgränsad insats (dagar–veckor) är det
> tillräckligt unikt; kollisioner hanteras med suffix. Fullständig tidpunkt
> finns alltid i frontmatter (§4).

---

## 3. Filstruktur (övergripande)

Varje fil består av två delar:

1. **YAML-frontmatter** mellan `---`-rader (maskinläsbara egenskaper, §4).
2. **Rapportkropp** i Markdown (människoläsbar 7S-text, §5).

En tom rad skiljer frontmatter från kropp. Filen är UTF-8, LF-radslut, och
avslutas med en avslutande nyrad.

Med **frontmatter** avses alltså YAML-blocket högst upp i filen, mellan de två
`---`-raderna. Det är filens maskinläsbara metadata, separerat från den
människoläsbara rapportkroppen.

---

## 4. Frontmatter (YAML)

Exakt dessa nycklar, i denna ordning:

```yaml
---
id: 7S-004
typ: 7S-rapport
tnr: "140755"
tidpunkt: "2026-02-14T07:55:00"
signal_tidpunkt: "2026-02-14T08:12:34"
signal_avsandare_nummer: "+46701234567"
signal_avsandare_id: "b1f2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
plats: "Grusparkering vid motionsspåret"
lat: 59.26608
lon: 17.70644
location: "59.26608,17.70644"
sagesman: AQ
---
```

Nycklar:

- `id` — sträng. Stabil unik identifierare. Format `7S-NNN` i exempeldata; valfri stabil sträng i drift (t.ex. UUID). Måste vara unik över hela vaulten.
- `typ` — sträng. Konstant `7S-rapport`. Skiljer rapporter från andra noter i grafvyn.
- `tnr` — sträng. Samma som filnamnets TNR-del, **utan** `TNR`-prefix och **utan** `.md`. Hämtas från inmatningens `TNR` och kan därför skilja sig från observationstiden. Inkludera ev. kollisionssuffix (`140755_2`). Sträng, inte tal (kan ha ledande nollor och `_`).
- `tidpunkt` — sträng. ISO 8601 lokal tid, `YYYY-MM-DDTHH:MM:SS`. Observationens tidpunkt. Detta är den auktoritativa tidsstämpeln.
- `signal_tidpunkt` — sträng. ISO 8601 lokal tid, `YYYY-MM-DDTHH:MM:SS`. Tidpunkten då Signal-meddelandet togs emot. Hämtas från Signals mottagningstidsstämpel när den finns.
- `signal_avsandare_nummer` — sträng. Avsändarens nummer i Signal-meddelandet. Citeras som sträng för att behålla exakt värde.
- `signal_avsandare_id` — sträng. Avsändarens Signal-id från meddelandet, normalt en UUID. Citeras som sträng för att behålla exakt värde.
- `plats` — sträng. Fritext-platsnamn. **Citerad** (dubbelfnuttar) eftersom den kan innehålla specialtecken.
- `lat` — tal. WGS84 decimalgrader, 5 decimaler. Nordlig latitud positiv.
- `lon` — tal. WGS84 decimalgrader, 5 decimaler. Östlig longitud positiv.
- `location` — sträng. Kombinerad koordinat `"lat,lon"` för kartvy (§8). **Krävs när koordinater finns** och måste spegla `lat`/`lon` exakt. Utelämnas helt om koordinater saknas.
- `sagesman` — sträng. Anropssignal för rapporterande enhet (§7).

Regler:

- Saknas koordinater för en observation: utelämna `lat`, `lon` **och**
  `location` helt (skriv dem inte som `null` eller `0`). `plats` bör ändå anges
  som fritext.
- Lägg inte till extra nycklar utan att uppdatera denna spec och schemat.
- Kombinerad koordinat för kartvy: se §8 (`location`-nyckel, krav när koordinater finns).

---

## 5. Rapportkropp (7S)

Exakt dessa sju kärnfält, i denna ordning, var och en med **fet** etikett följd av
kolon, och åtskilda av en tom rad. TNR upprepas först i kroppen för läsbarhet.
Efter `Sagesman` får ett valfritt extra S-fält, `Sedan`, förekomma när
rapporten anger vad patrullen gör efter observationen.

```markdown
**TNR:** 140755

**Stund:** 2026-02-14 07:55

**Ställe:** Grusparkering vid motionsspåret

**Styrka:** 2 personer

**Slag:** Person

**Sysselsättning:** Fiskade vid vattnet.

**Sagesman:** AQ

**Sedan:** Återgår till bas.
```

Fälten (7S):

Notation i tabellen nedan: uttrycket `= frontmatter <nyckel>` betyder att samma
uppgift också ska finnas i YAML-frontmatteren högst upp i filen. Det betyder
inte att olika 7S-fält måste vara lika med varandra bara för att de båda
refererar till frontmatter. Exempel: `TNR` i kroppen hämtas från frontmatter
`tnr`, medan `Stund` i kroppen återger frontmatter `tidpunkt` i ett annat,
människoläsbart format.

Fält:

- `TNR` — samma uppgift som i frontmatter `tnr`, återgiven i kroppen för läsbarhet.
- `Stund` — samma tidpunkt som i frontmatter `tidpunkt`, men i människoläsbar form `YYYY-MM-DD HH:MM` (utan sekunder).
- `Ställe` — samma uppgift som i frontmatter `plats`, men utan citationstecken.
- `Styrka` — antal/styrka. Ex: `1 fordon`, `2 personer`, `1 fordon, 2 personer`, `Familj (3-4)`.
- `Slag` — typ av observation. Ex: `Person`, `Fordon`, `Fordon + person`, `Person (cykel)`, `Fordon (jordbruk)`.
- `Sysselsättning` — vad de gör. Fritext, en mening.
- `Symbol` — särskiljande kännetecken. **Här placeras länkar** (§6).
- `Sagesman` — samma uppgift som i frontmatter `sagesman`, återgiven i kroppen för läsbarhet.
- `Sedan` — valfritt extra S efter `Sagesman`. Beskriver vad patrullen gör efter observationen. Ingen separat frontmatter-nyckel krävs.

**Konsistenskrav:** fälten måste vara inbördes förenliga. Ett `Slag: Fordon`
får inte ha `Sysselsättning` eller `Symbol` som beskriver en fotgängare, och
vice versa. (Detta gäller den centrala applikationens *tolkning* av fritexten.)

---

## 6. Länkning av kännetecken (Obsidian-wikilänkar)

Den centrala applikationen identifierar särskiljande kännetecken i fält
**Symbol** med enkel, regelbaserad matchning och omsluter dem med `[[ ]]`
(Obsidian-wikilänkssyntax). Detta skapar noder i Obsidians graf.

### 6.1 Vad som ska länkas

Kategorier:

- Fullständig nummerplåt: Svenskt format (§6.3). Exempel i text: `reg [[RJK241]]`.
- Partiell nummerplåt: Plåt där tecken saknas; maskera saknade positioner med `.` (§6.4). Exempel i text: `reg [[..G41.]]`.
- Annat distinkt kännetecken som matchas regelbundet: kanoniserad etikett (§6.5). Exempel i text: `[[logotyp-fragment DGE]]`.

### 6.2 Vad som INTE ska länkas

- Generiska beskrivningar utan särskiljande värde (`vardaglig klädsel`,
  `man ca 40 år`).
- Fordonsmärke/-modell/-färg ensamt (`mörkröd Toyota Avensis`) — det är
  kontext, inte en identifierare. (Endast plåten länkas.)
- Tolkningar/slutsatser. Länka det som *observerats*, inte det som *antas*.

### 6.3 Svenskt nummerplåtsformat (fullständig)

Två giltiga mönster:

- `AAA NNN` — tre bokstäver, tre siffror.
- `AAA NNL` — tre bokstäver, två siffror, en bokstav.

I länken skrivs plåten **utan mellanslag**: `RJK241`, `WBN84X`.

Tillåtna bokstäver: `A-Z` utom `I O Q V` (svensk konvention, undviker
förväxling). Använd versaler.

Regex (fullständig plåt):

```regex
^[ABCDEFGHJKLMNPRSTUWXYZ]{3}[0-9]{2}[0-9ABCDEFGHJKLMNPRSTUWXYZ]$
```

### 6.4 Partiell nummerplåt

När observatören bara sett delar av plåten: behåll plåtens **längd och
struktur**, ersätt varje **oläst position** med en punkt `.`. Punkten fungerar
som en regex-wildcard mot den fullständiga plåten.

- `RJK241` delvis sedd → t.ex. `..G41.`? **Nej** — positionerna måste stämma.
  Om position 4–5 lästes som `24` och resten är oläst: `...24.`.
- Maskera *faktiska* olästa positioner; gissa inte tecken.
- Behåll total längd (6 tecken).

Regex (partiell plåt — minst en punkt, i övrigt giltig struktur):

```regex
^[A-Z.]{3}[0-9.]{2}[0-9A-Z.]$   (och innehåller minst ett '.')
```

> En partiell plåt ska kunna matchas mot en fullständig med
> `re.match('^' + partiell + '$', fullständig)` (punkt = wildcard). Att *avgöra*
> vilken fullständig plåt den motsvarar är **analys (plugin)**, inte
> applikationens uppgift.

### 6.5 Kanoniserade kännetecken-etiketter

För icke-plåt-kännetecken som matchas regelbundet (logotyp-fragment,
ryggsäcksmärkning, keps m.m.): använd en **stabil, kanonisk etikett** så att
samma kännetecken alltid ger samma länktext (och därmed samma nod). Etiketten
är kort beskrivande svenska, gemener.

Exempel som används i testdata:

- `[[logotyp-fragment DGE]]`
- `[[ryggsäck märkning delvis läsbar -TAC]]`
- `[[keps mörk med ljust emblem]]`

Kravet är **determinism**: identiskt observerat kännetecken → identisk
länktext. Variation i fritext ska normaliseras till den kanoniska etiketten
innan länkning.

### 6.6 Inga entitetsfiler

Applikationen skapar **endast länkarna i meddelandet**. Den skapar **inga**
not-filer för entiteterna. En länk till en fil som inte finns blir en
"unresolved link"-nod i Obsidian — det är avsett. Att skapa och berika
entitetsnoter är analyssteget (plugin).

---

## 7. Anropssignaler (`sagesman`)

Kompani med huvudanropssignal **QO**. Plutoner:

Plutoner:

- `AQ` — 1. skyttepluton (linje)
- `BQ` — 2. skyttepluton (linje)
- `CQ` — 3. skyttepluton (linje)
- `DQ` — 4. skyttepluton (linje)
- `EQ` — stabspluton

I drift kan finare signaler förekomma; för detta format räcker plutonsnivå.
Oden bevarar inkommande `sagesman` även när värdet avviker från `AQ`-`EQ`, men
bör logga en varning för att markera att signalen inte följer den kanoniska
plutonsnivån.
Geografisk koppling (en pluton ansvarar normalt för en sektor) är en
*egenskap hos insatsen*, inte ett formatkrav.

---

## 8. Kart-kompatibel koordinat (`location`) — KRAV

Obsidians kartvy (community-plugin "Map View") läser **inte** separata
`lat`/`lon`-nycklar automatiskt. Därför **krävs** en kombinerad nyckel i
frontmatter när koordinater finns:

```yaml
location: "59.26608,17.70644"
```

- Format: sträng `"lat,lon"` (Map Views textformat). Decimalpunkt, komma som
  separator, inget mellanslag. Värdena ska vara **identiska** med `lat`/`lon`.
- `lat`/`lon` behålls som maskinläsbara tal (för t.ex. avståndsberäkning i
  analyssteget); `location` är den kartläsbara dubbletten.
- Saknas koordinater: utelämna alla tre (`lat`, `lon`, `location`).

> Listformatet `[lat, lon]` accepteras också av Map View, men för enhetlighet
> i detta format används strängformen `"lat,lon"`.

---

## 9. Teckenkodning och robusthet

- UTF-8 utan BOM. Svenska tecken (å ä ö) skrivs som sig själva, inte escapade.
- LF radslut.
- Citera `plats` (och varje frontmatter-strängvärde som kan innehålla `:`,
  `#`, `[`, citationstecken eller inledande/avslutande blanksteg).
- **Citera `tnr` och `tidpunkt`** (dubbelfnuttar) så att YAML-parsers behandlar
  dem som strängar — annars tolkas `tidpunkt` som en YAML-timestamp och `tnr`
  som ett heltal, vilket bryter schemavalidering.
- Validera mot JSON-schemat (`7S_frontmatter.schema.json`) innan skrivning.

---

## 10. Minimiexempel (komplett fil)

```markdown
---
id: 7S-004
typ: 7S-rapport
tnr: "140755"
tidpunkt: "2026-02-14T07:55:00"
signal_tidpunkt: "2026-02-14T08:12:34"
signal_avsandare_nummer: "+46701234567"
signal_avsandare_id: "b1f2c3d4-5e6f-7a8b-9c0d-1e2f3a4b5c6d"
plats: "Vägren E4 avfart söderut"
lat: 59.25401
lon: 17.69812
sagesman: CQ
location: "59.25401,17.69812"
---

**TNR:** 140755

**Stund:** 2026-02-14 07:55

**Ställe:** Vägren E4 avfart söderut

**Styrka:** 1 fordon, 1 person

**Slag:** Fordon + person

**Sysselsättning:** Långsam passage, andra varvet inom 25 min.

**Symbol:** mörkröd Toyota Avensis, reg [[..G41.]]. Två män, medelålders. Delvis synlig [[logotyp-fragment DGE]] på bakrutan.

**Sagesman:** CQ
```
