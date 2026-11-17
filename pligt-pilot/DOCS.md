# Pligt-pilot

## Kom i gang

1. Start add-onen og åbn **Pligter** i sidemenuen.
2. Tilføj børnene under **Børn** (navn og alder).
3. Under **Opgaver** kan du trykke **Vis forslag**. Appen kigger på husets rum og foreslår opgaver, som du slår til eller fra.
4. Kopiér hvert barns personlige link, send det til barnet, og vælg "Føj til hjemmeskærm" i browseren.

## Indstillinger

| Indstilling | Betydning |
| --- | --- |
| `notify_service` | Navn på din notifikationstjeneste, fx `mobile_app_min_telefon`. Du får besked, når et barn er færdig. |
| `weekly_goal` | Antal opgaver, der fylder ugens søjle helt. |
| `public_url` | Valgfri. Adressen børnene bruger, fx `http://homeassistant.local:8099`. Er den tom, bruges den adresse, du åbner siden fra. |

## Sikkerhed

Børnenes port (8099) viser kun børnenes egne sider. Forældreskærmen kan kun nås gennem Home Assistant. Hvert link er en tilfældig nøgle, og du kan lave et nyt link når som helst.
Åbn ikke port 8099 mod internettet. Brug VPN eller Nabu Casa, hvis børnene skal bruge appen uden for hjemmet.
