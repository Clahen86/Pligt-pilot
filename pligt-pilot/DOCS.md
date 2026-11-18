# Pligt-pilot

## Kom i gang

1. Start add-onen og åbn **Pligter** i sidemenuen.
2. Tilføj børnene under **Børn** (navn og alder).
3. Under **Opgaver** kan du trykke **Vis forslag**. Appen kigger på husets rum og foreslår opgaver, som du vælger til eller fra.
4. Kopiér hvert barns personlige link, send det til barnet, og vælg "Føj til hjemmeskærm" i browseren.

## Opgaver

Fanen **Opgaver** viser dine opgaver i to grupper: **Faste** og **Når jeg giver dem**. Hver opgave fylder én linje med dage eller hyppighed, pris, *hver sin* og rummet. Tryk på linjen for at rette opgaven, eller tryk **+ Ny opgave**. Pligter, maddage og husets opgaver står ikke i listen.

Arket har **Navn**, **Pris**, **Hvornår?**, **Hvem?** (*Hver sin* eller *Én af børnene*) og **Gem**. Under **Flere valg** finder du alder, hvor tit, antal gange, årstid, foto, overraskelse, hurtigknap, billede og bestemte børn, og nederst **Kopiér** og **Slet**. Slet spørger først.

## Fast eller kun når jeg giver den

Under **Hvornår?** i arket vælger du, hvornår børnene får opgaven:

- **Faste dage:** den kommer af sig selv, så tit som gentagelsen siger. Vælg evt. dagene (Man–Søn), eller **Hver dag**. Et tryk på en dag gør opgaven fast. En daglig opgave kommer så kun på de dage, og en ugentlig kommer på den første valgte dag og er åben resten af ugen. Ingen dage valgt betyder alle dage. Træk for glemte opgaver tæller kun de dage, opgaven blev givet.
- **Når jeg giver den:** børnene ser den aldrig af sig selv. Du giver den med hurtigknapperne eller **+ Tilføj**. Den står under *Når jeg giver dem* i listen.

## Giv en opgave hurtigt

Øverst på **Oversigt** står **Giv en opgave** med op til 8 knapper: dem, du har fastgjort, først, og derefter dem, I bruger mest. Tryk på en, og vælg barnet eller **Først til mølle**. Så er den sendt for i dag.

Tryk på **+ Tilføj** for at vælge, hvilke opgaver der altid skal stå som knap. Et flueben betyder fastgjort. Tryk igen for at fjerne det, og tryk **Færdig**. Du fjerner også en fastgjort knap ved at holde den inde et øjeblik, eller med **Fjern fra hurtigknapperne**, når du har trykket på den. Det samme valg findes som **Vis som hurtigknap** på opgaven.

Hver knap har et lille mærke:

- **Alle**: hvert barn laver sin egen (fx *Red din seng*, *Smør madpakke*, *Lektier*). Ét tryk sender den til alle børn, der må få den (alder, pause og valgte børn tæller med).
- **Én**: én af børnene gør det (fx *Dæk bord*, *Tøm opvaskeren*). Tryk og vælg barnet eller **Først til mølle**.

Appen gætter ud fra opgavens navn. Er gættet forkert, så ret **Hvem?** i opgavens ark. Dit valg vinder, også hvis du senere ændrer navnet.

## Årstid, hyppighed og vejr

Appen læser opgavens navn og sætter selv måneder og hyppighed:

| Opgave | Måneder | Højst |
|---|---|---|
| Græs og plæne | april–oktober | én gang om ugen |
| Hæk | maj–september | hver 3. uge |
| Løv og blade | september–november | én gang om ugen |
| Havemøbler og trampolin, vanding ude | april/maj–september | |
| Sne og glat føre | december–marts | kun når det har sneet |

Uden for månederne gives opgaven ikke ud, og ingen trækkes for den. Vælger du selv en sæson på opgaven, bruges din i stedet.

Har Home Assistant en vejr-entity (fx `weather.forecast_home`), venter udendørs opgaver på en tør dag ved regn, storm eller hagl, uden træk. Sneopgaver kommer kun, når det har sneet inden for et døgn. Uden vejr-entity gøres intet anderledes.

## Huset opretter opgaver

Under fanen **Huset** vælger du en maskine (fx vaskemaskine) og den måler eller kontakt, der viser, om den kører. Bedst er en stikkontakt med effektmåling i watt. Når maskinen har kørt og så har været stille i ca. 3 minutter, får børnene en ledig opgave. Den første, der tager den, får den.

Finder appen ikke din vaskemaskine eller tørretumbler på navnet, viser Huset en liste over alle effektmålere i hjemmet med rum og aktuel værdi. Tænd maskinen, se hvilken måler der stiger, vælg maskinen og tryk **Brug den**.

Lav fx to regler: vaskemaskinen giver "Flyt tøj til tørretumbleren", og tørretumbleren giver "Tag tøj ud og fold det".

En ledig opgave, som ingen har taget, forsvinder igen, når
- lågen åbnes: en dørsensor (binary_sensor) på reglen under **Huset**. Passer præcis én sensor til maskinen (fx "Vaskemaskine låge"), vælger appen den selv. Ellers trykker du **Vælg dørsensor** ved maskinen: søg på navn, rum eller id. Sensorer i maskinens rum står øverst, og om døren er åben eller lukket ses live, så du kan prøve lågen. Fjerner du den, sætter appen den ikke ind igen.
- maskinen starter igen.
- den har ligget i det antal timer, du vælger under **Huset** (standard 4).

En sensor, der er "unavailable" eller "unknown", fjerner aldrig noget. Har et barn taget opgaven, bliver den liggende.

Tryk **Ret** på en regel for at ændre opgavens navn og pris. En ledig opgave fra reglen får det nye med det samme. Oversigt viser under **Lige nu** maskineopgaverne, og om de er ledige, eller hvem der har taget dem.

## Forslag fra børnene

Børnene kan trykke **Tag et billede** under "Foreslå en opgave" (kameraet åbner direkte) og evt. skrive, hvad der skal laves. Du får en besked, og forslaget står under **Til godkendelse** med billedet. Giv det et navn og en pris, og tryk **Giv den** (barnet, der foreslog den, får opgaven i dag) eller **Nej tak**. Hvert barn kan have tre forslag, der venter.

## Pligter uden betaling

Under **Opgaver → Pligter uden betaling** sender du en pligt til et eller flere børn med en frist (dato og evt. klokkeslæt) og et træk. Barnet ser den med mærket **Pligt** og fristen. Er den ikke meldt færdig inden fristen, trækkes beløbet (aldrig mere end barnets saldo).

## Lommepenge med krav

Under **Børn → Indstillinger** kan du sætte en alder (fx 13) og et antal godkendte opgaver pr. uge (fx 5). Børn på eller over alderen får kun ugens lommepenge, hvis de har nok godkendte opgaver i ugen. Ellers holdes de tilbage, og barnet får besked. Godkender du opgaverne lidt for sent, kommer pengene alligevel. Barnet ser fremskridtet på sin side. Alder 0 slår kravet fra.

## Samspil med Hus-chat og Madplan

Kræver integrationen **Pligt-pilot**. Den lytter efter `hus_chat_machine` og `madplan_cook` og sender dem videre til add-on'en.
- Tømmes en maskine (eller tages den) i Hus-chat, fjernes en ledig husopgave for samme slags maskine.
- Et barn ser "Tag den i Pligter" i Hus-chat (og i beskeden på telefonen) i stedet for "Jeg tager den". Knappen åbner barnets egen side med maskineopgaven fremhævet. Kræver en tændt regel for den slags maskine. Voksne tager den i chatten som før.
- Navnet fra Madplan og Hus-chat passer, når det er helt ens med barnets navn, eller med det første ord i det ("Dennis" passer på "Dennis opgaver"). Passer flere børn, bruges det ikke.
- Giver Madplan et barn en maddag, får barnet opgaven "Maddag: <ret>" på dagen med opskrift og ingredienser. Prisen vælges under Indstillinger (standard 0 = en pligt uden betaling).
- Pligt-pilot fyrer selv `pligt_pilot_task` (taken, done, removed) for husopgaver, maddage og pligter.

Findes de andre apps ikke, sker der ingenting.

## Links der virker ude (Nabu Casa)

Installér integrationen **Pligt-pilot** (fra samme repo via HACS) og tilføj den under Indstillinger → Enheder og tjenester. Så går linkene gennem Home Assistant: `https://….ui.nabu.casa/pligter/k/…`. De virker overalt, med https, uden åbne porte og uden login. Integrationen fortæller selv add-on'en adressen, så `public_url` ikke skal udfyldes. Uden Nabu Casa bruges Home Assistants egen adresse udefra, hvis den findes. Ellers virker linkene kun hjemme som før.

Med Nabu Casa kan du springe Duck DNS-afsnittet herunder over: beskeder direkte fra linket virker også, fordi adressen er https.

## Beskeder direkte fra linket (uden app)

Når børnenes side kører med https, kan barnet trykke **Slå beskeder til** på sin side. Så kommer beskederne som almindelige notifikationer på telefonen, uden ntfy og uden Home Assistant-appen. Det kræver et gyldigt certifikat. Det kan du få gratis og uden at åbne porte på routeren:

1. Gå til duckdns.org, log ind og opret et navn, fx `familien-hansen`. Gem din token.
2. Installér add-onen **Duck DNS** i Home Assistant og skriv:
   ```
   lets_encrypt:
     accept_terms: true
   domains:
     - familien-hansen.duckdns.org
   token: DIN-TOKEN
   ipv4: 192.168.1.50
   ```
   Skriv Home Assistants adresse hjemme i stedet for 192.168.1.50. Du finder den under Indstillinger → System → Netværk. Vis skjulte valgmuligheder, hvis `ipv4` ikke står der. Navnet peger så på dit hjem og ikke på internettet.
3. Start Duck DNS. Loggen skal vise, at certifikatet er lavet. Det lægges i mappen `/ssl`.
4. I Pligt-pilot skriver du `public_url: https://familien-hansen.duckdns.org:8099` og genstarter. Loggen skal sige "Børnesiden bruger https".
5. Send børnene de nye links (de starter med https). Barnet åbner linket hjemme på wifi og trykker **Slå beskeder til**.
   - iPhone: Åbn linket i Safari, tryk på del-knappen, vælg Føj til hjemmeskærm, og åbn siden derfra. Kræver iOS 16.4 eller nyere.
   - Android: Virker direkte i Chrome.

Hjælper det ikke:
- Åbner linket ikke derhjemme, skyldes det ofte routerens beskyttelse mod DNS-omdirigering. Tilføj `duckdns.org` som undtagelse. I en FRITZ!Box findes den under Hjemmenetværk → Netværk → Netværksindstillinger.
- Beskeden dukker op overalt, hvor telefonen har internet. Men et tryk på den åbner kun siden, når barnet er på hjemmets wifi.
- Certifikatet fornyes af Duck DNS cirka hvert andet måned. Appen læser det nye certifikat af sig selv.

## Beskeder til børnene

Hvis du ikke vil have https, kan du i stedet bruge ntfy. Under hvert barn slår du **Beskeder til barnets telefon** til. Så får barnet et hemmeligt emne. Barnet installerer den gratis app **ntfy** (App Store eller Google Play), trykker på + og skriver emnet. Det virker uden Home Assistant-appen og uden https.

Beskeder sendes, når der er en ny ledig opgave, når du godkender eller afviser, og til den tid, du har valgt til påmindelse. Er `public_url` udfyldt, åbner et tryk på beskeden barnets side.

Beskederne går gennem den åbne tjeneste ntfy.sh. Emnet er et langt tilfældigt navn, men ikke en adgangskode, så beskederne bør ikke indeholde noget privat. Du kan bruge din egen ntfy-server ved at ændre `ntfy_server`.

Har barnet Home Assistant-appen, kan du i stedet skrive barnets notifikationstjeneste, fx `mobile_app_emmas_tlf`.

## Forældre med eget link
Under Børn → Forældre kan du lave et personligt link til hver forælder (op til 6). Linket åbner den samme side, som du ser i Home Assistant, så man kan godkende, rette opgaver, udbetale og meget mere fra sin egen telefon uden at logge ind. Linket virker på samme adresse som børnenes (port 8099), så det virker kun hjemme på wifi, medmindre du har sat noget andet op.

Linket er som en adgangskode. Del det kun med voksne, og brug **Nyt link** eller **Fjern forælder**, hvis det kommer til at ligge forkert. Forældre med et link kan ikke hente backup eller se og ændre andre forældres links.

## Billeder på opgaverne
Appen gætter et ikon ud fra opgavens navn (på dansk, engelsk, tysk, svensk og norsk). Vil du vælge selv, trykker du på opgaven og vælger et billede under **Flere valg**. "Automatisk" går tilbage til appens gæt.

## Sprog
Dansk, engelsk, tysk, svensk og norsk. Husets sprog vælges under Indstillinger (Sprog), og hvert barn kan få sit eget under Børn. Beskeder sendes på modtagerens sprog. Startpakken og forslagene oprettes på husets sprog. Opgaver, du selv har skrevet, oversættes ikke.

Nye sprog tilføjes i `app/lang/strings*.txt`: én linje pr. tekst, dansk først og så de andre sprog adskilt af ` || `.

## Penge og belønninger
- **Belønninger:** under Opgaver, nederst. Tryk "Tilføj tre eksempler" for at komme i gang. Barnet trykker Køb, og du får en besked og svarer under Køb og ønsker på Oversigt. Pengene trækkes først, når du siger ja.
- **Ønsker:** barnet skriver, hvad det ønsker sig og hvad det koster. Du kan sætte det som sparemål.
- **Dage i træk:** bonussen (som standard 5 kr.) gives hver 5. dag i træk. Sæt den til 0 under Indstillinger for at slå den fra.
- **Backup:** "Hent backup af alt" nederst under Børn henter en fil med al data (ikke billederne). Gem den et sikkert sted. Den indeholder børnenes links.

## Gør det nemt
- **Startpakke:** på Oversigt (før du har opgaver) opretter knappen "Startpakke" opgaver, der passer til børnenes alder. Du kan slette dem eller ændre dem bagefter.
- **Godkend alle:** knappen vises over de ventende opgaver. Opgaver med billede godkendes ikke automatisk.
- **QR-kode:** under Børn, ved barnets link. Appen laver koden selv, uden internet.
- **Søndagsopsummering:** kræver `notify_service`. Kan slås fra under Indstillinger.

## Sjove ting
- **Ugens boss:** antal liv og bonus kan ændres under Indstillinger. Bonussen udbetales manuelt fra boss-kortet på Oversigt, når bossen er besejret.
- **Overraskelse:** sæt kryds ved "Overraskelse" på en opgave. Den bliver ikke en fast opgave, men dukker af og til op som en ledig opgave med dobbelt pris, der udløber efter 90 minutter.
- **Bytte:** børn kan tilbyde en opgave til en søskende. Det kan slås fra under Indstillinger.
- **Sæson:** vælg "Hvornår på året" på en opgave. Uden for sæsonen er den skjult uden straf.
- **Rimelighedstjek:** under prisen vises en note, hvis prisen afviger meget fra det typiske eller fra dine andre opgaver.

## Indstillinger

| Indstilling | Betydning |
| --- | --- |
| `notify_service` | Navn på din notifikationstjeneste, fx `mobile_app_min_telefon`. Du får besked, når et barn er færdig. |
| `weekly_goal` | Antal opgaver, der fylder ugens søjle helt. |
| `ntfy_server` | Valgfri. Standard er `https://ntfy.sh`. |
| `public_url` | Valgfri. Adressen børnene bruger, fx `http://homeassistant.local:8099`. Er den tom, bruges den adresse, du åbner siden fra. |

## Sikkerhed

Børnenes port (8099) viser kun børnenes egne sider. Forældreskærmen kan kun nås gennem Home Assistant. Hvert link er en tilfældig nøgle, og du kan lave et nyt link når som helst.
Åbn ikke port 8099 mod internettet. Brug VPN eller Nabu Casa, hvis børnene skal bruge appen uden for hjemmet.
