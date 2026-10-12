# Installs the Sync and the Rotation as scheduled tasks on Windows. Safe to re-run.
$ErrorActionPreference = 'Stop'

$script = Join-Path $PSScriptRoot 'immich_wallpaper.py'
$configDir = Join-Path $env:APPDATA 'immich-wallpaper'

# The real interpreter, not the Microsoft Store alias; pythonw beside it runs without a console window.
$python = try { & python -c 'import sys; print(sys.executable)' } catch { $null }
if ($LASTEXITCODE -ne 0 -or -not $python) {
    Write-Host 'Python is not installed. Run: winget install Python.Python.3.12'
    exit 1
}
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'

& $python -m pip install --user --quiet pillow
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Could not install Pillow.'
    exit 1
}

New-Item -ItemType Directory -Force $configDir | Out-Null
if (-not (Test-Path "$configDir\config")) {
    Copy-Item (Join-Path $PSScriptRoot 'config.example') "$configDir\config"
    Write-Host "Created $configDir\config: fill in the Immich URL and album id, then re-run."
    exit 1
}
if (-not (Test-Path "$configDir\api-key") -or (Get-Item "$configDir\api-key").Length -eq 0) {
    Write-Host "Put an Immich API key in $configDir\api-key, then re-run."
    exit 1
}

# DisplayFusion re-applies its own wallpaper, undoing every Rotation.
$displayFusion = Get-ItemProperty 'HKCU:\Software\Binary Fortress Software\DisplayFusion' -ErrorAction SilentlyContinue
if ($displayFusion.WallpaperEnabled -eq 1) {
    Write-Host "Turn off DisplayFusion's wallpaper feature (DisplayFusion Settings > Wallpaper), then re-run."
    exit 1
}

# The immich-wallpaper command, in the per-user folder that Windows puts on PATH.
Set-Content -Encoding ascii "$env:LOCALAPPDATA\Microsoft\WindowsApps\immich-wallpaper.cmd" "@`"$python`" `"$script`" %*"

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -Force -TaskName 'immich-wallpaper-sync' -Settings $settings -Trigger $atLogon `
    -Action (New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`" run-sync") | Out-Null
# A logon trigger's repetition only starts at the next logon, so the 5 minutes count from now instead.
$everyFiveMinutes = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -Force -TaskName 'immich-wallpaper-rotate' -Settings $settings -Trigger $atLogon, $everyFiveMinutes `
    -Action (New-ScheduledTaskAction -Execute $pythonw -Argument "`"$script`" rotate") | Out-Null

& $python $script sync
& $python $script rotate
Write-Host 'Done. Each Monitor gets another photo every 5 minutes.'
