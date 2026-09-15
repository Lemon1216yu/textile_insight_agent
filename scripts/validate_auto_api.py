"""Live acceptance through the same HTTP endpoints as the frontend."""
import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from textile.settings import ROOT

CASES=[
 ('2026年8月营业收入是多少元？只返回收入。','query','lightweight'),
 ('那上个月呢？','query','clarify'),
 ('分析2026年7月至8月相对5月至6月的利润变化，分别查看销售毛利和期间费用，列出待核实因素。','analysis',None),
]
if __name__=='__main__':
    records=[]
    with httpx.Client(base_url='http://127.0.0.1:8018',timeout=20) as client:
        response=client.post('/api/login',json={'username':'executive','password':'demo123'})
        response.raise_for_status()
        assert client.get('/data').status_code==404
        for question,mode,strategy in CASES:
            response=client.post('/api/jobs',json={'question':question})
            assert response.status_code==202,response.text
            job_id=response.json()['id']
            deadline=time.monotonic()+240
            while True:
                result=client.get('/api/jobs/'+job_id);result.raise_for_status();job=result.json()
                if job['status'] not in {'queued','running'}:break
                if time.monotonic()>deadline:raise TimeoutError(job_id)
                time.sleep(1)
            expected='needs_clarification' if strategy=='clarify' else 'completed'
            passed=job['status']==expected and job['mode']==mode
            if strategy=='lightweight':passed=passed and job['results'][0]['retrieval']['strategy']==strategy
            records.append({'passed':passed,'job':job})
            print(json.dumps({'passed':passed,'mode':job['mode'],'status':job['status'],'question':question,
                              'steps':len(job.get('results',[]))},ensure_ascii=False),flush=True)
    (ROOT/'artifacts'/'auto-api-smoke.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
    if not all(r['passed'] for r in records):sys.exit(1)
