"""Authenticated read-only views of live MySQL and Milvus contents."""
from fastapi import APIRouter,Depends,HTTPException,Query
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
import pymysql
from textile.settings import ROOT,DB,COLLECTION,MILVUS_URI,EMBED_MODEL
from textile.catalog import CATALOG
from textile.security import allowed_catalog
from textile.db import query
from textile.retrieval import milvus,search
from textile.models import embed

class SearchRequest(BaseModel):
    question:str=Field(min_length=1,max_length=500)
    kind:str='table'

def router(auth):
    routes=APIRouter()
    def vector_access(user):
        if user.role not in {'admin','finance'}: raise HTTPException(403,'完整向量库说明仅向经营负责人和财务分析师展示')

    @routes.get('/data')
    def page(): return FileResponse(ROOT/'static'/'data.html')

    @routes.get('/api/data/overview')
    def overview(user=Depends(auth)):
        tables=[{'name':t,'description':CATALOG[t][0],'count':query(f'SELECT COUNT(*) AS n FROM `{t}`',user)['rows'][0]['n']} for t in allowed_catalog(user)]
        vectors=None
        if user.role in {'admin','finance'}:
            vectors={k:milvus().query(COLLECTION,filter=f'kind == "{k}"',output_fields=['count(*)'],consistency_level='Strong')[0]['count(*)'] for k in ['table','field','metric']}
        return {'tables':tables,'total':sum(t['count'] for t in tables),'vectors':vectors,'role':user.role,'region':user.region,
                'mysql':{'host':DB['host'],'port':DB['port'],'database':DB['database'],'user':DB['user']},
                'milvus':{'uri':MILVUS_URI,'collection':COLLECTION,'dimensions':256,'embedding_model':EMBED_MODEL}}

    @routes.get('/api/data/tables/{table}')
    def rows(table:str,page:int=Query(1,ge=1,le=10000),user=Depends(auth)):
        catalog=allowed_catalog(user)
        if table not in catalog: raise HTTPException(404,'表不存在或无权访问')
        columns=list(catalog[table]);primary=columns[0]
        sql=f'SELECT {", ".join("`"+c+"`" for c in columns)} FROM `{table}` ORDER BY `{primary}` LIMIT 20 OFFSET {(page-1)*20}'
        data=query(sql,user)
        # Metadata is read live from MySQL, then restricted to the same authorized fields.
        conn=pymysql.connect(**DB)
        try:
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute('SELECT COLUMN_NAME AS name,COLUMN_TYPE AS type,COLUMN_COMMENT AS description,COLUMN_KEY AS key_type FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION',(DB['database'],table))
                fields=[f for f in cursor.fetchall() if f['name'] in columns]
        finally: conn.close()
        return {**data,'fields':fields,'page':page,'total':query(f'SELECT COUNT(*) AS n FROM `{table}`',user)['rows'][0]['n']}

    @routes.get('/api/data/vectors')
    def vectors(kind:str='table',user=Depends(auth)):
        vector_access(user)
        if kind not in {'table','field','metric'}: raise HTTPException(422,'类型须为table、field或metric')
        records=milvus().query(COLLECTION,filter=f'kind == "{kind}"',output_fields=['id','name','kind','table_name','text'],limit=1000,consistency_level='Strong')
        return {'records':sorted(records,key=lambda x:x['id']),'kind':kind}

    @routes.get('/api/data/vectors/{record_id}')
    def vector(record_id:int,user=Depends(auth)):
        vector_access(user)
        records=milvus().query(COLLECTION,filter=f'id == {int(record_id)}',output_fields=['id','name','kind','text','vector'],limit=1,consistency_level='Strong')
        if not records: raise HTTPException(404,'记录不存在')
        row=records[0];row['vector']=[float(x) for x in row['vector']]
        return row

    @routes.post('/api/data/search')
    def vector_search(data:SearchRequest,user=Depends(auth)):
        vector_access(user)
        if data.kind not in {'table','field','metric'} or not data.question.strip(): raise HTTPException(422,'请输入问题并选择正确类型')
        vector=embed(data.question)
        hits=search(vector,f'kind == "{data.kind}"',5)
        return {'question':data.question,'dimensions':len(vector),'query_vector_preview':vector[:16],'hits':hits,
                'note':'这里只调用Embedding和Milvus，未调用聊天模型、未生成SQL。分数是余弦相似度，不是准确率。'}
    return routes
