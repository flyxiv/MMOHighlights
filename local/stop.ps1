# Stops the page, the backend and Postgres.
# Recordings in progress are cut off; on the next start the recorder resumes any stream that is
# still live into the same recording, and uploads whatever was left in the spool.
. (Join-Path $PSScriptRoot 'common.ps1')

foreach ($port in $FrontendPort, $BackendPort) {
    $procIds = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess |
        Sort-Object -Unique
    foreach ($p in $procIds) {
        Write-Log "stopping process $p on port $port"
        # /T also ends the child processes (streamlink, ffmpeg, the node server).
        & taskkill.exe /PID $p /T /F | Out-Null
    }
}
if ($UseLocalPostgres) { & "$PgBin\pg_ctl.exe" -D $PgData status *> $null }
if ($UseLocalPostgres -and $LASTEXITCODE -eq 0) {
    Write-Log 'stopping postgres'
    & "$PgBin\pg_ctl.exe" -D $PgData stop -m fast | Out-Null
}
