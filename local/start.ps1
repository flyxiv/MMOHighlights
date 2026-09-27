# Starts Postgres, the backend and the page if they aren't already running. Safe to run repeatedly;
# the login task runs it every 5 minutes, which also restarts anything that crashed.
. (Join-Path $PSScriptRoot 'common.ps1')

# One run at a time (a manual run and the scheduled task can otherwise race).
$lock = New-Object System.Threading.Mutex($false, 'Local\MMOHighlightsRecorderStart')
if (-not $lock.WaitOne(0)) { Write-Output 'start.ps1 is already running'; exit 0 }
try {
    # 1. Postgres, when the database is the local one (a remote DATABASE_URL in backend\.env skips this)
    if ($UseLocalPostgres) { & "$PgBin\pg_ctl.exe" -D $PgData status *> $null }
    if ($UseLocalPostgres -and $LASTEXITCODE -ne 0) {
        Write-Log 'starting postgres'
        # Detached for the same reason as the servers: postgres would otherwise inherit (and hold
        # open) the output pipe of whoever runs this script.
        $pgLog = Join-Path $LogDir 'postgres.log'
        Start-Detached "`"$PgBin\pg_ctl.exe`" -D `"$PgData`" -o `"-p $PgPort`" -l `"$pgLog`" start" $DataDir (Join-Path $LogDir 'pg_ctl.log')
        foreach ($i in 1..30) {
            Start-Sleep -Seconds 1
            & "$PgBin\pg_ctl.exe" -D $PgData status *> $null
            if ($LASTEXITCODE -eq 0) { break }
        }
    }

    # Detached processes don't inherit this script's environment, so each gets a launcher file.
    $runDir = Join-Path $DataDir 'run'
    New-Item -ItemType Directory -Force -Path $runDir | Out-Null
    $envLines = @(
        '@echo off'
        "set `"PATH=$env:PATH`""
        "set `"ROLE=$Role`""
        "set `"SPOOL_DIR=$SpoolDir`""
        'set "STORAGE_BACKEND=gcs"'
        'set "GCS_BUCKET=mmohighlights"'
        'set "GCS_PREFIX=archives/"'
        'set "GCS_PROJECT=1065049752953"'
        "set `"CORS_ORIGINS=[`"http://localhost:$FrontendPort`"]`""
        'set "PYTHONUTF8=1"'
        "set `"BACKEND_URL=http://127.0.0.1:$BackendPort`""
        'set "NEXT_TELEMETRY_DISABLED=1"'
    )
    # backend\.env's DATABASE_URL is read by the backend itself; only the local default is set here
    # (the URL may hold characters that cmd would mangle, such as % in a password).
    if (-not $DatabaseUrlFromEnv) { $envLines += "set `"DATABASE_URL=$DatabaseUrl`"" }

    # 2. Backend (recorder, uploader, API)
    $backendDir = Join-Path $Repo 'backend'
    if (-not (Test-Port $BackendPort)) {
        $launcher = Join-Path $runDir 'backend.cmd'
        # ASCII: cmd reads .cmd files in the console code page; every path here is ASCII except the
        # repo, which is only passed as the working directory.
        ($envLines + "`"$Uv`" run alembic upgrade head" +
            "`"$Uv`" run uvicorn app.main:app --host 127.0.0.1 --port $BackendPort") |
            Set-Content -Path $launcher -Encoding Default
        Write-Log 'starting backend'
        Start-Detached "`"$launcher`"" $backendDir (Join-Path $LogDir 'backend.log')
    }

    # 3. Page
    $frontendDir = Join-Path $Repo 'frontend'
    if (-not (Test-Port $FrontendPort)) {
        $npm = Join-Path (Split-Path $Node) 'npm.cmd'
        $npx = Join-Path (Split-Path $Node) 'npx.cmd'
        $build = if (Test-Path (Join-Path $frontendDir '.next\BUILD_ID')) { @() } else { "call `"$npm`" run build" }
        $launcher = Join-Path $runDir 'frontend.cmd'
        ($envLines + $build + "`"$npx`" next start -H 127.0.0.1 -p $FrontendPort") |
            Set-Content -Path $launcher -Encoding Default
        Write-Log $(if ($build) { 'building and starting page' } else { 'starting page' })
        Start-Detached "`"$launcher`"" $frontendDir (Join-Path $LogDir 'frontend.log')
    }
} finally {
    $lock.ReleaseMutex()
}
