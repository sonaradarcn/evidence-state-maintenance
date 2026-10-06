# Launch a persistent job queue (esm.scripts.jobqueue) as a detached process.
# usage (from the repository root): start_queue.ps1 <queue-name> [-data <ESM_DATA dir>] [-stage <ESM_STAGE>]
# Queue file <data>\<name>; console output <data>\logs\<name>.out.  Python: $env:ESM_PYTHON or python on PATH.
param([string]$name, [string]$data = (Join-Path (Get-Location) "esm_data_datalake"), [string]$stage = "datalake")
$env:ESM_DATA = $data
$env:ESM_STAGE = $stage
$env:PYTHONIOENCODING = "utf-8"
$py = if ($env:ESM_PYTHON) { $env:ESM_PYTHON } else { (Get-Command python).Source }
New-Item -ItemType Directory -Force "$data\logs" | Out-Null
$p = Start-Process -FilePath $py -ArgumentList "-B", "-m", "esm.scripts.jobqueue", "$data\$name", "--idle", "86400" `
     -WorkingDirectory (Get-Location) -WindowStyle Hidden -PassThru `
     -RedirectStandardOutput "$data\logs\$name.out" -RedirectStandardError "$data\logs\$name.err"
Add-Content "$data\logs\queue_pids.txt" "$name $($p.Id)"
Write-Output "queue $name pid=$($p.Id)"
