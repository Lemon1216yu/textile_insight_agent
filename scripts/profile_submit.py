"""逐段测量任务提交路径的耗时，定位剩余固定开销（不需要模型）。"""
import sys, time, os, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymysql

from textile.settings import APP_DB, ROOT
import textile.registry as rg
import textile.task_queue as tq
from textile.security import allowed_catalog
from security import UserContext


def timed(label, fn, n=5):
    times = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(f"{label:38s} min={times[0]:7.1f}ms  median={times[len(times)//2]:7.1f}ms  max={times[-1]:7.1f}ms")


print("=== 单次调用耗时（顺序，各5次）===")
timed("pymysql.connect(APP_DB)", lambda: pymysql.connect(**APP_DB).close())
timed("account('executive')", lambda: tq.account('executive'))
timed("scope('executive')", lambda: tq.scope('executive'))
timed("allowed_catalog(executive)", lambda: allowed_catalog(UserContext('executive', 'executive', None)))
timed("metrics_revision()", rg.metrics_revision)
timed("prompt_revision()", tq.prompt_revision)
timed("redis INC+EXPIRE", lambda: (rg.redis_client().incr('textile:probe:x'), rg.redis_client().expire('textile:probe:x', 120)))
timed("audit() 单次写", lambda: tq.audit('executive', 'probe', {'t': 1}))

print()
print("=== _prepare 整体 ===")
user = UserContext('executive', 'executive', None)
timed("_prepare(seq)", lambda: tq._prepare('2026年8月营业收入是多少？', 'auto', user), n=5)

print()
print("=== 20 并发 _prepare（模拟 20 个同时提交）===")
t = time.perf_counter()
with ThreadPoolExecutor(max_workers=20) as pool:
    list(pool.map(lambda i: tq._prepare(f'2026年{3+i%4}月营业收入是多少？{i}', 'auto', user), range(20)))
print(f"20 concurrent _prepare total = {(time.perf_counter()-t)*1000:.0f}ms")

print()
print("=== 关键静态量 ===")
print("allowed_catalog size:", len(json.dumps(allowed_catalog(UserContext('executive', 'executive', None)), ensure_ascii=False)))
