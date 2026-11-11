"""Persistent arq jobs and per-user, per-permission result caching."""
import asyncio,hashlib,json,os,threading,time,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pymysql
from arq import create_pool
from arq.connections import RedisSettings
from textile.settings import APP_DB,ROOT,MODEL
from textile.app_pool import app_cursor
from textile.registry import redis_client,metrics_revision
from textile.security import allowed_catalog
from security import UserContext

TTL=86400
RESULT_TTL=120
REDIS_URL=os.getenv('TEXTILE_REDIS_URL','redis://127.0.0.1:6379/0')

def encode(value):return json.dumps(value,ensure_ascii=False,default=str)

def account(username):
    with app_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT username,role,region,active,session_version FROM sys_users WHERE username=%s',(username,))
        row=cur.fetchone()
    if not row or not row['active']:raise PermissionError('账号不可用')
    return row

def scope(username):
    row=account(username)
    row['columns']=allowed_catalog(UserContext(username,row['role'],row['region']))
    return hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()

PROMPT_FILES=['agent.py','understanding.py','catalog.py','retrieval.py','metric_catalog.py','extended_catalog.py','lexical.py','models.py','registry.py']

_revision={'fingerprint':None,'value':None}
_revision_lock=threading.Lock()

def _prompt_fingerprint():
    parts=[]
    for name in PROMPT_FILES:
        info=(ROOT/'textile'/name).stat()
        parts.append(f'{name}:{info.st_mtime_ns}:{info.st_size}')
    return '|'.join(parts)

def prompt_revision():
    """按源文件指纹缓存版本号：文件未变时不再重复读取 9 个文件。"""
    fingerprint=_prompt_fingerprint()
    if _revision['fingerprint']==fingerprint:return _revision['value']
    with _revision_lock:
        if _revision['fingerprint']==fingerprint:return _revision['value']
        value=hashlib.sha256(b''.join((ROOT/'textile'/f).read_bytes() for f in PROMPT_FILES)).hexdigest()[:16]
        _revision.update(fingerprint=fingerprint,value=value)
        return value

def audit(username,action,detail):
    with app_cursor() as cur:
        cur.execute('INSERT INTO audit_events(username,action,detail) VALUES(%s,%s,%s)',(username,action,encode(detail)))

def _model_used():
    """本次任务实际服务的模型（额度降级后与首选模型不同）。

    B2 修复（2026-09-15）：原先读 Redis `textile:usage` 的 `lindex 0`，那是**全进程共享**的
    最新一条调用记录（实测该列表 1329/1658 条 user='system'），并发/多用户时会把
    别人的模型标到本任务上。改读 `models` 的 contextvar：同线程调用链共享，跨线程互不覆盖。
    这里**不**用 `models.last_call()`：它会把"没调用过"回落成首选模型，于是"被安全层拦下、
    根本没碰模型的失败任务"会被记成"用了首选模型"（假归属）。没有调用就返回 None。
    """
    try:
        from textile import models
        holder=getattr(models,'_last_call',None)
        value=holder.get() if holder is not None else None
        return value.get('model') if isinstance(value,dict) else None
    except Exception:
        return None

def result_facts(job,sql_limit=800):
    """把"查了什么/返回了什么"抽成结构化事实（纯函数，便于单测）。"""
    facts=[]
    for item in job.get('results') or []:
        if not isinstance(item,dict):continue
        if item.get('success') is False:
            # B2 补（2026-09-18）：步骤失败时 run() 不抛异常，只把错误塞进 results，
            # 结果里没有 SQL。若照常抽 sql/row_count，审计会变成"查了空 SQL、返回 0 行"，
            # 读者看不出这是失败 —— 必须显式记下失败与原因。
            facts.append({'failed':True,'error':str(item.get('error') or '')[:300],
                          'step':(item.get('step') or {}).get('title')})
            continue
        sql=' '.join(str(item.get('sql') or '').split())
        facts.append({'sql':sql[:sql_limit],
                      'sql_truncated':len(sql)>sql_limit,
                      'row_count':item.get('row_count',0),
                      'columns':list(item.get('columns') or []),
                      'limited_to':item.get('limited_to')})
    return facts

def finished_detail(job):
    """一次问答任务的审计明细：谁（username 另列）+ 何时（occurred_at 另列）+ 问了什么 + 查了什么 + 返回了什么。"""
    facts=result_facts(job)
    detail={'job_id':job.get('id'),'mode':job.get('mode'),'status':job.get('status'),
            'question':job.get('question'),'role':job.get('actor_role'),'region':job.get('actor_region'),
            'seconds':job.get('duration_seconds'),'model':_model_used(),
            'row_counts':[f.get('row_count',0) for f in facts],'results':facts}
    if job.get('status')=='failed':
        detail['error']=str(job.get('error') or '')[:300]
        if not detail['error']:
            # B2 补（2026-09-18）：run() 内部把步骤失败写进 results 而不抛异常时，
            # job['error'] 是空的，真实端到端跑出过"status=failed 但审计里没有原因"。
            # 回退到步骤级错误，避免失败在审计里不可解释。
            step_errors=[f.get('error') for f in facts if f.get('failed') and f.get('error')]
            detail['error']=' | '.join(step_errors)[:300]
        detail['error_type']=job.get('error_type') or ('StepFailed' if detail['error'] else None)
        detail['denied']=bool(job.get('denied'))
    return detail

def save(job):
    redis_client().setex('textile:job:'+job['id'],TTL,encode(job))

def get_job(job_id,username):
    raw=redis_client().get('textile:job:'+job_id)
    if not raw:return None
    job=json.loads(raw)
    if job['owner']!=username or job['scope']!=scope(username):return None
    return job

def history(username):
    ids=redis_client().lrange('textile:history:'+username,0,49)
    return [j for i in ids if (j:=get_job(i,username))]

_POOL=None
_POOL_LOCK=asyncio.Lock()
# 任务体是 IO 密集（模型、MySQL、Redis），线程数可高于核数；
# asyncio.to_thread 的默认池只有 min(32, 核数+4)=12，承载不了 max_jobs=20。
_EXECUTOR=ThreadPoolExecutor(max_workers=24,thread_name_prefix='textile-job')

async def _pool():
    """复用 arq 连接池；此前每次提交都新建并关闭一次连接池。"""
    global _POOL
    if _POOL is None:
        async with _POOL_LOCK:
            if _POOL is None:_POOL=await create_pool(RedisSettings.from_dsn(REDIS_URL))
    return _POOL

def _prepare(question,mode,user):
    """同步的限流、权限范围、缓存查找与任务落库；在线程中执行，避免阻塞事件循环。"""
    r=redis_client();current_scope=scope(user.user_id)
    minute=int(time.time()//60)
    ratekey=f'textile:rate:{user.user_id}:{minute}'
    rate=r.incr(ratekey);r.expire(ratekey,120)
    if rate>60:
        from fastapi import HTTPException
        raise HTTPException(429,'每分钟最多提交60个问题，请稍后再试')
    budget=int(os.getenv('TEXTILE_DAILY_TOKEN_LIMIT','1000000'))
    if int(r.get(f'textile:tokens:{user.user_id}:{time.strftime("%Y-%m-%d")}') or 0)>=budget:
        r.lpush('textile:alerts',encode({'kind':'token_budget','user':user.user_id,'time':time.time()}));r.ltrim('textile:alerts',0,199)
        from fastapi import HTTPException
        raise HTTPException(429,'今日模型用量已达上限，请联系管理员')
    revision=prompt_revision()
    cachekey='textile:result:'+hashlib.sha256(encode([user.user_id,current_scope,question,mode,MODEL,revision,metrics_revision()]).encode()).hexdigest()
    job={'id':uuid.uuid4().hex,'owner':user.user_id,'question':question,'mode':mode,'status':'queued',
         'events':[],'created_at':time.time(),'scope':current_scope,'prompt_version':revision,'cache_key':cachekey}
    cached=r.get(cachekey)
    if cached:
        job.update(json.loads(cached));job['cache_hit']=True;job['duration_seconds']=0
    save(job)
    r.lpush('textile:history:'+user.user_id,job['id']);r.ltrim('textile:history:'+user.user_id,0,99);r.expire('textile:history:'+user.user_id,TTL)
    audit(user.user_id,'query_submitted',{'job_id':job['id'],'question':question,'mode':mode,'cache_hit':bool(cached),
                                          'scope':current_scope,'role':getattr(user,'role',None),'region':getattr(user,'region',None)})
    return job,bool(cached)

async def submit(question,mode,user):
    job,cached=await asyncio.to_thread(_prepare,question,mode,user)
    if not cached:
        try:await (await _pool()).enqueue_job('execute_query',job['id'],_job_id=job['id'])
        except Exception:
            job.update(status='failed',error='任务队列不可用');save(job);raise
    return job['id']

async def execute_query(ctx,job_id):
    def work():
        from textile.agent import run
        from textile.telemetry import usage_context
        r=redis_client();raw=r.get('textile:job:'+job_id)
        if not raw:return
        job=json.loads(raw);start=time.time()
        def emit(kind,message,extra=None):
            job['events'].append({'kind':kind,'message':message,'time':time.time(),**(extra or {})});save(job)
        try:
            if scope(job['owner'])!=job['scope']:raise PermissionError('任务权限已变更，请重新提交')
            row=account(job['owner']);user=UserContext(row['username'],row['role'],row['region'])
            job['actor_role']=row['role'];job['actor_region']=row['region']
            job.update(status='running',started_at=start,queue_seconds=round(start-job['created_at'],3));save(job)
            token=usage_context.set(job['owner'])
            try:result=run(job['question'],job['mode'],user,emit)
            finally:usage_context.reset(token)
            if scope(job['owner'])!=job['scope']:raise PermissionError('执行期间权限已变更，结果未发布')
            safe={k:v for k,v in result.items() if k not in {'user','question'}}
            job.update(safe,cache_hit=False)
            if job['status']=='completed':r.setex(job['cache_key'],RESULT_TTL,encode(safe))
        except Exception as exc:
            from security import SecurityError
            # B2：把失败类型与"是否安全层拒绝"写进任务，审计里才能区分"查错了"和"被拦下了"。
            job.update(status='failed',error=str(exc)[:500],error_type=type(exc).__name__,
                       denied=isinstance(exc,SecurityError));job.pop('results',None);job.pop('report',None)
        job['duration_seconds']=round(time.time()-job['created_at'],2);save(job)
        folder=ROOT/'artifacts'/'runs';folder.mkdir(exist_ok=True)
        (folder/(job_id+'.json')).write_text(encode(job),encoding='utf-8')
        audit(job['owner'],'query_finished',finished_detail(job))
    await asyncio.get_running_loop().run_in_executor(_EXECUTOR,work)

class WorkerSettings:
    handle_signals=False
    functions=[execute_query]
    redis_settings=RedisSettings.from_dsn(REDIS_URL)
    max_jobs=20
    job_timeout=600
    max_tries=1
    keep_result=TTL
    health_check_interval=15
