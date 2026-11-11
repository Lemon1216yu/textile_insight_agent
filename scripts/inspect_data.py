"""Read live storage and export an inspection snapshot outside the business UI.

Run: .venv/Scripts/python.exe scripts/inspect_data.py
Only SELECT / Milvus query operations; never exports configuration passwords.
"""
import json, sys
from collections import Counter
from datetime import datetime
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymysql
from textile.settings import DB, ROOT, COLLECTION, MILVUS_URI
from textile.catalog import CATALOG
from textile.retrieval import milvus

def main():
    target=ROOT/'artifacts'/'storage-inspection'
    target.mkdir(parents=True,exist_ok=True)
    tables=[]
    with pymysql.connect(**DB) as conn:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            for table in CATALOG:
                cur.execute(f'SELECT COUNT(*) AS n FROM `{table}`')
                count=cur.fetchone()['n']
                cur.execute(f'SHOW COLUMNS FROM `{table}`')
                columns=cur.fetchall()
                cur.execute(f'SELECT * FROM `{table}` LIMIT 5')
                sample=cur.fetchall()
                tables.append(dict(table=table,description=CATALOG[table][0],row_count=count,columns=columns,sample=sample))
    m=milvus()
    # Iterate instead of relying on approximate collection statistics or fixed row limits.
    it=m.query_iterator(collection_name=COLLECTION,batch_size=100,filter='',output_fields=['*'])
    entities=[]
    try:
        while batch:=it.next(): entities.extend(batch)
    finally: it.close()
    entities.sort(key=lambda row:row['id'])
    kinds=dict(Counter(x['kind'] for x in entities))
    summary=dict(checked_at=datetime.now().isoformat(timespec='seconds'),
        mysql=dict(host=DB['host'],port=DB['port'],database=DB['database'],
                   business_tables=len(tables),business_rows=sum(t['row_count'] for t in tables),tables=tables),
        milvus=dict(uri=MILVUS_URI,collection=COLLECTION,entities=len(entities),kinds=kinds,
                    vector_dimensions=sorted(set(len(x['vector']) for x in entities)),
                    partitions=m.list_partitions(COLLECTION)))
    (target/'live-storage.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    (target/'milvus-entities.json').write_text(json.dumps(entities,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    lines=['# 当前向量条目（不含完整浮点数组）','',f"检查时间：{summary['checked_at']}；集合：`{COLLECTION}`；共 {len(entities)} 条。",'',
           '每个表、字段或指标是一个独立语义单元；不是将订单逐行向量化。完整向量在同目录 milvus-entities.json。','']
    for x in entities:
        lines.extend([f"## {x['id']} · {x['kind']} · {x['name']}",'',
                      f"业务表：`{x['table_name'] or '指标定义'}`；向量维度：{len(x['vector'])}",'',x['text'],''])
    (target/'vector-chunks.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'mysql_tables':len(tables),'mysql_business_rows':summary['mysql']['business_rows'],
                      'tables':{t['table']:t['row_count'] for t in tables},'milvus':summary['milvus'],
                      'output':str(target)},ensure_ascii=False,default=str))

if __name__=='__main__': main()
