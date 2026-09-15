"""Local MySQL integration checks, no model calls."""
from fastapi.testclient import TestClient
from textile.app import app
from textile.db import query
from security import UserContext

def test_dashboard_matches_actual_sql():
    with TestClient(app) as c:
        assert c.get('/api/dashboard').status_code==401
        assert c.post('/api/login',json={'username':'executive','password':'bad'}).status_code==401
        assert c.post('/api/login',json={'username':'executive','password':'demo123'}).status_code==200
        d=c.get('/api/dashboard').json()
        assert d['kpi']['orders']==460
        assert round(d['kpi']['revenue'],2)==9376097.90
        assert len(d['trend'])==6

def test_sales_dashboard_and_header_spoof():
    with TestClient(app) as c:
        c.post('/api/login',json={'username':'sales_east','password':'demo123'})
        d=c.get('/api/dashboard',headers={'x-user-role':'admin'}).json()
        assert d['role']=='sales'
        assert 'gross_profit' not in d['kpi']
        assert d['kpi']['orders']<460
        assert c.get('/api/jobs/nonexistent').status_code==404

def test_actual_row_isolation_or_union():
    r=query("SELECT DISTINCT region FROM sales_orders WHERE 1=1 OR region='华南' UNION SELECT DISTINCT region FROM dim_customers",UserContext('s','sales','华东'))
    assert r['rows']==[{'region':'华东'}]

def test_no_data_and_unknown_mode():
    r=query("SELECT order_id FROM sales_orders WHERE order_date>'2030-01-01'")
    assert r['rows']==[]
    with TestClient(app) as c:
        c.post('/api/login',json={'username':'executive','password':'demo123'})
        assert c.post('/api/jobs',json={'question':'x','mode':'delete'}).status_code==422
