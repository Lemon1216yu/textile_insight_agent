"""40 real SQL-result comparisons; canonical metric definitions are the gold source."""
import sys,json,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.registry import get_metrics
from textile.metric_catalog import compile_sql
from textile.agent import single_query
from textile.db import query
from textile.settings import ROOT, MODEL
from textile.task_queue import prompt_revision
from security import UserContext
from scripts.evaluate_textile import equal

def cases():
    result=[]
    for m in get_metrics():
        question=f"2026年8月{m['name']}是多少？按指标{m['code']}的正式管理口径，仅返回一个数值，单位{m['unit']}，不四舍五入。"
        result.append({'id':m['code'],'domain':m['domain'],'question':question,'gold_sql':compile_sql(m,'2026-08-01','2026-09-01')})
    for table,dim,key,name,value,domain in [
        ('sales_quotes','dim_customers','customer_id','customer_name','quote_price','销售'),
        ('machine_downtime','dim_machines','machine_id','machine_name','downtime_minutes','生产'),
        ('goods_receipts','dim_materials','material_id','material_name','accepted_kg','采购'),
        ('stock_counts','dim_warehouses','warehouse_id','warehouse_name','counted_meters','库存'),
        ('finished_inspections','dim_products','product_id','product_name','qualified_meters','质量'),
        ('accounts_receivable','dim_customers','customer_id','customer_name','receivable_amount','财务'),
        ('energy_readings','dim_workshops','workshop_id','workshop_name','electricity_kwh','生产'),
        ('cost_allocations','dim_departments','department_id','department_name','allocated_amount','财务')]:
        result.append({'id':table,'domain':domain,
            'question':f'查询扩展业务表{table}，关联{dim}，按{name}汇总{value}，覆盖全部样本，只返回名称和总量，不四舍五入。',
            'gold_sql':f'SELECT d.{name},SUM(f.{value}) FROM {table} f JOIN {dim} d ON f.{key}=d.{key} GROUP BY d.{name}'})
    return result

def main():
    from textile.models import last_call
    def evaluate(case):
        record=dict(case);start=time.time()
        try:
            expected=query(case['gold_sql'])['rows']
            actual=single_query(case['question'],UserContext('evaluation','admin'))
            record.update(passed=equal(expected,actual['rows']),expected=expected,actual=actual['rows'],sql=actual['sql'],
                          strategy=actual['retrieval']['strategy'])
        except Exception as exc:record.update(passed=False,error=str(exc))
        # 实际服务的模型：额度耗尽时会自动降级到链上的下一个模型，
        # 只记配置的首选模型会把证据归错模型。last_call() 按上下文隔离，
        # 并发评测时不会像实例属性 last_model 那样被别的线程覆盖。
        used=last_call()
        record['model']=used['model']
        record['fallback']=bool(used['fallback'])
        record['seconds']=round(time.time()-start,2)
        print(json.dumps({'id':case['id'],'passed':record['passed'],'model':record['model']},ensure_ascii=False),flush=True)
        return record
    with ThreadPoolExecutor(2) as pool:results=list(pool.map(evaluate,cases()))
    used_models=sorted({r.get('model') for r in results if r.get('model')})
    report={'model':MODEL,'models_used':used_models,'fallback_used':any(r.get('fallback') for r in results),
            'prompt_version':prompt_revision(),'cases':results,'count':len(results),'passed':sum(r['passed'] for r in results)}
    report['execution_accuracy']=report['passed']/report['count']
    report['note']='Synthetic functional regression, not production accuracy; no historical 70%-91% claim.'
    (ROOT/'artifacts'/'evaluation-expanded.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
if __name__=='__main__':main()
