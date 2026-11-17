# Pligt-pilot

## Kom i gang

1. Start add-onen og åbn **Pligter** i sidemenuen.
2. Tilføj børnene under **Børn** (navn og alder).
3. Under **Opgaver** kan du trykke **Vis forslag**. Appen kigger på husets rum og foreslår opgaver, som du slår til eller fra.
4. Kopiér hvert barns personlige link, send det til barnet, og vælg "Føj til hjemmeskærm" i browseren.

## Huset opretter opgaver

Under fanen **Huset** vælger du en maskine (fx vaskemaskine) og den måler eller kontakt, der viser, om den kører. Bedst er en stikkontakt med effektmåling i watt. Når maskinen har kørt og så har været stille i ca. 3 minutter, får børnene en ledig opgave. Den første, der tager den, får den.

Lav fx to regler: vaskemaskinen giver "Flyt tøj til tørretumbleren", og tørretumbleren giver "Tag tøj ud og fold det".

## Beskeder til børnene

Under hvert barn slår du **Beskeder til barnets telefon** til. Så får barnet et hemmeligt emne. Barnet installerer den gratis app **ntfy** (App Store eller Google Play), trykker på + og skriver emnet. Det virker uden Home Assistant-appen og uden https.

Beskeder sendes, når der er en ny ledig opgave, når du godkender eller afviser, og til den tid, du har valgt til påmindelse. Er `public_url` udfyldt, åbner et tryk på beskeden barnets side.

Beskederne går gennem den åbne tjeneste ntfy.sh. Emnet er et langt tilfældigt navn, men ikke en adgangskode, så beskederne bør ikke indeholde noget privat. Du kan bruge din egen ntfy-server ved at ændre `ntfy_server`.

Har barnet Home Assistant-appen, kan du i stedet skrive barnets notifikationstjeneste, fx `mobile_app_emmas_tlf`.

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
