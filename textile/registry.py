"""Published metric master data in MySQL; Redis is a disposable 60s read cache."""
import json,os,threading
import pymysql
from redis import Redis
from textile.settings import APP_DB
from textile.app_pool import app_cursor

# 复用同一个 Redis 客户端（redis-py 内部维护连接池且线程安全）。
# 之前每次调用都新建连接：一次任务提交要建 5~7 条连接，在事件循环里同步串行，
# 是并发提交延迟偏高的主要原因之一。
_CLIENT=None
_CLIENT_LOCK=threading.Lock()

def redis_client():
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                _CLIENT=Redis.from_url(os.getenv('TEXTILE_REDIS_URL','redis://127.0.0.1:6379/0'),
                                       decode_responses=True,socket_connect_timeout=2,socket_timeout=3,
                                       max_connections=64,health_check_interval=30)
    return _CLIENT

def get_metrics():
    cache=redis_client()
    try:
        raw=cache.get('textile:metrics:published:v1')
        if raw:return json.loads(raw)
    except Exception:pass
    with app_cursor() as cur:
        cur.execute("SELECT definition FROM metric_registry WHERE status='published' ORDER BY code")
        result=[json.loads(row[0]) if isinstance(row[0],str) else row[0] for row in cur.fetchall()]
    if not result:raise RuntimeError('指标主数据尚未初始化')
    try:cache.setex('textile:metrics:published:v1',60,json.dumps(result,ensure_ascii=False))
    except Exception:pass
    return result

def metrics_revision():
    import hashlib
    return hashlib.sha256(json.dumps(get_metrics(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
