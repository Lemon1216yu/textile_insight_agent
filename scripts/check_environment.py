import sys, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from pymilvus import MilvusClient
from textile.settings import DB, MILVUS_URI

conn=pymysql.connect(**DB)
with conn.cursor() as c:
    c.execute('SELECT VERSION()'); print('MySQL:',c.fetchone()[0])
    c.execute('SHOW GRANTS'); print('SELECT-only grants:',len(c.fetchall()))
    try:
        c.execute('CREATE TABLE forbidden_write_probe (id INT)')
        raise RuntimeError('Reader unexpectedly has DDL permission')
    except pymysql.err.OperationalError as e:
        if e.args[0]!=1142: raise
        print('Read-only account DDL denial: PASS')
conn.close()
m=MilvusClient(uri=MILVUS_URI,timeout=10)
print('Milvus:',m.get_server_version())
name='textile_environment_probe'
if not m.has_collection(name):
    m.create_collection(name,dimension=2,metric_type='COSINE')
m.upsert(name,[{'id':1,'vector':[1.,0.],'label':'textile-probe'}])
rows=m.search(name,data=[[1.,0.]],limit=1,output_fields=['label'],consistency_level='Strong')
assert rows[0][0]['entity']['label']=='textile-probe'
print('Milvus real insert/search: PASS')
m.drop_collection(name)
