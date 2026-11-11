"""Read-only portable business snapshot (not a full operational backup).

No overwrite restore operation is provided. Secrets are never exported.
"""
import sys,json,hashlib,argparse
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from textile.settings import DB,APP_DB,ROOT,COLLECTION
from textile.catalog import CATALOG
from textile.registry import get_metrics
from textile.retrieval import milvus

def main():
    target=ROOT/'artifacts'/'snapshots'/datetime.now().strftime('%Y%m%d-%H%M%S')
    target.mkdir(parents=True)
    tables={}
    with pymysql.connect(**DB) as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        # One consistent MySQL snapshot across business tables.
        cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
        for table in CATALOG:
            cur.execute(f'SELECT * FROM `{table}`');tables[table]=cur.fetchall()
        conn.rollback()
    (target/'business.json').write_text(json.dumps(tables,ensure_ascii=False,default=str),encoding='utf-8')
    (target/'metrics.json').write_text(json.dumps(get_metrics(),ensure_ascii=False),encoding='utf-8')
    vectors=[];iterator=milvus().query_iterator(COLLECTION,batch_size=100,filter='',output_fields=['*'])
    try:
        while batch:=iterator.next():vectors.extend(batch)
    finally:iterator.close()
    (target/'vectors.json').write_text(json.dumps(vectors,ensure_ascii=False,default=str),encoding='utf-8')
    manifest={'tables':len(tables),'rows':sum(map(len,tables.values())),'collection':COLLECTION,'vectors':len(vectors),
              'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir()}}
    (target/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'snapshot':str(target),**manifest},ensure_ascii=False))
if __name__=='__main__':main()
