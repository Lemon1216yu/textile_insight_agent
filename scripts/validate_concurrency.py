"""Twenty real jobs through HTTP + arq, measuring admission and queue time separately."""
import asyncio,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from textile.settings import ROOT

async def main():
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8018',timeout=90) as client:
        (await client.post('/api/login',json={'username':'executive','password':'demo123'})).raise_for_status()
        questions=[f'2026年{month}月{metric}是多少？只返回该指标数值。' for month in [3,4,5,6] for metric in ['营业收入','销售毛利','期间费用','生产良品率','采购金额']]
        async def submit(question):
            start=time.monotonic();response=await client.post('/api/jobs',json={'question':question})
            response.raise_for_status();return {'id':response.json()['id'],'admission_seconds':round(time.monotonic()-start,3)}
        records=await asyncio.gather(*(submit(q) for q in questions))
        deadline=time.monotonic()+600
        while True:
            jobs=await asyncio.gather(*(client.get('/api/jobs/'+r['id']) for r in records))
            data=[response.json() for response in jobs]
            if all(j['status'] not in ['queued','running'] for j in data):break
            if time.monotonic()>deadline:raise TimeoutError('jobs did not finish within 10 minutes')
            await asyncio.sleep(3)
        for record,job in zip(records,data):
            record.update(status=job['status'],queue_seconds=job.get('queue_seconds'),cache_hit=job.get('cache_hit',False),
                          duration_seconds=job.get('duration_seconds'),error=job.get('error'))
        result={'count':20,'accepted':len(records),'completed':sum(j['status']=='completed' for j in data),
                'maximum_admission_seconds':max(r['admission_seconds'] for r in records),'records':records,
                'note':'Real model calls. Submission latency and worker waiting are reported separately; this is not production load certification.'}
        (ROOT/'artifacts'/'concurrency-20.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False))
if __name__=='__main__':asyncio.run(main())
