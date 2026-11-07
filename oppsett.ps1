# Broen - oppsett av en PC (Windows PowerShell 5.1+)
#
# Kjor fra Win+R (eller en PowerShell):
#   powershell -ExecutionPolicy Bypass -NoExit -Command "$env:BROEN_PC='pc1'; irm https://raw.githubusercontent.com/hansarne-lang/broen/main/oppsett.ps1 | iex"
#
# Valgfrie miljovariabler:
#   BROEN_PC       navn paa PC-en (pc1, pc2, pc3)                 standard: pc1
#   BROEN_MAPPE    hvor alt installeres                            standard: %USERPROFILE%\Broen
#   BROEN_ROT      nettverksdisken, f.eks. \\NAS-PC\broen          standard: lokal mappe (solo-modus)
#   BROEN_GIT      kode-repo agentene skal klone                   standard: lokalt test-repo
#   BROEN_MONITOR  1 = start monitoren paa denne PC-en             standard: 1 i solo-modus, ellers 0
#
# Skriptet er ASCII-only med vilje (fungerer med irm | iex i PowerShell 5.1).

$ErrorActionPreference = 'Continue'
function Steg($t)  { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function OK($t)    { Write-Host "    [OK]  $t" -ForegroundColor Green }
function Adv($t)   { Write-Host "    [!]   $t" -ForegroundColor Yellow }
function Feil($t)  { Write-Host "    [FEIL] $t" -ForegroundColor Red }
function Har($c)   { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Skriv-Utf8($sti, $tekst) { [IO.File]::WriteAllText($sti, $tekst, (New-Object Text.UTF8Encoding $false)) }
function Ja($sporsmal) { $s = Read-Host "    $sporsmal [J/n]"; return ($s -eq '' -or $s -match '^[jJyY]') }

$Pc      = if ($env:BROEN_PC)    { $env:BROEN_PC }    else { 'pc1' }
$Mappe   = if ($env:BROEN_MAPPE) { $env:BROEN_MAPPE } else { Join-Path $HOME 'Broen' }
$Solo    = -not $env:BROEN_ROT
$Rot     = if ($env:BROEN_ROT)   { $env:BROEN_ROT }   else { Join-Path $Mappe 'rot' }
$Monitor = if ($env:BROEN_MONITOR) { $env:BROEN_MONITOR -eq '1' } else { $Solo }
$Kode    = Join-Path $Mappe 'broen'
$Repo    = Join-Path $Mappe 'prosjekt'
$Agenter = @("$Pc-claude", "$Pc-codex")

Write-Host "Broen-oppsett for $Pc" -ForegroundColor White
Write-Host "  Installasjon: $Mappe"
Write-Host "  Rot:          $Rot $(if ($Solo) { '(lokal - solo-modus)' } else { '(nettverksdisk)' })"
Write-Host "  Agenter:      $($Agenter -join ', ')"
New-Item -ItemType Directory -Force -Path $Mappe | Out-Null

# ---------------------------------------------------------------- 1. forutsetninger
Steg "1/7 Sjekker Python, Git og Node.js"
$py = $null
if (Har 'py') { try { & py -3 -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = @('py', '-3') } } catch {} }
if (-not $py -and (Har 'python')) { try { & python -c "import sys" 2>$null; if ($LASTEXITCODE -eq 0) { $py = @('python') } } catch {} }
$mangler = @()
if ($py) {
    $pyArgs = @($py | Select-Object -Skip 1)
    $ver = & $py[0] @pyArgs -c "import sys;print('%d.%d'%sys.version_info[:2])"
    if ([version]$ver -ge [version]'3.11') { OK "Python $ver" } else { Feil "Python $ver er for gammel (trenger 3.11+)"; $mangler += 'Python.Python.3.12' }
} else { Feil "Python mangler"; $mangler += 'Python.Python.3.12' }
if (Har 'git') { OK (git --version) } else { Feil "Git mangler"; $mangler += 'Git.Git' }
if (Har 'npm') { OK "Node.js $(node --version)" } else { Feil "Node.js mangler"; $mangler += 'OpenJS.NodeJS.LTS' }
if ($mangler) {
    if ((Har 'winget') -and (Ja "Installere $($mangler -join ', ') med winget?")) {
        foreach ($p in $mangler) { winget install -e --id $p --accept-source-agreements --accept-package-agreements }
        Adv "Ferdig. LUKK dette vinduet og kjor kommandoen paa nytt (PATH maa oppdateres)."
    } else {
        Adv "Installer det som mangler og kjor skriptet paa nytt."
    }
    return
}

# ---------------------------------------------------------------- 2. claude og codex
Steg "2/7 Sjekker Claude Code og Codex CLI"
if (-not (Har 'claude')) { Adv "Installerer Claude Code..."; npm install -g @anthropic-ai/claude-code }
if (-not (Har 'codex'))  { Adv "Installerer Codex CLI...";  npm install -g @openai/codex }
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
foreach ($c in 'claude', 'codex') {
    if (Har $c) { OK "$c $((& $c --version 2>$null) | Select-Object -Last 1)" } else { Feil "$c ble ikke funnet etter installasjon" ; return }
}

# ---------------------------------------------------------------- 3. Broen-koden
Steg "3/7 Henter Broen fra GitHub"
if (Test-Path (Join-Path $Kode '.git')) { git -C $Kode pull --quiet; OK "Oppdatert $Kode" }
else { git clone --quiet https://github.com/hansarne-lang/broen $Kode; OK "Klonet til $Kode" }

# ---------------------------------------------------------------- 4. rot / nettverksdisk
Steg "4/7 Sjekker rot-mappen"
if ($Rot -match '^(\\\\[^\\]+\\[^\\]+)' -and -not (Test-Path $Rot)) {
    $del = $Matches[1]
    Adv "Faar ikke tilgang til $del - logger paa (bruk brukernavn og passord fra NAS-PC-en)"
    net use $del /persistent:yes
}
try {
    New-Item -ItemType Directory -Force -Path $Rot -ErrorAction Stop | Out-Null
    $test = Join-Path $Rot ".skrivetest-$Pc"; Set-Content $test 'ok' -ErrorAction Stop; Remove-Item $test -ErrorAction Stop
    OK "$Rot er skrivbar"
} catch {
    Feil "Kommer ikke til $Rot : $($_.Exception.Message)"
    Adv "Sjekk deling/rettigheter, og at Proton VPN tillater LAN-tilkoblinger paa NAS-PC-en."
    return
}
$delt = Join-Path $Rot 'deltakere.json'
if (-not (Test-Path $delt)) {
    if ($Solo) {
        $d = Get-Content (Join-Path $Kode 'deltakere.json') -Raw | ConvertFrom-Json
        $roller = [ordered]@{}
        $roller["$Pc-claude"] = "Koordinator og utvikler. Tar imot oppgaver fra haj, gjor kodearbeidet, bestiller grafikk fra $Pc-codex og melder 'ferdig' til haj."
        $roller["$Pc-codex"]  = "Grafikk og ressursfiler, samt mindre kodeoppgaver fra $Pc-claude. Leverer filer som vedlegg."
        Skriv-Utf8 $delt (@{ koordinator = "$Pc-claude"; agenter = $roller } | ConvertTo-Json -Depth 5)
        OK "Laget deltakere.json for solo-modus"
    } else {
        Copy-Item (Join-Path $Kode 'deltakere.json') $delt
        Adv "Kopierte standard deltakere.json til nettverksdisken - tilpass rollene der."
    }
} else { OK "deltakere.json finnes allerede" }

# ---------------------------------------------------------------- 5. kode-repo for agentene
Steg "5/7 Kode-repo for agentene"
$GitUrl = $env:BROEN_GIT
if (-not $GitUrl) {
    $bare = Join-Path $Rot 'git\prosjekt.git'
    if (-not (Test-Path $bare) -and (Test-Path (Join-Path $Repo '.git'))) {
        git init --quiet --bare --initial-branch=main $bare
        git -C $Repo push --quiet $bare HEAD:refs/heads/main
        OK "Flyttet eksisterende prosjekt til $bare"
    }
    if (-not (Test-Path $bare)) {
        git init --quiet --bare --initial-branch=main $bare
        $tmp = Join-Path $env:TEMP "broen-init-$(Get-Random)"
        git clone --quiet $bare $tmp 2>$null
        Skriv-Utf8 (Join-Path $tmp 'README.md') "# Testprosjekt for Broen`n"
        Skriv-Utf8 (Join-Path $tmp '.gitignore') ".broen-inn/`n.broen-ut/`n.broen-svar.txt`n"
        git -C $tmp add -A
        git -C $tmp -c user.name='Broen' -c user.email='broen@localhost' commit --quiet -m 'Start'
        git -C $tmp push --quiet origin HEAD:refs/heads/main 2>$null
        Remove-Item -Recurse -Force $tmp
        OK "Laget test-repo $bare"
    }
    $GitUrl = $bare
}
if (-not (Test-Path (Join-Path $Repo '.git'))) { git clone --quiet $GitUrl $Repo; OK "Klonet til $Repo" }
else {
    $naa = git -C $Repo remote get-url origin 2>$null
    if ($naa -ne $GitUrl) { git -C $Repo remote set-url origin $GitUrl; git -C $Repo fetch --quiet origin; git -C $Repo branch --quiet -u origin/main 2>$null; OK "Pekte $Repo om til $GitUrl" }
    else { OK "$Repo finnes" }
}
$gi = Join-Path $Repo '.gitignore'
$innhold = if (Test-Path $gi) { Get-Content $gi -Raw } else { '' }
foreach ($l in '.broen-inn/', '.broen-ut/', '.broen-svar.txt') { if ($innhold -notmatch [regex]::Escape($l)) { Add-Content $gi $l } }
if (-not (git -C $Repo config user.name)) {
    git -C $Repo config user.name "Broen $Pc"; git -C $Repo config user.email "broen-$Pc@localhost"
}
OK "Repo klart"

# ---------------------------------------------------------------- 6. broen.json
Steg "6/7 Skriver broen.json"
$agentCfg = [ordered]@{}
$agentCfg["$Pc-claude"] = [ordered]@{ type = 'claude'; repo = $Repo }
$agentCfg["$Pc-codex"]  = [ordered]@{ type = 'codex';  repo = $Repo }
$cfg = [ordered]@{
    rot = $Rot; pc = $Pc; agenter = $agentCfg
    maks_runder = 20; poll_sekunder = 5; tidsavbrudd_sekunder = 1800
    historikk_meldinger = 30; selvsjekk_minutter = 5; monitor_port = 8765; monitor_token = ''
}
Skriv-Utf8 (Join-Path $Kode 'broen.json') ($cfg | ConvertTo-Json -Depth 5)
OK (Join-Path $Kode 'broen.json')

# ---------------------------------------------------------------- 7. innlogging og start
Steg "7/7 Innlogging og start"
$svar = Read-Host "    Er claude og codex allerede logget inn paa denne PC-en? [j/N]"
$loggetInn = $svar -match '^[jJyY]'
if (-not $loggetInn) {
Write-Host "    Begge verktoyene maa vaere logget inn for at agentene skal kunne jobbe."
Write-Host "    Jeg aapner to vinduer. Logg inn i begge, og lukk dem naar du er ferdig:"
Write-Host "      - Claude: godta mappen ($Repo) og logg inn, skriv /exit naar du er inne"
Write-Host "      - Codex:  'codex login'"
Start-Process powershell -WorkingDirectory $Repo -ArgumentList '-NoExit', '-Command', 'claude'
Start-Process powershell -WorkingDirectory $Repo -ArgumentList '-NoExit', '-Command', 'codex login'
Read-Host "    Trykk Enter her naar du er logget inn i begge"
}

$pyArg = ($py | Select-Object -Skip 1) -join ' '
if ($Monitor) {
    Start-Process powershell -WorkingDirectory $Kode -ArgumentList '-NoExit', '-Command', "$($py[0]) $pyArg monitor.py broen.json"
    OK "Monitor startet: http://localhost:8765"
}
Start-Process powershell -WorkingDirectory $Kode -ArgumentList '-NoExit', '-Command', "while (`$true) { $($py[0]) $pyArg vaktmester.py broen.json; Write-Host 'Starter paa nytt om 10 s'; Start-Sleep 10 }"
OK "Vaktmester startet for $($Agenter -join ', ')"

$snarvei = Join-Path ([Environment]::GetFolderPath('Startup')) "Broen vaktmester $Pc.lnk"
if (-not (Test-Path $snarvei) -and (Ja "Starte vaktmesteren automatisk naar PC-en starter?")) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($snarvei)
    $s.TargetPath = Join-Path $Kode 'start-vaktmester.bat'; $s.WorkingDirectory = $Kode; $s.Save()
    OK "Snarvei lagt i Oppstart"
}

if ($Monitor) {
    Start-Sleep 8
    Start-Process 'http://localhost:8765'
    try {
        $h = Invoke-RestMethod 'http://localhost:8765/api/helse'
        Steg "Helsesjekk: $($h.niva.ToUpper())"
        foreach ($a in $h.agenter) {
            Write-Host "    $($a.agent): $($a.niva)"
            foreach ($p in $a.punkter) { if ($p.niva -ne 'ok') { Write-Host "       - $($p.tekst)" -ForegroundColor Yellow } }
        }
        Write-Host "    (Selvsjekken trenger noen sekunder ved forste start - se 'Er alle gronne?' i monitoren.)"
    } catch { Adv "Fikk ikke kontakt med monitoren ennaa - aapne http://localhost:8765" }
}
Write-Host ""
Write-Host "Ferdig. Gaa til monitoren, trykk 'Er alle gronne?' og deretter 'Dyp sjekk av alle'." -ForegroundColor Green
