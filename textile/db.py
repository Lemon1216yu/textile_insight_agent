"""Database execution: connection pool, error classification, EXPLAIN and timing."""
import threading
import time
import pymysql
from database import DatabaseClient, DatabaseConnectionPool
from security import SecurityError, UserContext
from textile import governance
from textile.security import TextileSecurity
from textile.settings import DB, QUERY_TIMEOUT_MS, SLOW_QUERY_MS

_local=threading.local()
def client():
    # A pool belongs to one worker thread: no cross-request mutable timing data or counter races.
    if not hasattr(_local,'db'):
        def connection():
            conn=pymysql.connect(**DB)
            # A8：语句超时写进会话变量（可配置），超时由 MySQL 强制中断而不是跑到底。
            governance.apply_timeout(conn, QUERY_TIMEOUT_MS)
            return conn
        _local.db=DatabaseClient(db_config=DB,security_manager=TextileSecurity(),
            connection_pool=DatabaseConnectionPool(connection,2,0,3),slow_query_threshold_ms=SLOW_QUERY_MS)
    return _local.db

def query(sql,user=None,record_governance=True):
    """执行只读查询。

    record_governance=False 用于健康检查这类自检查询，避免自己的探活把治理计数刷成假数据。
    安全层拒绝、EXPLAIN 预检失败、执行失败都算一次"查询尝试"并计入治理统计——否则
    "被拦下的查询"永远不会出现在统计里（评审 F2）。预检失败的原始 pymysql 异常会被翻译成
    与执行路径一致的 QueryExecutionError（评审 F4），SecurityError 原样抛出（agent 依赖它判重试）。
    """
    db=client(); user=user or UserContext.demo_admin()
    started=time.perf_counter()
    try:
        secured=db.security.secure_sql(sql,user)
        # Preflight read-only EXPLAIN; execute validates the original SQL independently.
        conn=db.connection_pool.acquire()
        try:
            with conn.cursor() as c:
                c.execute('EXPLAIN '+secured)
                explain=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]
        finally: db.connection_pool.release(conn)
        columns,rows=db.execute(sql,user)
    except Exception as exc:
        elapsed_ms=(time.perf_counter()-started)*1000
        final=exc if isinstance(exc,SecurityError) else _translate(db,exc,sql,elapsed_ms)
        if record_governance:
            governance.record(sql,elapsed_ms,timeout_ms=QUERY_TIMEOUT_MS,slow_ms=SLOW_QUERY_MS,error=final)
        if final is exc: raise
        raise final from exc
    elapsed_ms=(time.perf_counter()-started)*1000
    outcome=governance.record(sql,elapsed_ms,timeout_ms=QUERY_TIMEOUT_MS,slow_ms=SLOW_QUERY_MS) if record_governance else None
    execution={**db.last_query_info,'explain':explain}
    if outcome:
        # 键名用 elapsed_ms 以免与 database.py 的 duration_ms（不含 secure_sql/EXPLAIN）混淆。
        execution['governance']=outcome
    return {'sql':db.last_query_info['sql'],'columns':columns,'rows':[dict(zip(columns,r)) for r in rows],
            'row_count':len(rows),'execution':execution,'limited_to':200}

def _translate(db,exc,sql,elapsed_ms):
    """将预检错误统一转换为 QueryExecutionError。"""
    translator=getattr(db,'_translate_db_error',None)
    if translator is None: return exc
    try:
        return translator(exc,sql,round(elapsed_ms,2))
    except Exception:
        return exc
