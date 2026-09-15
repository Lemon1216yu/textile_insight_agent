"""Bounded local operational counters and alerts; no prompts or credentials."""
import json,time,logging
from textile.registry import redis_client

def http_event(method,path,status,seconds):
    try:
        r=redis_client();day=time.strftime('%Y-%m-%d')
        event={'time':time.time(),'method':method,'path':path,'status':status,'seconds':round(seconds,3)}
        pipe=r.pipeline();key='textile:http:'+day
        pipe.hincrby(key,'requests',1);pipe.hincrby(key,'errors',int(status>=500));pipe.hincrbyfloat(key,'seconds',seconds);pipe.expire(key,86400*8)
        pipe.lpush('textile:http:events',json.dumps(event));pipe.ltrim('textile:http:events',0,999)
        if status>=500 or seconds>10:
            pipe.lpush('textile:alerts',json.dumps({'kind':'http_error' if status>=500 else 'slow_request',**event}));pipe.ltrim('textile:alerts',0,199)
        pipe.execute()
    except Exception:logging.getLogger(__name__).warning('http_metrics_unavailable')

def operations_summary():
    from textile.app_pool import app_cursor
    r=redis_client();day=time.strftime('%Y-%m-%d');c=r.hgetall('textile:http:'+day)
    with app_cursor(dict_cursor=True) as cur:
        cur.execute('SELECT username,role FROM sys_users WHERE active=1');users=cur.fetchall()
    usage=[];roles={}
    for u in users:
        tokens=int(r.get(f"textile:tokens:{u['username']}:{day}") or 0)
        usage.append({**u,'tokens':tokens});roles[u['role']]=roles.get(u['role'],0)+tokens
    return {'day':day,'http':c,'mean_http_seconds':float(c.get('seconds',0))/max(1,int(c.get('requests',0))),
            'queued':r.zcard('arq:queue'),'worker_alive':bool(r.exists('arq:queue:health-check')),
            'users':usage,'roles':roles,'alerts':[json.loads(x) for x in r.lrange('textile:alerts',0,49)],
            'note':'Local operational sample; role totals are not real department accounting. No external notifications configured.'}
