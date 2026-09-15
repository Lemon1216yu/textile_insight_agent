"""Reuse MVP DatabaseClient: pool, error classification, slow EXPLAIN, timing."""
import threading
import pymysql
from database import DatabaseClient, DatabaseConnectionPool
from security import UserContext
from textile.security import TextileSecurity
from textile.settings import DB

_local=threading.local()
def client():
    # A pool belongs to one worker thread: no cross-request mutable timing data or counter races.
    if not hasattr(_local,'db'):
        def connection():
            conn=pymysql.connect(**DB)
            with conn.cursor() as c: c.execute('SET SESSION max_execution_time=8000')
            return conn
        _local.db=DatabaseClient(db_config=DB,security_manager=TextileSecurity(),
            connection_pool=DatabaseConnectionPool(connection,2,0,3),slow_query_threshold_ms=200)
    return _local.db

def query(sql,user=None):
    db=client(); user=user or UserContext.demo_admin()
    secured=db.security.secure_sql(sql,user)
    # Preflight read-only EXPLAIN; execute validates the original SQL independently.
    conn=db.connection_pool.acquire()
    try:
        with conn.cursor() as c:
            c.execute('EXPLAIN '+secured)
            explain=[dict(zip([d[0] for d in c.description],r)) for r in c.fetchall()]
    finally: db.connection_pool.release(conn)
    columns,rows=db.execute(sql,user)
    return {'sql':db.last_query_info['sql'],'columns':columns,'rows':[dict(zip(columns,r)) for r in rows],
            'row_count':len(rows),'execution':{**db.last_query_info,'explain':explain},'limited_to':200}
