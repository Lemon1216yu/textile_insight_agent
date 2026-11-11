"""52 real SQL-result comparisons; canonical metric definitions are the gold source."""
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
    # A10 收尾：新增 12 个多表 join 用例，把「真实问数」的表覆盖从 8 张扩展表扩到 20 张，
    # 每个业务域都有 join 用例；并补两类更难形状：三表链路（事实->设备->车间）与平均值口径。
    # gold SQL 均已预验证返回非空（预验证脚本见 artifacts/join-eval-prep/，产物不入库）。
    for table,dim,key,name,value,domain,agg in [
        ('sales_contracts','dim_customers','customer_id','customer_name','contract_amount','销售','SUM'),
        ('sales_shipments','dim_products','product_id','product_name','shipped_meters','销售','SUM'),
        ('dyeing_batches','dim_colors','color_id','color_name','input_meters','生产','SUM'),
        ('work_orders','dim_products','product_id','product_name','completed_meters','生产','SUM'),
        ('material_consumption','dim_materials','material_id','material_name','consumed_kg','生产','SUM'),
        ('purchase_returns','dim_suppliers','supplier_id','supplier_name','refund_amount','采购','SUM'),
        ('stock_transfers','dim_warehouses','warehouse_id','warehouse_name','transferred_meters','库存','SUM'),
        ('inventory_aging','dim_products','product_id','product_name','quantity_meters','库存','SUM'),
        ('incoming_inspections','dim_materials','material_id','material_name','rejected_kg','质量','SUM'),
        ('cash_receipts','dim_customers','customer_id','customer_name','receipt_amount','财务','SUM'),
        # 非可加度量：取平均，必须保留完整精度
        ('supplier_evaluations','dim_suppliers','supplier_id','supplier_name','quality_score','采购','AVG')]:
        if agg=='AVG':
            question=f'查询业务表{table}，关联{dim}，按{name}计算{value}的平均值，保留完整精度不四舍五入，只返回名称和平均值。'
        else:
            question=f'查询业务表{table}，关联{dim}，按{name}汇总{value}，覆盖全部样本，只返回名称和总量，不四舍五入。'
        result.append({'id':table,'domain':domain,'question':question,
            'gold_sql':f'SELECT d.{name},{agg}(f.{value}) FROM {table} f JOIN {dim} d ON f.{key}=d.{key} GROUP BY d.{name}'})
    result.append({'id':'maintenance_orders','domain':'生产',
        'question':'查询业务表maintenance_orders（设备保养维修工单），经设备关联到dim_workshops，按workshop_name汇总maintenance_cost，覆盖全部样本，只返回名称和总量，不四舍五入。',
        'gold_sql':'SELECT w.workshop_name,SUM(f.maintenance_cost) FROM maintenance_orders f JOIN dim_machines m ON f.machine_id=m.machine_id JOIN dim_workshops w ON m.workshop_id=w.workshop_id GROUP BY w.workshop_name'})
    return result

def write_report(report,path=None):
    """写入评测报告；覆盖前把上一次结果存档（归档逻辑见 scripts/artifact_io.py）。"""
    from scripts.artifact_io import write_json
    path=path or ROOT/'artifacts'/'evaluation-expanded.json'
    archived=write_json(report,path)
    if archived: print(json.dumps({'archived_previous':archived.name},ensure_ascii=False),flush=True)

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
    write_report(report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False))
if __name__=='__main__':main()
