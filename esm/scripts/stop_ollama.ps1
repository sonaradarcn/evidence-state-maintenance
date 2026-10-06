# Stop ESM's own Ollama servers (pids recorded by start_ollama.ps1).  Optional: -port <p> to stop one server only.
param([int]$port = 0)
$data = if ($env:ESM_DATA) { $env:ESM_DATA } else { Join-Path (Get-Location) "esm_data" }
$log = Join-Path $data "logs"
$f = "$log\ollama_pids.txt"
if (-not (Test-Path $f)) { Write-Output "no pid file"; exit 0 }
$keep = @()
foreach ($line in Get-Content $f) {
    $parts = $line.Split(" ")
    if ($parts.Count -lt 2) { continue }
    $p = [int]$parts[0]; $id = [int]$parts[1]
    if ($p -eq 11434) { continue }
    if ($port -ne 0 -and $p -ne $port) { $keep += $line; continue }
    try { Stop-Process -Id $id -Force -ErrorAction Stop; Write-Output "stopped $p pid=$id" } catch { Write-Output "not running $p pid=$id" }
    # runner child processes
    Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue | ForEach-Object {
        try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }
}
Set-Content $f $keep
