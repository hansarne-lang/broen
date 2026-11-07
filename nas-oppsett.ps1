# Broen - del nettverksdisken paa NAS-/VPN-PC-en (kjores EN gang, som administrator)
#
# Win+R, lim inn, og trykk Ctrl+Shift+Enter (= kjor som administrator):
#   powershell -ExecutionPolicy Bypass -NoExit -Command "irm https://raw.githubusercontent.com/hansarne-lang/broen/main/nas-oppsett.ps1 | iex"
#
# Valgfritt: $env:BROEN_NAS_MAPPE='D:\broen' foran irm for aa legge mappen et annet sted.

function Steg($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }
function OK($t)   { Write-Host "    [OK]  $t" -ForegroundColor Green }
function Adv($t)  { Write-Host "    [!]   $t" -ForegroundColor Yellow }
function Feil($t) { Write-Host "    [FEIL] $t" -ForegroundColor Red }

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Feil "Maa kjores som administrator. Bruk Ctrl+Shift+Enter i Win+R."; return }

$Mappe = if ($env:BROEN_NAS_MAPPE) { $env:BROEN_NAS_MAPPE } else { 'C:\broen' }
$Bruker = "$env:USERDOMAIN\$env:USERNAME"

Steg "1/4 Mappe"
New-Item -ItemType Directory -Force -Path $Mappe | Out-Null
OK $Mappe

Steg "2/4 Deling"
$share = Get-SmbShare -Name 'broen' -ErrorAction SilentlyContinue
if ($share) { OK "Delingen 'broen' finnes allerede ($($share.Path))" }
else {
    New-SmbShare -Name 'broen' -Path $Mappe -FullAccess $Bruker | Out-Null
    OK "Delt som 'broen' med full tilgang for $Bruker"
}

Steg "3/4 Brannmur og nettverksprofil"
Set-NetFirewallRule -Group '@FirewallAPI.dll,-28502' -Enabled True -ErrorAction SilentlyContinue
OK "Fil- og skriverdeling er aapnet i brannmuren"
foreach ($p in Get-NetConnectionProfile) {
    if ($p.NetworkCategory -eq 'Public' -and $p.InterfaceAlias -notmatch 'Proton|WireGuard|OpenVPN|TAP|tun') {
        Set-NetConnectionProfile -InterfaceIndex $p.InterfaceIndex -NetworkCategory Private
        OK "Satt '$($p.InterfaceAlias)' til Privat nettverk"
    } else { OK "'$($p.InterfaceAlias)': $($p.NetworkCategory)" }
}

Steg "4/4 Adresser de andre PC-ene skal bruke"
$ip = Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -match '^(192\.168|10\.(?!2\.0\.)|172\.)' -and $_.InterfaceAlias -notmatch 'vEthernet|Proton|WireGuard|Loopback' }
foreach ($a in $ip) { Write-Host "    \\$($a.IPAddress)\broen    ($($a.InterfaceAlias))" -ForegroundColor White }
Write-Host ""
Write-Host "    De andre PC-ene logger paa delingen som: $Bruker (samme passord som her)."
Adv "Proton VPN: slaa paa innstillingen som tillater LAN-tilkoblinger, ellers kan delingen bli usynlig naar VPN-en er paa."
Write-Host ""
Write-Host "Ferdig." -ForegroundColor Green
