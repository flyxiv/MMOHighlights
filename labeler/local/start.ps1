# Starts the labeler backend and page if they aren't already running. Safe to run repeatedly; the
# login task runs it every 5 minutes, which also restarts anything that crashed.
. (Join-Path $PSScriptRoot 'common.ps1')

$lock = New-Object System.Threading.Mutex($false, 'Local\MMOHighlightsLabelerStart')
if (-not $lock.WaitOne(0)) { Write-Output 'start.ps1 is already running'; exit 0 }
try {
    # Detached processes don't inherit this script's environment, so each gets a launcher file.
    $envLines = @(
        '@echo off'
        "set `"PATH=$env:PATH`""
        "set `"LABELER_STORAGE=$Storage`""
        "set `"LABELER_CACHE_DIR=$CacheDir`""
        "set `"LABELER_CORS_ORIGINS=[`"http://localhost:$FrontendPort`"]`""
        'set "PYTHONUTF8=1"'
        "set `"BACKEND_URL=http://127.0.0.1:$BackendPort`""
        'set "NEXT_TELEMETRY_DISABLED=1"'
    )

    $backendDir = Join-Path $Labeler 'backend'
    if (-not (Test-Port $BackendPort)) {
        $launcher = Join-Path $RunDir 'backend.cmd'
        # ASCII: cmd reads .cmd files in the console code page. The repo path (non-ASCII) is only
        # passed as the working directory.
        ($envLines + "`"$Uv`" run uvicorn app.main:app --host 127.0.0.1 --port $BackendPort") |
            Set-Content -Path $launcher -Encoding Default
        Write-Log 'starting labeler backend'
        Start-Detached "`"$launcher`"" $backendDir (Join-Path $LogDir 'backend.log')
    }

    $frontendDir = Join-Path $Labeler 'frontend'
    if (-not (Test-Port $FrontendPort)) {
        $npm = Join-Path (Split-Path $Node) 'npm.cmd'
        $npx = Join-Path (Split-Path $Node) 'npx.cmd'
        $build = if (Test-Path (Join-Path $frontendDir '.next\BUILD_ID')) { @() } else { "call `"$npm`" run build" }
        $launcher = Join-Path $RunDir 'frontend.cmd'
        ($envLines + $build + "`"$npx`" next start -H 127.0.0.1 -p $FrontendPort") |
            Set-Content -Path $launcher -Encoding Default
        Write-Log $(if ($build) { 'building and starting labeler page' } else { 'starting labeler page' })
        Start-Detached "`"$launcher`"" $frontendDir (Join-Path $LogDir 'frontend.log')
    }
} finally {
    $lock.ReleaseMutex()
}
