"""验证应用账号连接池：连接复用、并发下建连次数。"""
import sys, time, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import textile.app as appmod
import textile.task_queue as tq
from textile.app_pool import app_pool, app_cursor

print('--- 基础调用 ---')
print('fetch_user:', appmod.fetch_user('executive')['username'], '| name:', appmod.fetch_user('executive')['display_name'])
print('account:', tq.account('executive')['role'])
tq.audit('executive', 'pool_probe', {'ok': 1})
with app_cursor(dict_cursor=True) as cur:
    cur.execute('SELECT COUNT(*) AS n FROM sys_users'); print('sys_users rows:', cur.fetchone()['n'])

print('--- 连接复用（10 次调用后的池内实建连接数）---')
for _ in range(10):
    appmod.fetch_user('executive'); tq.account('executive'); tq.audit('executive', 'pool_probe', {'i': 1})
print('total_connections created:', app_pool()._total_connections, '(应远小于 30)')

print('--- 20 并发调用（模拟并发请求的认证+审计）---')
def work(i):
    appmod.fetch_user('executive'); tq.account('executive'); tq.audit('executive', 'pool_probe', {'c': i})
t = time.perf_counter()
with ThreadPoolExecutor(max_workers=20) as pool:
    list(pool.map(work, range(20)))
wall = time.perf_counter() - t
print(f'20 concurrent x3 calls = {wall*1000:.0f}ms | pool connections = {app_pool()._total_connections}')
print('redis client singleton:', tq.redis_client() is tq.redis_client())
print('OK')
