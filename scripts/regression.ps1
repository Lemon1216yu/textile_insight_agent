$ErrorActionPreference='Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot)
$env:PYTHONIOENCODING='utf-8'
# Static gates first: seconds-fast, and they stop config/secret mistakes before model calls.
& .venv/Scripts/python.exe scripts/check_env_contract.py
if ($LASTEXITCODE -ne 0) {throw 'Env template drifted from code; see scripts/check_env_contract.py'}
& .venv/Scripts/python.exe scripts/check_publish_safety.py
if ($LASTEXITCODE -ne 0) {throw 'Secret leak in tracked files; see scripts/check_publish_safety.py'}
# Run the whole directory instead of listing filenames: the old list named only 6 of
# 10 test files, so test_sql_governance.py (A8), test_audit.py (B2), test_accounts.py and
# test_integration.py never ran in this entry point. Whole dir = 106 cases, ~14s, no model calls.
& .venv/Scripts/python.exe -m pytest tests_textile -q
if ($LASTEXITCODE -ne 0) {throw 'Regression tests failed'}
& .venv/Scripts/python.exe scripts/evaluate_expanded.py
if ($LASTEXITCODE -ne 0) {throw 'Model evaluation failed'}
& .venv/Scripts/python.exe -c "import json; from pathlib import Path; d=json.loads(Path('artifacts/evaluation-expanded.json').read_text(encoding='utf-8')); assert d['execution_accuracy']>=.85, d['execution_accuracy']"
if ($LASTEXITCODE -ne 0) {throw 'Execution Accuracy below 0.85; see artifact'}
