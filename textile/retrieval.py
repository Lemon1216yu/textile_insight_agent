"""Milvus table recall -> candidate fields -> BFS join paths; metric retrieval."""
from functools import lru_cache
from pymilvus import MilvusClient
from join_resolver import _bfs_shortest_path
from textile.settings import MILVUS_URI,COLLECTION
from textile.catalog import CATALOG,RELATIONS
from textile.metric_catalog import definition_text
from textile.registry import get_metrics
from textile.models import embed,embed_batch
from textile.security import allowed_catalog

def lightweight_context(user, understanding):
    """One authorized table, no embedding call or global table/field search."""
    from textile.understanding import visible_metrics
    from textile.metric_catalog import definition_text
    allowed=allowed_catalog(user)
    if understanding.complexity!='simple' or len(understanding.tables)!=1:
        raise ValueError('轻量上下文仅支持明确的单表问题')
    table=understanding.tables[0]
    fields=allowed[table]
    selected=[m for m in visible_metrics(user) if m['code'] in understanding.metric_codes]
    if not selected:
        selected=[m for m in visible_metrics(user) if m['table']==table]
    schema=table+' -- '+CATALOG[table][0]+'\n'+'\n'.join(
        f'  {f} {typ}: {CATALOG[table][1][f][1]}' for f,typ in fields.items())
    return {'strategy':'lightweight','tables':[{'table_name':table}],'fields':[],
            'paths':[],'relations':[],'schema':schema,
            'metrics':[{'name':m['name'],'text':definition_text(m)} for m in selected]}

@lru_cache(maxsize=1)
def milvus(): return MilvusClient(uri=MILVUS_URI,timeout=15)

def documents():
    docs=[]
    for t,(desc,fields) in CATALOG.items():
        docs.append({'kind':'table','table_name':t,'text':t+' '+desc+' '+' '.join(m for _,m in fields.values()),'name':t})
        for f,(typ,meaning) in fields.items():
            docs.append({'kind':'field','table_name':t,'text':f'{t}.{f} {typ} {meaning}','name':f})
    for metric in get_metrics():
        docs.append({'kind':'metric','table_name':'','text':definition_text(metric),'name':metric['name']})
    return docs

def index_count():
    """精确的在线向量数。get_collection_stats 的 row_count 是近似值：
    一次 upsert 后旧行仍待压缩，会返回约两倍的虚高数字，不能用于判断索引是否需要重建。"""
    try:
        rows=milvus().query(COLLECTION,filter='',output_fields=['count(*)'])
        return int(rows[0]['count(*)'])
    except Exception:
        return 0

def build_index():
    m=milvus(); docs=documents()
    existing=index_count() if m.has_collection(COLLECTION) else 0
    if existing>len(docs):
        # 文档减少时旧的更高 id 会残留，直接重建集合，避免检索到已删除口径。
        m.drop_collection(COLLECTION)
        existing=0
    if not m.has_collection(COLLECTION):
        m.create_collection(COLLECTION,dimension=256,metric_type='COSINE',consistency_level='Strong')
    for i in range(0,len(docs),10):
        batch=docs[i:i+10]; vectors=embed_batch([d['text'] for d in batch])
        m.upsert(COLLECTION,[{'id':i+j+1,'vector':v,**d} for j,(d,v) in enumerate(zip(batch,vectors))])
    m.flush(COLLECTION)
    return {'collection':COLLECTION,'documents':len(docs),'dimensions':256,'previous':existing}

def search(vector,filter_,limit):
    hits=milvus().search(COLLECTION,data=[vector],filter=filter_,limit=limit,
                        output_fields=['kind','table_name','text','name'],consistency_level='Strong')[0]
    return [{**h['entity'],'score':round(h['distance'],4)} for h in hits]

def hybrid_search(question,vector,kind,allowed,limit,mode='hybrid'):
    import json
    from textile.lexical import lexical_search,rrf,identity
    from textile.understanding import visible_metrics
    # Filter both corpora before fusion. Restricted items never enter the prompt.
    names=allowed if kind=='metric' else None
    candidates=[d for d in documents() if d['kind']==kind and (
        d['name'] in names if kind=='metric' else
        d['table_name'] in allowed and (kind!='field' or d['name'] in allowed[d['table_name']]))]
    if not candidates:return []
    condition='kind == '+json.dumps(kind)
    condition+=(' and name in '+json.dumps(list(names)) if kind=='metric' else
                ' and table_name in '+json.dumps(list(allowed)))
    valid={identity(d):d for d in candidates}
    vector_hits=[h for h in search(vector,condition,min(len(candidates),max(limit*3,12))) if identity(h) in valid]
    if mode=='vector':return vector_hits[:limit]
    lexical_hits=lexical_search(question,candidates,max(limit*3,12))
    return rrf(vector_hits,lexical_hits,limit=limit)

def retrieve(question,user,required_tables=None,mode='hybrid'):
    import json
    allowed=allowed_catalog(user)
    vector=embed(question)
    tables=hybrid_search(question,vector,'table',allowed,4,mode)
    chosen=[r['table_name'] for r in tables]
    for t in required_tables or []:
        if t in allowed and t not in chosen:chosen.append(t)
    graph={t:[] for t in allowed}
    for t,rels in RELATIONS.items():
        for target,key in rels:
            if t in allowed and target in allowed:
                graph[t].append({'target':target}); graph[target].append({'target':t})
    paths=[]
    if chosen:
        for t in chosen[1:]:
            path=_bfs_shortest_path(chosen[0],t,graph)
            if path and all(x in allowed for x in path):
                paths.append(path)
    for path in paths:
        for t in path:
            if t not in chosen: chosen.append(t)
    fields=hybrid_search(question,vector,'field',{t:allowed[t] for t in chosen},24,mode)
    fields=[f for f in fields if f['name'] in allowed[f['table_name']]]
    # Recall critical keys and metric operands deterministically to prevent invalid trimmed schemas.
    selected={t:{f['name'] for f in fields if f['table_name']==t} for t in chosen}
    for t in chosen:
        selected[t].update(f for f in allowed[t] if f.endswith('_id') or f.endswith('_date') or f in {'region','order_status'})
        selected[t].update(f for f in allowed[t] if any(w in f for w in ['amount','cost','meters','quantity']))
    schema='\n'.join(t+' -- '+CATALOG[t][0]+'\n'+'\n'.join(f'  {f} {CATALOG[t][1][f][0]}: {CATALOG[t][1][f][1]}' for f in allowed[t] if f in selected[t]) for t in chosen)
    from textile.understanding import visible_metrics
    metrics=hybrid_search(question,vector,'metric',[m['name'] for m in visible_metrics(user)],3,mode)
    relations=[f'{t}.{key} = {other}.{key}' for t,rs in RELATIONS.items() for other,key in rs if t in chosen and other in chosen]
    return {'tables':tables,'fields':fields,'paths':paths,'relations':relations,'metrics':metrics,'schema':schema,'retriever':mode}
