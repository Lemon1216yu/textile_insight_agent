$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot)
$env:PYTHONIOENCODING='utf-8'
& .venv/Scripts/python.exe -m pytest tests_textile/test_security.py tests_textile/test_understanding.py tests_textile/test_platform.py -q
if ($LASTEXITCODE -ne 0) {throw 'Regression tests failed'}
& .venv/Scripts/python.exe scripts/evaluate_expanded.py
if ($LASTEXITCODE -ne 0) {throw 'Model evaluation failed'}
& .venv/Scripts/python.exe -c "import json; from pathlib import Path; d=json.loads(Path('artifacts/evaluation-expanded.json').read_text(encoding='utf-8')); assert d['execution_accuracy']>=.85, d['execution_accuracy']"
if ($LASTEXITCODE -ne 0) {throw 'Execution Accuracy below 0.85; see artifact'}
