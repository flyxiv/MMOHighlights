# Shared settings for hosting the labeler on this Windows PC. Dot-sourced by the other scripts.
# Override anything here in local\config.ps1 (not committed).

$ErrorActionPreference = 'Continue'
$Labeler = Split-Path -Parent $PSScriptRoot

# Cache, logs and launchers live on an ASCII path (the Windows user folder has Korean characters).
$DataDir      = 'C:\Users\Public\mmohl-labeler'
$CacheDir     = Join-Path $DataDir 'cache'
$LogDir       = Join-Path $DataDir 'logs'
$RunDir       = Join-Path $DataDir 'run'
$Storage      = 'gs://ai_datasets_jyn'
$BackendPort  = 8100
$FrontendPort = 3100

function Find-Tool([string]$name, [string[]]$candidates) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($c in $candidates) {
        $hit = Get-ChildItem -Path $c -Filter "$name.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) { return $hit.FullName }
    }
    throw "$name not found. Install it or set its path in local\config.ps1."
}

$Config = Join-Path $PSScriptRoot 'config.ps1'
if (Test-Path $Config) { . $Config }

$WingetPkgs = Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages'
if (-not $Uv)   { $Uv   = Find-Tool 'uv'   @("$WingetPkgs\astral-sh.uv*") }
if (-not $Node) { $Node = Find-Tool 'node' @("$env:ProgramFiles\nodejs") }
$env:PATH = ((Split-Path $Node) + ';' + (Split-Path $Uv) + ";$env:PATH")

New-Item -ItemType Directory -Force -Path $CacheDir, $LogDir, $RunDir | Out-Null

function Test-Port([int]$port) {
    [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

# Starts a hidden process that inherits none of this script's handles, so a terminal running
# start.ps1 doesn't wait for the server to exit. Output goes to $logFile through cmd.
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
