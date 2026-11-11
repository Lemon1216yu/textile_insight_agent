"""Archive exact prompt-bearing source and version id for reproducible regression."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.settings import ROOT,MODEL
from textile.task_queue import prompt_revision,PROMPT_FILES
if __name__=='__main__':
    version=prompt_revision();target=ROOT/'artifacts'/'prompt-versions'/version;target.mkdir(parents=True,exist_ok=True)
    for name in PROMPT_FILES:
        (target/name).write_bytes((ROOT/'textile'/name).read_bytes())
    (target/'manifest.json').write_text(json.dumps({'version':version,'model':MODEL,'note':'Run scripts/regression.ps1 for strict SQL-result regression before activation.'},indent=2),encoding='utf-8')
    print(version)
