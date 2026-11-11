"""应用账号（sys_users / audit_events / metric_registry）的 MySQL 连接池。

背景：这些路径此前每次调用都 `pymysql.connect(**APP_DB)` 新建连接。一次任务提交会产生
3 次建连（认证 1 + 权限范围 1 + 审计 1），20 并发即约 60 次建连；本机 MySQL 跑在 Docker
端口转发下，单次建连约 40ms 且并发时相互争抢，实测把提交延迟从 186ms 放大到 2422ms。
复用连接后单次请求降到毫秒级。

注意：pymysql 的 `with connection as conn:` 只做提交/回滚，**不会关闭连接**，
所以不能靠它归还连接池。这里用 `app_connection()` 包装，在 with 结束时显式归还。
"""
import threading
from contextlib import contextmanager

import pymysql

from database import DatabaseConnectionPool
from textile.settings import APP_DB

POOL_SIZE = 12
MAX_OVERFLOW = 8
POOL_TIMEOUT = 5

_pool = None
_lock = threading.Lock()


def app_pool():
    """进程内共享的应用账号连接池（懒加载，线程安全）。"""
    global _pool
    if _pool is None:
        with _lock:
            if _pool is None:
                _pool = DatabaseConnectionPool(
                    connection_factory=lambda: pymysql.connect(**APP_DB),
                    pool_size=POOL_SIZE, max_overflow=MAX_OVERFLOW, pool_timeout=POOL_TIMEOUT)
    return _pool


class PooledConnection:
    """`with app_connection() as conn:` 结束时把连接归还连接池。

    对外暴露的就是原生 pymysql 连接，调用方无需改动 cursor 用法。
    """

    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        self._pool.release(self._conn)
        return False

    def __getattr__(self, name):
        return getattr(self._conn, name)


def app_connection():
    return PooledConnection(app_pool(), app_pool().acquire())


@contextmanager
def app_cursor(dict_cursor=False):
    """单条语句的便捷写法：自动获取/归还连接。"""
    conn = app_pool().acquire()
    try:
        with conn.cursor(pymysql.cursors.DictCursor if dict_cursor else pymysql.cursors.Cursor) as cur:
            yield cur
    finally:
        app_pool().release(conn)
