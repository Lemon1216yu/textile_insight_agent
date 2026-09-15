import json,uuid
import pytest
from fastapi.testclient import TestClient
from textile.app import app
from textile.catalog import CATALOG
from textile.extended_catalog import EXTRA_CATALOG,EXTRA_RELATIONS
from textile.lexical import lexical_search,rrf
from textile.registry import get_metrics,redis_client
from textile.task_queue import scope,save,get_job
from textile.db import query
from security import UserContext,SecurityError

def test_52_distinct_tables_and_valid_relationships():
    assert len(CATALOG)==52 and len(EXTRA_CATALOG)==44
    for table,edges in EXTRA_RELATIONS.items():
        for target,key in edges:
            assert key in CATALOG[table][1] and key in CATALOG[target][1]

def test_chinese_keyword_retrieval_and_fusion():
    docs=[{'kind':'field','table_name':'t','name':'cost_amount','text':'cost_amount 订单实际销售成本'},
          {'kind':'field','table_name':'t','name':'net_amount','text':'net_amount 不含税销售收入'}]
    lexical=lexical_search('cost_amount 实际销售成本',docs,2)
    assert lexical[0]['name']=='cost_amount'
    fused=rrf([docs[1],docs[0]],lexical,limit=2)
    assert len(fused)==2 and set(fused[0]['sources'])=={'vector','bm25'}

def test_metric_master_is_in_mysql_and_calculates_with_permissions():
    assert len(get_metrics())==32
    with TestClient(app) as c:
        c.post('/api/login',json={'username':'sales_east','password':'demo123'})
        body={'start':'2026-08-01','end':'2026-09-01'}
        assert c.post('/api/metrics/FIN-003/calculate',json=body).status_code==403
        actual=c.post('/api/metrics/SAL-001/calculate',json=body)
        assert actual.status_code==200 and actual.json()['value']>0
        assert c.post('/api/metrics/SAL-001/calculate',json={'start':'bad','end':'2026-09-01'}).status_code==422

def test_result_owner_and_permission_scope(monkeypatch):
    from textile import task_queue as queue
    identifier='test-'+uuid.uuid4().hex
    owner='executive'
    job={'id':identifier,'owner':owner,'scope':scope(owner),'status':'completed','report':'test'}
    save(job)
    try:
        assert get_job(identifier,owner)['report']=='test'
        assert get_job(identifier,'sales_east') is None
        old=queue.account
        monkeypatch.setattr(queue,'account',lambda username:{**old(username),'session_version':999999})
        assert get_job(identifier,owner) is None
    finally:redis_client().delete('textile:job:'+identifier)

def test_extended_sql_join_and_permissions():
    rows=query('SELECT d.machine_name,SUM(m.downtime_minutes) AS minutes FROM machine_downtime m JOIN dim_machines d ON m.machine_id=d.machine_id GROUP BY d.machine_name',UserContext('p','production'))['rows']
    assert len(rows)==12
    with pytest.raises(SecurityError):
        query('SELECT SUM(receivable_amount) FROM accounts_receivable',UserContext('p','production'))
    with pytest.raises(SecurityError):
        query('SELECT definition FROM metric_registry',UserContext('a','admin'))

def test_data_explorer_removed_and_new_portal_served():
    with TestClient(app) as c:
        assert c.get('/data').status_code==404
        assert c.get('/').status_code==200
        assert '/portal/assets/' in c.get('/').text
