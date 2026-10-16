param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$Args
)

# Minitab skill launcher: resolves a pywin32-capable Python and forwards to the CLI.
#   .\minitab.ps1 doctor
#   .\minitab.ps1 run "对 C1 做过程能力分析 LSL=9 USL=17" --backend auto
#   .\minitab.ps1 demo

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$python = $null
if ($env:MINITAB_PYTHON -and (Test-Path $env:MINITAB_PYTHON)) { $python = $env:MINITAB_PYTHON }
if (-not $python) {
  try { $python = (& python "$root\scripts\find_python.py" 2>$null | Select-Object -First 1) } catch { $python = $null }
}
if (-not $python) { Write-Error "找不到带 pywin32 的 Python。请设置 `$env:MINITAB_PYTHON 或 pip install pywin32"; exit 2 }

& $python "$root\scripts\minitab_cli.py" @Args
exit $LASTEXITCODE
