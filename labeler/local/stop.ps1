# Stops the labeler page and backend. Saved labels that haven't reached the bucket yet stay in the
# local index and are pushed on the next start.
. (Join-Path $PSScriptRoot 'common.ps1')

foreach ($port in $FrontendPort, $BackendPort) {
    $procIds = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue).OwningProcess |
        Sort-Object -Unique
    foreach ($p in $procIds) {
        Write-Log "stopping process $p on port $port"
        & taskkill.exe /PID $p /T /F | Out-Null
    }
}
