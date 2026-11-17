# Pligt-pilot

Pligter, penge og ønsker til hele familien, som en Home Assistant add-on.

Børnene åbner et personligt link på telefon eller tablet. Ingen HA-konto,
ingen kodeord. Du godkender med ét tryk.

> Status: første version (v0.1). Testet mod en simuleret Home Assistant, men
> endnu ikke på en rigtig installation. Udkastet til skærmene ligger i `design/`.

## Installation

1. I Home Assistant: **Indstillinger → Add-ons → Add-on butik → ⋮ → Repositories**.
2. Tilføj `https://github.com/Clahen86/Pligt-pilot`.
3. Installér **Pligt-pilot**, start den og åbn **Pligter** i sidemenuen.

Se `pligt-pilot/DOCS.md` for indstillinger.

## Mål

- **Super nemt for børnene.** Højst tre tryk: åbn, tryk på opgaven, tryk "Færdig".
- **Super nemt for forældrene.** Godkend eller afvis fra en notifikation.
- **Opsætning på få minutter.** Appen ser huset og rummene i Home Assistant og
  foreslår opgaver, som man slår til eller fra. Man kan skrive sine egne.
- **Rigtige kroner.** Pris pr. opgave, saldo pr. barn og ugegraf.
- **Ugens helt.** Konkurrence med point efter alder og en bonus.

## Nyt i 0.9
- **Forældreside med eget link:** hver forælder kan få et personligt link og styre alt det samme som i Home Assistant, direkte fra sin telefon uden at logge ind.

## Nyt i 0.8
- **Flere sprog:** dansk, engelsk, tysk, svensk og norsk. Forældresiden følger husets sprog, og hvert barn kan have sit eget. Beskeder på telefonen kommer på modtagerens sprog.

## Nyt i 0.7
- **Belønninger:** børnene kan bruge kroner på ting, du selv vælger (skærmtid, fredagsfilm). Du svarer ja eller nej.
- **Ønsker:** et barn kan skrive et ønske, og du kan med ét tryk gøre det til barnets sparemål.
- **Dage i træk:** en lille bonus, når et barn har gjort noget 5 dage i træk.
- **Udbetal til alle** med ét tryk.
- **Backup:** hent al data som en fil.
- **Gode råd:** korte hint, fx hvis et barn ikke har åbnet siden i flere dage, eller en opgave tit bliver misset.

## Nyt i 0.6
- **Startpakke:** ét tryk opretter opgaver, der passer til børnenes alder.
- **Godkend alle:** godkend alt, der venter, med ét tryk (billeder ses først).
- **QR-kode:** hvert barn kan scanne sit link direkte fra skærmen.
- **Kopi af opgave:** lav en kopi af en opgave og ret den til.
- **Søndagsopsummering:** hver søndag kl. 18 får forælderen en besked om ugens opgaver og penge.

## Nyt i 0.5
- **Ugens boss:** hele familien slår en boss sammen. Hver godkendt opgave er et slag, og når bossen er besejret kan forælderen give en bonus til dem, der hjalp.
- **Karakter der vokser:** hvert barn har en fugl, der udvikler sig fra æg til Pligtlegende og får kasket, solbriller, kappe og krone.
- **Overraskelsesopgave:** nogle dage dukker en ekstra opgave op med dobbelt pris, der kun er åben i 90 minutter.
- **Bytte:** børn kan give en opgave til en søskende, evt. mod betaling.
- **Rimelighedstjek:** appen siger til, hvis en pris virker for høj eller for lav.
- **Sæsonopgaver:** fx løv om efteråret og snerydning om vinteren, kun aktive i deres sæson.

## Nyt i 0.4

- Beskeder direkte fra børnenes link, uden app: web-push over https med et gratis DuckDNS-certifikat (ingen åbne porte). Se `pligt-pilot/DOCS.md`.
- Appen finder selv måleren til vaskemaskine, tørretumbler og opvaskemaskine.

## Nyt i 0.3

- Fødselsdato i stedet for alder. Alderen følger med, og opgaver låses op af sig selv.
- Huset opretter opgaver: når vaskemaskinen er færdig, får børnene "Flyt tøj til tørretumbleren". Færdig tørretumbler giver "Tag ud og fold".
- Besked til børnene ved ledige opgaver, godkendelse, afvisning og påmindelse. Gratis via appen ntfy, uden HA-app og uden https.
- Tryk på forælderens besked åbner appen.
- Foto som bevis, serier ("5 i træk"), mærker, familiemål, lommepenge, træk for glemte opgaver, bonus for perfekt uge og overblik pr. måned.
- En lampe kan blinke grønt, når du godkender.

## Nyt i 0.2

- Pauseknap pr. barn (ferie eller sygdom).
- Opgaver kun til bestemte børn.
- Fortryd en godkendelse, og en historik over penge ind og ud.
- Sparemål pr. barn med en bjælke på barnets skærm.
- Opgaver, der kan laves flere gange pr. dag eller uge.

## Første version (v1)

1. Personligt link pr. barn (ingen HA-login).
2. Opgaver med pris og godkendelse.
3. Opsætning, der foreslår opgaver ud fra rum og enheder i HA.
4. Saldo i kroner, ugegraf og "Ugens helt".

## Senere (v2)

- Huset opretter opgaver selv (fx "Hæng tøjet op", når vaskemaskinen er færdig).
- NFC-tags og sensorer, så opgaver meldes færdige uden app.
- Energibonus i samarbejde med Energy Pilot.
- Ønsker til huset ("Bilen klar kl. 7", "Det er for koldt") med faste grænser.

## Eksisterende løsninger (undersøgt 17. nov. 2026)

KidsChores, ChoreOps, TaskMate og Choremander findes allerede til HA. De kræver
typisk en HA-konto til børnene. Det er den forskel, vi bygger på.

## Samspil med andre projekter

Dette repo er selvstændigt og ændrer intet i Energy Pilot, Heat-pilot eller andre
repos.

## Licens

MIT
