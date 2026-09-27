# Shared settings for hosting the recorder on this Windows PC. Dot-sourced by the other scripts.
# Override anything here in local\config.ps1 (not committed).

# Native tools (alembic, pg_ctl) log to stderr; under 'Stop' PowerShell 5.1 would treat that as fatal.
$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent $PSScriptRoot

# Postgres refuses to run from a path with non-ASCII characters, so data lives under C:\Users\Public.
$DataDir    = 'C:\Users\Public\mmohl-pg'
$PgBin      = Join-Path $DataDir 'pgsql\bin'
$PgData     = Join-Path $DataDir 'data'
$PgPort     = 5433
$SpoolDir   = Join-Path $DataDir 'spool'
$LogDir     = Join-Path $DataDir 'logs'
$BackendPort  = 8000
$FrontendPort = 3000

function Find-Tool([string]$name, [string[]]$candidates) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $candidates) {
        $hit = Get-ChildItem -Path $c -Filter "$name.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw "$name not found. Install it or set its path in local\config.ps1."
}

# "recorder" on the PC that records; "viewer" on other PCs, which only serve the page from the
# shared database (set $Role = 'viewer' in local\config.ps1 there).
$Role = 'recorder'

$Config = Join-Path $PSScriptRoot 'config.ps1'
if (Test-Path $Config) { . $Config }

$WingetPkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
if (-not $Uv)   { $Uv   = Find-Tool 'uv'   @("$WingetPkgs\astral-sh.uv*") }
if (-not $Node) { $Node = Find-Tool 'node' @("$env:ProgramFiles\nodejs") }
$toolDirs = @((Split-Path $Node), (Split-Path $Uv))
if ($Role -eq 'recorder') {
    if (-not $Ffmpeg) { $Ffmpeg = Find-Tool 'ffmpeg' @("$WingetPkgs\Gyan.FFmpeg*") }
    $toolDirs += (Split-Path $Ffmpeg)
}

# The database address comes from backend\.env (DATABASE_URL). Without one, the local Postgres
# on port $PgPort is used and started by these scripts.
function Get-DotEnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    foreach ($line in Get-Content -Path $file -Encoding UTF8) {
        if ($line -match "^\s*$key\s*=\s*(.+?)\s*$") { return $Matches[1].Trim('"') }
    }
    return $null
}
$DatabaseUrlFromEnv = Get-DotEnvValue (Join-Path $Repo 'backend\.env') 'DATABASE_URL'
$DatabaseUrl = if ($DatabaseUrlFromEnv) { $DatabaseUrlFromEnv } else {
    "postgresql+asyncpg://recorder:recorder@localhost:$PgPort/recorder?ssl=disable"
}
$UseLocalPostgres = $DatabaseUrl -match "@(localhost|127\.0\.0\.1):$PgPort/"

New-Item -ItemType Directory -Force -Path $SpoolDir, $LogDir | Out-Null

# Tools the backend spawns (ffmpeg) and npm/npx must be on PATH for child processes.
$env:PATH = (($toolDirs -join ';') + ";$env:PATH")

function Test-Port([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# Starts a hidden process that inherits none of this script's handles (Start-Process would pass on
# the caller's output pipe, so a terminal running start.ps1 would wait until the server exits).
# Output goes to $logFile through cmd.
function Start-Detached([string]$commandLine, [string]$workingDir, [string]$logFile) {
    $startup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $full = "cmd.exe /c `"$commandLine >> `"$logFile`" 2>&1`""
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $full; CurrentDirectory = $workingDir; ProcessStartupInformation = $startup
    }
    if ($r.ReturnValue -ne 0) { throw "couldn't start: $commandLine (error $($r.ReturnValue))" }
}

function Write-Log([string]$msg) {
    $line = "$(Get-Date -Format s) $msg"
    Add-Content -Path (Join-Path $LogDir 'hosting.log') -Value $line -Encoding utf8
    Write-Output $line
}
