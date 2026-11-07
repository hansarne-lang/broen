# Broen – flere agenter på flere PC-er

Agentene (Claude og Codex på tre PC-er) sender meldinger og filer til hverandre gjennom en delt mappe på nettverksdisken. På hver PC kjører en **vaktmester**, som vekker agentene headless. **Monitoren** er en nettside der du følger med, korrigerer og sender meldinger selv.

## Kom i gang

1. Last ned: **Code → Download ZIP** på GitHub, eller `git clone https://github.com/hansarne-lang/broen.git`.
2. **Raskest:** trykk Win+R på hver PC og lim inn (bytt `pc1` med navnet på PC-en):
   ```
   powershell -ExecutionPolicy Bypass -NoExit -Command "$env:BROEN_PC='pc1'; irm https://raw.githubusercontent.com/hansarne-lang/broen/main/oppsett.ps1 | iex"
   ```
   Uten `BROEN_ROT` settes PC-en opp i **solo-modus** (lokal mappe, Claude + Codex på samme maskin, monitor på localhost). Med nettverksdisk: legg til `$env:BROEN_ROT='\\NAS-PC\broen';` foran `irm`.
   Alternativt: dobbeltklikk `installer.bat` på hver PC. Den sjekker Python, Git og Node, installerer Claude Code og Codex CLI og lager `broen.json`.
3. Følg **Oppsett** under.

Krav: Windows, Python 3.11+, Git, Node.js, et Claude-abonnement (Claude Code) og et ChatGPT-abonnement (Codex).

## Filer

| Fil | Hva den gjør |
|---|---|
| `felles.py` | Meldingsformat og levering (pause, rundegrense, STOPP) |
| `vaktmester.py` | Kjører på hver PC og starter `claude -p` / `codex exec` når det kommer post |
| `monitor.py` + `monitor.html` | Overvåkningssiden (port 8765) |
| `deltakere.json` | Rollene. Ligger **på nettverksdisken** og er felles for alle |
| `broen.eksempel.json` | Mal for konfigurasjonen på hver PC |
| `installer.bat` | Sjekker og installerer det som trengs på en PC |
| `start-*.bat` | Start med dobbeltklikk |

## Oppsett

**1. NAS-PC-en (den med Proton VPN)**
1. Lag mappen `broen` og del den på nettverket med lese- og skrivetilgang for brukerne på de tre PC-ene.
2. Slå på LAN-tilgang i Proton VPN (innstillingen for å tillate LAN-tilkoblinger) og gi PC-en fast IP.
3. Test fra en annen PC: `dir \\NAS-PC\broen`, både med VPN-en på og av.
4. Kopier `deltakere.json` inn i `\\NAS-PC\broen\` og tilpass rollene.

**2. Git-repo for koden**
- Enklest er et bart repo på disken: `git init --bare \\NAS-PC\broen-git\minapp.git`. Hver PC kloner fra det.
- Legg `.broen-inn/`, `.broen-ut/` og `.broen-svar.txt` i `.gitignore`.

**3. På hver av de tre PC-ene**
1. Installer Python 3.11 eller nyere og Git.
2. Installer Claude Code (`npm i -g @anthropic-ai/claude-code`, eller den offisielle installasjonen) og Codex CLI (`npm i -g @openai/codex`).
3. Kjør `claude` og `codex` én gang hver for å logge inn.
4. Klon repoet. Kjør deretter `claude` én gang **i repomappen**, så den har godtatt mappen.
5. Kopier Broen-filene til for eksempel `C:\broen\`. Lag `broen.json` fra eksempelet, med riktig `pc`, agentnavn og `repo`-sti.
6. Dobbeltklikk `start-vaktmester.bat`.

**4. Monitoren** kjører på én PC, gjerne NAS-PC-en: `start-monitor.bat`. Fra de andre maskinene åpner du `http://NAS-PC:8765`. Sett `monitor_token` hvis du vil ha passord.

## Slik bruker du det

1. I monitoren velger du **Ny tråd**, gir tråden et navn og skriver oppgaven til koordinatoren (`pc1-claude`).
2. Agentene jobber videre på egen hånd. Du ser trådene oppdatere seg hvert tredje sekund.
3. **📥 Til deg** viser spørsmål og ferdigmeldinger fra agentene. Trykk **Svar**, så går svaret rett inn i tråden.
4. **Korrigere:** Skriv i tråden til hvilken som helst agent. Meldingen din nullstiller rundetelleren.
5. **Godkjenne før levering:** Kryss av for **Pause** på tråden. Da havner alle agentmeldingene under **✋ Holdt tilbake**, der du kan redigere tekst og mottaker og trykke **Slipp videre**, eller slette meldingen.
6. **STOPP alt** stopper all levering umiddelbart. Agenter som er midt i en jobb, får gjøre den ferdig, men svaret deres blir holdt tilbake.

## «Er alle grønne?»

Knappen øverst til høyre har en prikk som viser totalstatus hele tiden: grønn, gul eller rød. Trykker du på knappen, får du detaljene.

**Rask sjekk** skjer automatisk og bruker ingen kvote:
- **Puls hvert 15. sekund** fra hver vaktmester. Kommer det ingen puls på over 60 sekunder, blir agenten rød.
- **Selvsjekk hvert 5. minutt:** Vaktmesteren sjekker at `claude`/`codex` finnes og svarer på `--version`, at repoet finnes og at `git ls-remote origin` svarer. Den sjekker også at PC-en kan skrive til nettverksdisken.
- **Siste agentkjøring:** Feilet den, blir agenten rød til neste vellykkede kjøring.

**Dyp sjekk** gjøres med en knapp, per agent eller for alle. Agenten blir startet med en ekte forespørsel og må svare `PONG`. Det bekrefter at innlogging og kvote virker, og koster en liten forespørsel per agent.

Fargene betyr:
- **Rød:** Noe må fikses.
- **Gul:** Alt kjører, men noe trenger oppmerksomhet, for eksempel at STOPP er på, at meldinger venter på deg eller at det er lang kø.
- **Grønn:** Alt er i orden.

Svaret finnes også som JSON på `GET /api/helse`, med feltet `alle_gronne: true/false`. Det kan du bruke fra andre verktøy.

## Sikringer

- **Rundegrense** (`maks_runder`, standard 20): Meldinger etter så mange runder uten innblanding fra deg blir holdt tilbake.
- **Tidsavbrudd** per agentkjøring (`tidsavbrudd_sekunder`).
- **Ugyldig svar eller krasj** fra en agent: Utdataene sendes til deg som et spørsmål.
- **Feil mottaker:** Meldingen sendes til deg.
- **Ferdigmeldinger:** Bare koordinatoren kan melde `ferdig` til deg.
- **Krasj i vaktmesteren:** Halvbehandlede meldinger legges tilbake i køen ved neste oppstart.

## Tilpasning

- **Tillatelser:** Claude får som standard lese, redigere og skrive filer og kjøre `git`. Vil du gi flere rettigheter, legger du inn `"kommando": [...]` på agenten i `broen.json`. `"kommandoer": {"claude": [...]}` gjelder alle agentene av den typen. `{svarfil}` byttes ut med en midlertidig fil.
- **Codex** kjører med `-a never exec -s workspace-write`, som betyr at den kan skrive i repoet uten å spørre, men ikke utenfor. Derfor kopierer vaktmesteren vedlegg inn og ut via `.broen-inn` og `.broen-ut`.
- **Kjør vaktmesteren ved oppstart:** Legg en snarvei til `start-vaktmester.bat` i `shell:startup`.
