"""A8 SQL 资源治理：查询超时、慢查询记录与计数（供 /api/health 暴露）。

为什么单独成模块：
1. 计数与日志是横切关注点，散在 db/agent 里会重复；集中一处便于测试与暴露。
2. 断言要能"无模型"验证：本模块不含任何模型调用，计数器与日志可直接单测。
3. 超时由 MySQL 的 `max_execution_time` 强制（SELECT 专用），Python 侧不重复实现中断逻辑，
   只负责"设置会话变量 + 识别超时错误 + 记录"。

两条来自独立评审的硬约束（均已用真实路径复现过）：
- **超时识别必须覆盖翻译层**：`database.py::_translate_db_error` 会把原始 3024 改写成
  `QueryExecutionError(error_type='query_timeout', metadata.error_code=3024)`，原始码文本全部丢失。
  只匹配原始错误码/文本会在真实入口（`textile.db.query`）漏判，把超时错记成普通 error。
- **计数必须区分作用域**：真实查询在 arq worker 进程执行，API 进程读不到它的内存计数；
  因此除本进程计数外，同步一份 Redis 汇总（best-effort，Redis 不可用不影响查询）。
"""
import logging
import threading

LOG = logging.getLogger('textile.sql')

# MySQL 中断语句时的错误码：3024 = max_execution_time 超时，1317 = 语句被中断
# （实测同一台 MySQL 上两表自连接报 3024、三表自连接报 1317）。
MYSQL_TIMEOUT_CODES = (3024, 1317)
TIMEOUT_MARKERS = ('maximum statement execution time exceeded', 'Query execution was interrupted')
# 翻译层给出的超时类型（database.py::_translate_db_error 的 error_type）。
TRANSLATED_TIMEOUT_TYPES = ('query_timeout',)
FIELDS = ('queries', 'slow_queries', 'timeouts')
SHARED_KEY = 'textile:sql:counters'


class _Counters:
    """进程内计数（带锁，并发/评测场景下不会丢计数）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._values = {field: 0 for field in FIELDS}

    def bump(self, key, amount=1):
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def snapshot(self):
        with self._lock:
            return dict(self._values)

    def reset(self):
        with self._lock:
            self._values = {field: 0 for field in FIELDS}


COUNTERS = _Counters()


def _error_code(exc):
    """原始 pymysql 错误码；翻译后的异常把码放在 metadata.error_code。"""
    metadata = getattr(exc, 'metadata', None)
    if isinstance(metadata, dict) and metadata.get('error_code') is not None:
        return metadata.get('error_code')
    args = getattr(exc, 'args', None)
    return args[0] if args else None


def is_timeout(exc):
    """判断异常是否为"语句超时被杀"，而不是语法/权限错误。

    同时覆盖三种形态：原始 pymysql 码、翻译层 error_type、错误文本标记。
    """
    if getattr(exc, 'error_type', None) in TRANSLATED_TIMEOUT_TYPES:
        return True
    if _error_code(exc) in MYSQL_TIMEOUT_CODES:
        return True
    text = str(exc)
    return any(marker in text for marker in TIMEOUT_MARKERS)


def apply_timeout(conn, timeout_ms):
    """把语句超时写进会话变量（MySQL 8：max_execution_time 仅作用于只读 SELECT）。"""
    with conn.cursor() as cursor:
        cursor.execute('SET SESSION max_execution_time=%s', (int(timeout_ms),))
    return int(timeout_ms)


def _shared_bump(field):
    """best-effort 写跨进程汇总；Redis 不可用或不支持时静默跳过，绝不影响查询。"""
    try:
        from textile.registry import redis_client
        redis_client().hincrby(SHARED_KEY, field, 1)
    except Exception:
        pass


def record(sql, duration_ms, timeout_ms=None, slow_ms=None, error=None):
    """记录一次查询：计数（本进程 + Redis 汇总）+ 超阈值写结构化日志。

    返回 {'kind': 'ok'|'slow'|'timeout'|'error', 'elapsed_ms': float}
    """
    duration_ms = round(float(duration_ms), 2)
    COUNTERS.bump('queries')
    _shared_bump('queries')
    if error is not None and is_timeout(error):
        kind, field = 'timeout', 'timeouts'
    elif error is not None:
        kind, field = 'error', None
    elif slow_ms is not None and duration_ms >= slow_ms:
        kind, field = 'slow', 'slow_queries'
    else:
        kind, field = 'ok', None
    if field:
        COUNTERS.bump(field)
        _shared_bump(field)
    if kind == 'timeout':
        LOG.warning('sql_timeout elapsed_ms=%s timeout_ms=%s sql=%s', duration_ms, timeout_ms, _short(sql))
    elif kind == 'error':
        LOG.warning('sql_error elapsed_ms=%s error=%s sql=%s', duration_ms, type(error).__name__, _short(sql))
    elif kind == 'slow':
        LOG.warning('sql_slow elapsed_ms=%s slow_ms=%s sql=%s', duration_ms, slow_ms, _short(sql))
    return {'kind': kind, 'elapsed_ms': duration_ms}


def _short(sql, limit=160):
    text = ' '.join(str(sql).split())
    return text if len(text) <= limit else text[:limit] + '...'


def _shared_snapshot():
    try:
        from textile.registry import redis_client
        raw = redis_client().hgetall(SHARED_KEY) or {}
        data = {}
        for field in FIELDS:
            value = raw.get(field) if isinstance(raw, dict) else None
            data[field] = int(value or 0)
        return data, True
    except Exception:
        return {}, False


def stats(reset=False):
    """给 /api/health 用的只读快照。

    scope=process 表示这些计数只属于当前进程；shared 是 Redis 汇总（含 arq worker 进程）。
    """
    from textile.settings import QUERY_TIMEOUT_MS, SLOW_QUERY_MS
    snapshot = {'scope': 'process', **COUNTERS.snapshot(),
                'query_timeout_ms': QUERY_TIMEOUT_MS, 'slow_query_ms': SLOW_QUERY_MS}
    if reset:
        COUNTERS.reset()
    shared, available = _shared_snapshot()
    snapshot['shared'] = shared
    snapshot['shared_available'] = available
    return snapshot
