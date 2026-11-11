"""Same query set, same corpora, compare vector-only and RRF Recall@4/1."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.retrieval import hybrid_search
from textile.catalog import CATALOG
from textile.models import embed
from textile.settings import ROOT

if __name__=='__main__':
    rows=[]
    for table,(description,fields) in CATALOG.items():
        # Balanced literal identifiers and business wording, one target per query.
        for question,kind in [(f'查询{table}的数据','identifier'),(description.split('；')[0],'business')]:
            vector=embed(question);row={'question':question,'target':table,'kind':kind}
            for mode in ['vector','hybrid']:
                hits=hybrid_search(question,vector,'table',CATALOG,4,mode)
                names=[h['table_name'] for h in hits]
                row[mode]={'recall4':int(table in names),'hit1':int(bool(names) and names[0]==table),'tables':names}
            rows.append(row)
    summary={mode:{metric:sum(r[mode][metric] for r in rows)/len(rows) for metric in ['recall4','hit1']} for mode in ['vector','hybrid']}
    result={'count':len(rows),'summary':summary,'cases':rows,'note':'Single target synthetic retrieval probe; not a real user query benchmark.'}
    (ROOT/'artifacts'/'retrieval-comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'count':len(rows),'summary':summary}))
