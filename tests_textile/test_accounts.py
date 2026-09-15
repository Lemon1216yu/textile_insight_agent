"""Enterprise account and role-permission integration checks (local MySQL, no model calls)."""
import os
import uuid
import pymysql
from fastapi.testclient import TestClient
from textile.app import app
from textile.db import query
from textile.settings import DB
from security import UserContext, SecurityError

DEMO_PASSWORD='demo123'

# 业务写账号 textile_app 没有 DELETE 权限，测试残留账号用运维账号真正删除，
# 否则每跑一次测试都会在 sys_users 留下停用垃圾行。
_ADMIN_DB={**DB,'user':'root','password':os.environ.get('TEXTILE_MYSQL_ROOT_PASSWORD','')}


def purge_users(*usernames):
    usernames=[u for u in usernames if u]
    if not usernames:return
    with pymysql.connect(**_ADMIN_DB) as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM sys_users WHERE username IN (%s)' % ','.join(['%s']*len(usernames)),usernames)


def reset_password(username,password=DEMO_PASSWORD):
    """改密接口要求新密码≥10位，演示密码 demo123 只有7位，只能用写账号直接还原。"""
    from textile.app import hash_password, _conn
    with _conn() as conn, conn.cursor() as cur:
        cur.execute('UPDATE sys_users SET password_hash=%s, session_version=session_version+1 WHERE username=%s',
                    (hash_password(password),username))
        assert cur.rowcount==1

def login(c, username, password=DEMO_PASSWORD):
    r=c.post('/api/login',json={'username':username,'password':password})
    assert r.status_code==200, r.text
    return r.json()

def test_six_roles_can_login_and_get_menus():
    with TestClient(app) as c:
        data=login(c,'admin'); assert data['role']=='admin'
        assert {'dashboard','query','analysis','metrics','reports','accounts'}<=set(c.get('/api/me').json()['menus'])
        for username,role in [('executive','executive'),('finance','finance'),('sales_east','sales'),('production','production'),('warehouse','warehouse')]:
            data=login(c,username)
            assert data['role']==role
            menus=c.get('/api/me').json()['menus']
            assert 'accounts' not in menus
            assert set(menus)=={'dashboard','query','analysis','metrics','reports'}

def test_bad_password_and_disabled_account_rejected():
    username='temp_'+uuid.uuid4().hex[:8]
    try:
        with TestClient(app) as c:
            assert c.post('/api/login',json={'username':'executive','password':'wrong'}).status_code==401
            login(c,'admin')
            assert c.patch('/api/admin/users/1',json={'active':False}).status_code==400  # 不能停用自己
            assert c.post('/api/admin/users',json={'username':username,'display_name':'临时用户','role':'finance','password':'testpass123'}).status_code==201
            uid=[u['user_id'] for u in c.get('/api/admin/users').json()['users'] if u['username']==username][0]
            assert c.patch(f'/api/admin/users/{uid}',json={'active':False}).status_code==200
            assert c.post('/api/login',json={'username':username,'password':'testpass123'}).status_code==403
            assert c.patch(f'/api/admin/users/{uid}',json={'active':True}).status_code==200
            assert c.post('/api/login',json={'username':username,'password':'testpass123'}).status_code==200
    finally:
        purge_users(username)

def test_change_password_flow():
    try:
        with TestClient(app) as c:
            login(c,'finance')
            assert c.post('/api/password',json={'old_password':'wrong','new_password':'newpass123'}).status_code==400
            assert c.post('/api/password',json={'old_password':DEMO_PASSWORD,'new_password':'newpass123'}).status_code==200
            # 改密递增 session_version，旧会话立即失效，因此旧 token 登出返回 401。
            assert c.post('/api/logout').status_code==401
            assert c.post('/api/login',json={'username':'finance','password':'newpass123'}).status_code==200
            # 改密接口要求新密码≥10位；演示密码 demo123 只有7位，接口无法改回。
            assert c.post('/api/password',json={'old_password':'newpass123','new_password':DEMO_PASSWORD}).status_code==422
    finally:
        reset_password('finance')

def test_admin_manages_users_and_roles():
    ops='ops_'+uuid.uuid4().hex[:8]
    sname='sales_'+uuid.uuid4().hex[:8]
    try:
        with TestClient(app) as c:
            login(c,'admin')
            assert c.get('/api/admin/users').status_code==200
            def uid_of(name):
                return [u['user_id'] for u in c.get('/api/admin/users').json()['users'] if u['username']==name][0]
            r=c.post('/api/admin/users',json={'username':ops,'display_name':'测试主管','role':'production','password':'testpass123'})
            assert r.status_code==201
            # duplicate rejected
            assert c.post('/api/admin/users',json={'username':ops,'display_name':'x','role':'admin','password':'testpass123'}).status_code==409
            # sales requires region
            assert c.post('/api/admin/users',json={'username':'sales_'+uuid.uuid4().hex[:8],'display_name':'x','role':'sales','password':'testpass123'}).status_code==422
            assert c.post('/api/admin/users',json={'username':sname,'display_name':'x','role':'sales','region':'华东','password':'testpass123'}).status_code==201
            # non-admin cannot manage
            login(c,'executive')
            assert c.get('/api/admin/users').status_code==403
            assert c.post('/api/admin/users',json={'username':'hacker','display_name':'x','role':'admin','password':'testpass123'}).status_code==403
    finally:
        purge_users(ops,sname)

def test_production_cannot_access_sales_orders():
    u=UserContext('production','production',None)
    try:
        query("SELECT COUNT(*) AS n FROM sales_orders",u)
        assert False,'生产角色不应能访问销售订单表'
    except SecurityError:
        pass
    r2=query("SELECT SUM(actual_meters) AS output FROM production_batches",u)
    assert r2['rows'][0]['output'] is not None

def test_warehouse_hides_amount_fields():
    u=UserContext('warehouse','warehouse',None)
    # 库存金额对仓储可见（盘点对账用），销售金额字段隐藏。
    assert query("SELECT SUM(inventory_value) AS v FROM inventory_snapshots WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM inventory_snapshots)",u)['rows'][0]['v'] is not None
    try:
        query("SELECT SUM(net_amount) FROM sales_orders",u)
        assert False,'仓储角色不应能访问销售金额字段'
    except SecurityError:
        pass

def test_sales_region_filter_and_cost_hidden():
    u=UserContext('sales_east','sales','华东')
    r=query("SELECT DISTINCT region FROM sales_orders",u)
    assert r['rows']==[{'region':'华东'}]
    try:
        query("SELECT SUM(cost_amount) FROM sales_orders",u)
        assert False,'销售不应能访问成本字段'
    except SecurityError:
        pass

def test_metrics_catalog_visible_per_role():
    with TestClient(app) as c:
        login(c,'production')
        data=c.get('/api/metrics').json()
        assert data['total']==32
        items=data['items']
        sales_metrics=[m for m in items if m['code'].startswith('SAL')]
        assert sales_metrics and not any(m['visible'] for m in sales_metrics)
        prd=[m for m in items if m['code'].startswith('PRD')]
        assert prd and all(m['visible'] for m in prd)
