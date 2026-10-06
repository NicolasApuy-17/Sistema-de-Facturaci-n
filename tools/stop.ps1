$taskRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$expectedScript = [regex]::Escape((Join-Path $taskRoot 'tools\serve_local.py'))
$expectedExecutables = @((Join-Path $taskRoot '.venv\Scripts\python.exe'), (Join-Path $taskRoot '.venv\Scripts\pythonw.exe'))
$processes = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe', 'pythonw.exe') })
$candidates = @($processes | Where-Object {
    $_.CommandLine -match $expectedScript -or ($_.ExecutablePath -in $expectedExecutables -and $_.CommandLine -match 'tools[\\/]serve\.py')
})
$ids = [System.Collections.Generic.HashSet[uint32]]::new()
foreach ($candidate in $candidates) { [void]$ids.Add($candidate.ProcessId) }
do {
    $changed = $false
    foreach ($process in $processes) {
        if ($ids.Contains($process.ParentProcessId) -and $ids.Add($process.ProcessId)) { $changed = $true }
    }
} while ($changed)
foreach ($processId in $ids) {
    Stop-Process -Id $processId -ErrorAction SilentlyContinue
}
Write-Host 'Se detuvieron los procesos de la aplicación en esta carpeta. PostgreSQL sigue activo.'
