# Pligt-pilot

Pligter, penge og ønsker til hele familien, som en Home Assistant add-on.

Børnene åbner et personligt link på telefon eller tablet. Ingen HA-konto,
ingen kodeord. Du godkender med ét tryk.

> Status: idé- og designfase. Ingen kode endnu. Udkastet til skærmene ligger i
> `design/`.

## Mål

- **Super nemt for børnene.** Højst tre tryk: åbn, tryk på opgaven, tryk "Færdig".
- **Super nemt for forældrene.** Godkend eller afvis fra en notifikation.
- **Opsætning på få minutter.** Appen ser huset og rummene i Home Assistant og
  foreslår opgaver, som man slår til eller fra. Man kan skrive sine egne.
- **Rigtige kroner.** Pris pr. opgave, saldo pr. barn og ugegraf.
- **Ugens helt.** Konkurrence med point efter alder og en bonus.

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
