# Pligt-pilot

## Kom i gang

1. Start add-onen og åbn **Pligter** i sidemenuen.
2. Tilføj børnene under **Børn** (navn og alder).
3. Under **Opgaver** kan du trykke **Vis forslag**. Appen kigger på husets rum og foreslår opgaver, som du slår til eller fra.
4. Kopiér hvert barns personlige link, send det til barnet, og vælg "Føj til hjemmeskærm" i browseren.

## Huset opretter opgaver

Under fanen **Huset** vælger du en maskine (fx vaskemaskine) og den måler eller kontakt, der viser, om den kører. Bedst er en stikkontakt med effektmåling i watt. Når maskinen har kørt og så har været stille i ca. 3 minutter, får børnene en ledig opgave. Den første, der tager den, får den.

Lav fx to regler: vaskemaskinen giver "Flyt tøj til tørretumbleren", og tørretumbleren giver "Tag tøj ud og fold det".

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

## Sprog
Dansk, engelsk, tysk, svensk og norsk. Husets sprog vælges under Indstillinger (Sprog), og hvert barn kan få sit eget under Børn. Beskeder sendes på modtagerens sprog. Startpakken og forslagene oprettes på husets sprog. Opgaver, du selv har skrevet, oversættes ikke.

Nye sprog tilføjes i `app/lang/strings*.txt`: én linje pr. tekst, dansk først og så de andre sprog adskilt af ` || `.

## Penge og belønninger
- **Belønninger:** under Opgaver, nederst. Tryk "Tilføj tre eksempler" for at komme i gang. Barnet trykker Køb, og du får en besked og svarer under Køb og ønsker på Oversigt. Pengene trækkes først, når du siger ja.
- **Ønsker:** barnet skriver, hvad det ønsker sig og hvad det koster. Du kan sætte det som sparemål.
- **Dage i træk:** bonussen (som standard 5 kr.) gives hver 5. dag i træk. Sæt den til 0 under Indstillinger for at slå den fra.
- **Backup:** "Hent backup af alt" nederst under Børn henter en fil med al data (ikke billederne). Gem den et sikkert sted. Den indeholder børnenes links.

## Gør det nemt
- **Startpakke:** på Oversigt (før du har opgaver) opretter knappen "Startpakke" opgaver, der passer til børnenes alder. Du kan slå dem fra eller ændre dem bagefter.
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
