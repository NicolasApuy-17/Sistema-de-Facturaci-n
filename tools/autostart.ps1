$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $taskRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Primero instala y configura el sistema.' }
$configPath = Join-Path $taskRoot 'config.local.json'
if (-not (Test-Path -LiteralPath $configPath)) { throw 'Primero ejecuta Configurar.cmd.' }
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
if ($config.database.name -ne 'facturacion_prod') { throw 'El inicio automático se prepara en la empresa, sobre facturacion_prod.' }
$account = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$scriptPath = Join-Path $taskRoot 'tools\serve_local.py'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $scriptPath + '" --background --no-browser') -WorkingDirectory $taskRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $account
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $account -LogonType Interactive -RunLevel Limited
$existing = Get-ScheduledTask -TaskName 'ControlEmpresaLocal' -ErrorAction SilentlyContinue
if ($existing) { throw 'Ya existe el inicio automático ControlEmpresaLocal. Revisa la instalación antes de reemplazarlo.' }
Register-ScheduledTask -TaskName 'ControlEmpresaLocal' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Aplicación local de gestión. Inicio al entrar en Windows.' | Out-Null
Write-Host 'Inicio automático preparado para este usuario de Windows. Crea un acceso directo a http://127.0.0.1:8765.'
