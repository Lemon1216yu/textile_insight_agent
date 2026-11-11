"""分离测量 HTTP 提交路径：认证开销 vs _prepare 开销。不需要模型。"""
import asyncio, time, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx

BASE = 'http://127.0.0.1:8018'


async def measure(client, method, path, payload=None, n=1):
    async def one(i):
        t = time.perf_counter()
        if method == 'POST':
            r = await client.post(path, json=payload)
        else:
            r = await client.get(path)
        r.raise_for_status()
        return round((time.perf_counter() - t) * 1000, 1)
    return sorted(await asyncio.gather(*(one(i) for i in range(n))))


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=120) as client:
        await client.post('/api/login', json={'username': 'executive', 'password': 'demo123'})
        print('--- 1 request: GET /api/metrics (auth + 指标主数据, 无模型) ---')
        print(await measure(client, 'GET', '/api/metrics', n=1))
        print('--- 1 request: POST /api/jobs (完整提交路径, 无模型执行) ---')
        print(await measure(client, 'POST', '/api/jobs', {'question': '2026年8月营业收入是多少？只返回该指标数值。'}, n=1))
        print('--- 20 concurrent: GET /api/metrics (纯认证+主数据) ---')
        print(await measure(client, 'GET', '/api/metrics', n=20))
        print('--- 20 concurrent: POST /api/jobs (提交路径) ---')
        t = time.perf_counter()
        res = await measure(client, 'POST', '/api/jobs', {'question': '2026年8月采购金额是多少？只返回该指标数值。'}, n=20)
        print(res)
        print(f'wall={time.perf_counter()-t:.2f}s  max={max(res)}ms  median={res[len(res)//2]}ms')


asyncio.run(main())
