# Start a dedicated Ollama server for ESM on its own port and GPU (the default port 11434 is left alone).
# usage: start_ollama.ps1 <port> <gpu> [num_parallel] [ctx]
# Logs and pids go to $env:ESM_DATA\logs (default .\esm_data\logs).  Stop with stop_ollama.ps1.
# Optional: $env:OLLAMA_EXE (default: ollama on PATH), $env:OLLAMA_MODELS (model directory).
param([int]$port, [int]$gpu, [int]$par = 1, [int]$ctx = 16384)
if ($port -eq 11434) { throw "port 11434 is the default Ollama server; choose another port" }
$data = if ($env:ESM_DATA) { $env:ESM_DATA } else { Join-Path (Get-Location) "esm_data" }
$log = Join-Path $data "logs"
New-Item -ItemType Directory -Force $log | Out-Null
$exe = if ($env:OLLAMA_EXE) { $env:OLLAMA_EXE } else { (Get-Command ollama).Source }
$env:OLLAMA_HOST = "127.0.0.1:$port"
$env:CUDA_VISIBLE_DEVICES = "$gpu"
$env:GGML_VK_VISIBLE_DEVICES = "$gpu"
$env:OLLAMA_VULKAN = "false"
$env:OLLAMA_NUM_PARALLEL = "$par"
$env:OLLAMA_CONTEXT_LENGTH = "$ctx"
$env:OLLAMA_KEEP_ALIVE = "10h"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$p = Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden -PassThru `
     -RedirectStandardOutput "$log\ollama_$port.log" -RedirectStandardError "$log\ollama_$port.err"
Add-Content "$log\ollama_pids.txt" "$port $($p.Id)"
Write-Output "started $port gpu=$gpu par=$par pid=$($p.Id)"
