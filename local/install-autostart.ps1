# Registers a scheduled task that runs start.ps1 at login and every 5 minutes after that
# (so anything that crashed is restarted). Remove it with: Unregister-ScheduledTask MMOHighlightsRecorder
$ErrorActionPreference = 'Stop'
$start = Join-Path $PSScriptRoot 'start.ps1'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$start`""
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'MMOHighlightsRecorder' -Action $action -Trigger $atLogon, $repeat `
    -Settings $settings -Description 'Starts the MMOHighlights live recorder (local\start.ps1).' -Force | Out-Null
Write-Output 'Registered scheduled task MMOHighlightsRecorder (at login, then every 5 minutes).'
