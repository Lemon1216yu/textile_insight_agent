"""Authenticated enterprise API: user accounts, bounded background jobs, role-based dashboard."""
import base64,hashlib,hmac,json,os,time,uuid,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import date
import pymysql
from fastapi import FastAPI,HTTPException,Request,Depends
from fastapi.responses import FileResponse,Response,JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel,Field
from security import UserContext
from textile.settings import ROOT,DB,APP_DB,MILVUS_URI,MODEL,DATA_PERIOD
from textile.db import query
from textile.retrieval import milvus
from textile.agent import run
from textile.understanding import validate_input
from textile.permissions import ROLES,menus_for
from textile.registry import redis_client
from textile.task_queue import audit
from textile.app_pool import app_connection

app=FastAPI(title='织见 · 纺织制造经营智能分析平台',version='1.0.0')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

@app.middleware('http')
async def no_store(request, call_next):
    started=time.perf_counter()
    response=await call_next(request)
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control']='no-store'
        from textile.observability import http_event
        http_event(request.method,request.url.path,response.status_code,time.perf_counter()-started)
    return response
SESSION_HOURS=8
PBKDF2_ITERATIONS=200_000

def hash_password(password,salt_hex=None):
    salt=bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt,PBKDF2_ITERATIONS)
    return salt.hex()+'.'+digest.hex()

def verify_password(password,stored):
    try:
        salt_hex,hash_hex=stored.split('.')
        candidate=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt_hex),PBKDF2_ITERATIONS).hex()
        return hmac.compare_digest(candidate,hash_hex)
    except (ValueError,TypeError):
        return False

def _conn():
    # 应用账号走共享连接池；此前每次调用都新建连接，20 并发提交会放大到 2.4s。
    return app_connection()

def fetch_user(username):
    with _conn() as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT user_id,username,password_hash,display_name,role,region,active,session_version FROM sys_users WHERE username=%s',(username,))
        return cur.fetchone()

def update_last_login(user_id):
    with _conn() as conn:
        with conn.cursor() as cur: cur.execute('UPDATE sys_users SET last_login_at=NOW() WHERE user_id=%s',(user_id,))

def sign(value): return hmac.new(os.environ['TEXTILE_SESSION_SECRET'].encode(),value.encode(),hashlib.sha256).hexdigest()

def auth(request:Request):
    token=request.cookies.get('textile_session','')
    try:
        payload,signature=token.rsplit('.',1)
        if not hmac.compare_digest(sign(payload),signature): raise ValueError()
        username,expiry,version,*nonce=base64.urlsafe_b64decode(payload).decode().split(':')
        if int(expiry)<time.time(): raise ValueError()
        if redis_client().exists('textile:revoked:'+hashlib.sha256(token.encode()).hexdigest()): raise ValueError()
        row=fetch_user(username)
        if not row or not row['active'] or str(row['session_version'])!=version: raise ValueError()
        return UserContext(row['username'],row['role'],row['region'])
    except Exception: raise HTTPException(401,'请先登录')

class Login(BaseModel):
    username:str
    password:str
class JobRequest(BaseModel):
    question:str=Field(min_length=1,max_length=1200)
    mode:str='auto'
class PasswordChange(BaseModel):
    old_password:str=Field(min_length=1,max_length=200)
    new_password:str=Field(min_length=10,max_length=200)
class UserCreate(BaseModel):
    username:str=Field(min_length=2,max_length=50,pattern=r'^[a-zA-Z0-9_]+$')
    display_name:str=Field(min_length=1,max_length=50)
    role:str
    region:str|None=None
    password:str=Field(min_length=10,max_length=200)
class UserUpdate(BaseModel):
    display_name:str|None=None
    role:str|None=None
    region:str|None=None
    active:bool|None=None
    password:str|None=Field(default=None,min_length=10,max_length=200)

def require_admin(user):
    if user.role!='admin': raise HTTPException(403,'仅系统管理员可执行该操作')

@app.get('/')
def index(): return FileResponse(ROOT/'static'/'portal'/'index.html')

@app.get('/app')
def app_page(): return FileResponse(ROOT/'static'/'portal'/'index.html')

app.mount('/portal',StaticFiles(directory=ROOT/'static'/'portal',html=True,check_dir=False),name='portal')

@app.post('/api/login')
def login(data:Login):
    row=fetch_user(data.username)
    if not row or not verify_password(data.password,row['password_hash']):
        raise HTTPException(401,'账号或密码错误')
    if not row['active']: raise HTTPException(403,'账号已被停用，请联系系统管理员')
    update_last_login(row['user_id'])
    audit(row['username'],'login',{})
    p=base64.urlsafe_b64encode(f"{row['username']}:{int(time.time())+SESSION_HOURS*3600}:{row['session_version']}:{uuid.uuid4().hex}".encode()).decode()
    response=JSONResponse({'user':row['username'],'name':row['display_name'],'role':row['role'],'region':row['region']})
    response.set_cookie('textile_session',p+'.'+sign(p),httponly=True,samesite='strict',max_age=SESSION_HOURS*3600)
    return response

@app.post('/api/logout')
def logout(request:Request,user=Depends(auth)):
    token=request.cookies.get('textile_session','')
    redis_client().setex('textile:revoked:'+hashlib.sha256(token.encode()).hexdigest(),SESSION_HOURS*3600,'1')
    audit(user.user_id,'logout',{})
    response=JSONResponse({'ok':True})
    response.delete_cookie('textile_session')
    return response

@app.get('/api/me')
def me(user=Depends(auth)):
    row=fetch_user(user.user_id)
    return {'user':user.user_id,'name':row['display_name'] if row else user.user_id,
            'role':user.role,'role_name':ROLES.get(user.role,{}).get('name',user.role),
            'region':user.region,'menus':menus_for(user.role)}

@app.post('/api/password')
def change_password(data:PasswordChange,user=Depends(auth)):
    row=fetch_user(user.user_id)
    if not row or not verify_password(data.old_password,row['password_hash']):
        raise HTTPException(400,'原密码不正确')
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE sys_users SET password_hash=%s,session_version=session_version+1 WHERE user_id=%s',(hash_password(data.new_password),row['user_id']))
    audit(user.user_id,'password_changed',{})
    return {'ok':True}

@app.get('/api/admin/users')
def list_users(user=Depends(auth)):
    require_admin(user)
    with _conn() as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT user_id,username,display_name,role,region,active,created_at,last_login_at FROM sys_users ORDER BY user_id')
        return {'users':cur.fetchall()}

@app.post('/api/admin/users',status_code=201)
def create_user(data:UserCreate,user=Depends(auth)):
    require_admin(user)
    if data.role not in ROLES: raise HTTPException(422,'未知角色')
    if data.role=='sales' and data.region not in {'华东','华南','华北'}: raise HTTPException(422,'销售经理必须绑定区域')
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute('INSERT INTO sys_users (username,password_hash,display_name,role,region) VALUES (%s,%s,%s,%s,%s)',
                            (data.username,hash_password(data.password),data.display_name,data.role,data.region))
        audit(user.user_id,'account_created',{'username':data.username,'role':data.role,'region':data.region})
        return {'ok':True}
    except pymysql.err.IntegrityError:
        raise HTTPException(409,'用户名已存在')

@app.patch('/api/admin/users/{user_id}')
def update_user(user_id:int,data:UserUpdate,user=Depends(auth)):
    require_admin(user)
    if data.role is not None and data.role not in ROLES: raise HTTPException(422,'未知角色')
    with _conn() as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT role,region FROM sys_users WHERE user_id=%s',(user_id,))
        target=cur.fetchone()
    if not target: raise HTTPException(404,'账户不存在')
    effective_role=data.role if data.role is not None else target['role']
    effective_region=data.region if data.region is not None else target['region']
    if effective_role=='sales' and effective_region not in {'华东','华南','华北'}: raise HTTPException(422,'销售经理必须绑定区域')
    current=fetch_user(user.user_id)
    if current and current['user_id']==user_id and data.role and data.role!='admin':
        raise HTTPException(400,'不能修改当前管理员自身的岗位')
    if data.active is False and current and current['user_id']==user_id:
        raise HTTPException(400,'不能停用当前登录账号')
    sets=[]; params=[]
    for field,value in [('display_name',data.display_name),('role',data.role),('region',data.region),('active',data.active)]:
        if value is not None:
            sets.append(field+'=%s'); params.append(int(value) if field=='active' else value)
    if data.password:
        sets.append('password_hash=%s'); params.append(hash_password(data.password))
    if not sets: raise HTTPException(422,'没有需要更新的字段')
    sets.append('session_version=session_version+1')
    params.append(user_id)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE sys_users SET '+', '.join(sets)+' WHERE user_id=%s',params)
    audit(user.user_id,'account_updated',{'user_id':user_id,'fields':sorted(data.model_fields_set-{'password'}),'password_reset':bool(data.password)})
    return {'ok':True}

@app.get('/api/health')
def health():
    status={'mysql':False,'milvus':False,'model':MODEL,'period':DATA_PERIOD,'synthetic_data':True}
    try: query('SELECT COUNT(order_id) AS n FROM sales_orders'); status['mysql']=True
    except Exception: pass
    try: status['milvus']=bool(milvus().get_server_version())
    except Exception: pass
    try:
        status['redis']=bool(redis_client().ping())
        status['worker']=bool(redis_client().exists('arq:queue:health-check'))
    except Exception: status.update(redis=False,worker=False)
    # 模型链状态：cooling=true 表示该模型免费额度暂时耗尽、已自动切到后面的模型。
    try:
        from textile.models import model_status
        status['model_chain']=model_status()
    except Exception: status['model_chain']=[]
    # 最近一次真正服务的模型：免费额度耗尽自动降级时，它会与首选 model 不一致。
    # 用量列表是最新在前（lpush），所以取下标 0。
    try:
        import json as _json
        raw=redis_client().lindex('textile:usage',0)
        if raw:
            last=_json.loads(raw)
            status['model_last_used']={'model':last.get('model'),'at':last.get('time')}
    except Exception: pass
    status['status']='ok' if all(status[k] for k in ['mysql','milvus','redis','worker']) else 'degraded'
    return status

@app.get('/api/admin/operations')
def operations(user=Depends(auth)):
    require_admin(user)
    from textile.observability import operations_summary
    return operations_summary()

@app.get('/api/dashboard')
def dashboard(user=Depends(auth)):
    if user.role=='production':
        kpi=query("SELECT COUNT(batch_id) AS batches, SUM(actual_meters) AS output_meters, (SUM(actual_meters)-SUM(defect_meters))/NULLIF(SUM(actual_meters),0)*100 AS yield_pct, SUM(actual_meters)/NULLIF(SUM(planned_meters),0)*100 AS plan_pct FROM production_batches",user)['rows'][0]
        return {'kpi':kpi,'role':user.role,'region':user.region,'period':DATA_PERIOD,'view':'production'}
    if user.role=='warehouse':
        kpi=query("SELECT SUM(quantity) AS stock_meters, SUM(inventory_value) AS stock_value, SUM(aged_90_meters) AS aged_meters, SUM(aged_90_meters)/NULLIF(SUM(quantity),0)*100 AS aged_pct FROM inventory_snapshots WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM inventory_snapshots)",user)['rows'][0]
        return {'kpi':kpi,'role':user.role,'region':user.region,'period':DATA_PERIOD,'view':'warehouse'}
    sales="FROM sales_orders WHERE order_status='已完成' AND delivery_date IS NOT NULL"
    amounts='SUM(net_amount) AS revenue, COUNT(order_id) AS orders, SUM(quantity) AS meters'
    if user.role!='sales': amounts+=', SUM(net_amount-cost_amount) AS gross_profit'
    kpi=query('SELECT '+amounts+' '+sales,user)['rows'][0]
    trend=query("SELECT DATE_FORMAT(delivery_date,'%Y-%m') AS month, "+amounts+' '+sales+" GROUP BY DATE_FORMAT(delivery_date,'%Y-%m') ORDER BY month",user)['rows']
    products=query('SELECT p.product_name, SUM(s.net_amount) AS revenue FROM sales_orders s JOIN dim_products p ON s.product_id=p.product_id WHERE s.order_status=\'已完成\' AND s.delivery_date IS NOT NULL GROUP BY p.product_name ORDER BY revenue DESC',user)['rows']
    inventory=query('SELECT SUM(quantity) AS stock, SUM(aged_90_meters) AS aged FROM inventory_snapshots WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM inventory_snapshots)',user)['rows'][0]
    return {'kpi':kpi,'trend':trend,'products':products,'inventory':inventory,'period':DATA_PERIOD,'role':user.role,'region':user.region,'view':'sales_finance'}

@app.post('/api/jobs',status_code=202)
async def create_job(data:JobRequest,user=Depends(auth)):
    from textile.task_queue import submit
    if data.mode not in {'auto','query','analysis'}: raise HTTPException(422,'未知查询模式')
    try:
        question=validate_input(data.question)
        return {'id':await submit(question,data.mode,user)}
    except ValueError as exc:raise HTTPException(422,str(exc))

@app.get('/api/jobs/{job_id}')
def get_job(job_id:str,user=Depends(auth)):
    from textile.task_queue import get_job as read_job
    job=read_job(job_id,user.user_id)
    if not job:raise HTTPException(404,'任务不存在或权限已变更')
    return job

@app.get('/api/metrics')
def metrics(user=Depends(auth)):
    from textile.registry import get_metrics
    METRIC_DEFINITIONS=get_metrics()
    keys=('code','name','domain','unit','definition','formula','time_field','dimensions','owner',
          'caveats','target','version','status','scope','aggregation','dependencies')
    items=[]
    for m in METRIC_DEFINITIONS:
        role_visible=user.role in m['roles'] or user.role=='admin'
        items.append({k:m.get(k) for k in keys} | {'visible':role_visible})
    return {'total':len(METRIC_DEFINITIONS),'items':items}

class MetricCalculation(BaseModel):
    start:date
    end:date

@app.post('/api/metrics/{code}/calculate')
def calculate_metric(code:str,data:MetricCalculation,user=Depends(auth)):
    from textile.registry import get_metrics
    from textile.metric_catalog import compile_sql
    metric=next((m for m in get_metrics() if m['code']==code),None)
    if not metric or (user.role!='admin' and user.role not in metric['roles']):raise HTTPException(403,'无权计算此指标')
    if data.start>=data.end:raise HTTPException(422,'起始日期必须早于结束日期')
    result=query(compile_sql(metric,data.start.isoformat(),data.end.isoformat()),user)
    value=next(iter(result['rows'][0].values())) if result['rows'] else None
    return {'code':code,'value':value,'unit':metric['unit'],'start':data.start,'end':data.end,'formula':metric['formula']}

@app.get('/api/history')
def history(user=Depends(auth)):
    from textile.task_queue import history as list_history
    return [{k:j.get(k) for k in ['id','question','status','mode','created_at','duration_seconds']} for j in list_history(user.user_id)]

@app.get('/api/jobs/{job_id}/report')
def download_report(job_id:str,user=Depends(auth)):
    job=get_job(job_id,user)
    if not job.get('report'):raise HTTPException(409,'报告尚未生成')
    parts=['# '+job['question'],job['report'],'---\n模拟业务数据。']
    for result in job.get('results',[]):
        if result['success']:
            parts.extend(['## '+result['step']['title'],'```json\n'+json.dumps(result['rows'],ensure_ascii=False,indent=2)+'\n```'])
    return Response('\n\n'.join(parts),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="analysis.md"'})

@app.get('/api/usage')
def usage(user=Depends(auth)):
    from textile.registry import redis_client
    r=redis_client();day=time.strftime('%Y-%m-%d')
    return {'day':day,'tokens':int(r.get(f'textile:tokens:{user.user_id}:{day}') or 0),
            'limit':int(os.getenv('TEXTILE_DAILY_TOKEN_LIMIT','1000000'))}

@app.get('/api/admin/audit')
def audit_log(user=Depends(auth)):
    require_admin(user)
    with _conn() as conn,conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT event_id,occurred_at,username,action,detail FROM audit_events ORDER BY event_id DESC LIMIT 100')
        return {'items':cur.fetchall()}
