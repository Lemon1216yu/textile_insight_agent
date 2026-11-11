"""Real execution-result comparison against explicit gold SQL; never canned answers."""
import sys,json,time,math,argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.agent import single_query
from textile.db import query
from security import UserContext

CASES=[
 ('simple','2026年3月至8月营业收入合计是多少元？只返回收入一个指标。',"SELECT SUM(net_amount) FROM sales_orders WHERE order_status='已完成' AND delivery_date IS NOT NULL AND delivery_date>='2026-03-01' AND delivery_date<'2026-09-01'"),
 ('simple','2026年8月已完成销售订单有多少笔？只返回笔数。',"SELECT COUNT(*) FROM sales_orders WHERE order_status='已完成' AND delivery_date IS NOT NULL AND delivery_date>='2026-08-01' AND delivery_date<'2026-09-01'"),
 ('medium','2026年3月至8月按客户名称统计营业收入元，只返回客户名称和收入，收入降序排列。',"SELECT c.customer_name,SUM(s.net_amount) FROM sales_orders s JOIN dim_customers c ON s.customer_id=c.customer_id WHERE s.order_status='已完成' AND s.delivery_date IS NOT NULL AND s.delivery_date>='2026-03-01' AND s.delivery_date<'2026-09-01' GROUP BY c.customer_name ORDER BY SUM(s.net_amount) DESC"),
 ('medium','2026年8月整体生产良品率百分比是多少？只返回良品率，不要四舍五入。',"SELECT (SUM(actual_meters)-SUM(defect_meters))/NULLIF(SUM(actual_meters),0)*100 FROM production_batches WHERE production_date>='2026-08-01' AND production_date<'2026-09-01'"),
 ('complex','最近库存快照，各面料90天以上库龄库存占比百分比是多少？只返回面料名称、占比，不要四舍五入。',"SELECT p.product_name,SUM(i.aged_90_meters)/NULLIF(SUM(i.quantity),0)*100 FROM inventory_snapshots i JOIN dim_products p ON i.product_id=p.product_id WHERE i.snapshot_date=(SELECT MAX(snapshot_date) FROM inventory_snapshots) GROUP BY p.product_name"),
 ('complex','2026年8月经营利润是多少元？按销售毛利减期间费用的简化管理口径，只返回一个经营利润指标。',"SELECT (SELECT SUM(net_amount-cost_amount) FROM sales_orders WHERE order_status='已完成' AND delivery_date IS NOT NULL AND delivery_date>='2026-08-01' AND delivery_date<'2026-09-01')-(SELECT SUM(amount) FROM finance_expenses WHERE expense_date>='2026-08-01' AND expense_date<'2026-09-01') AS operating_profit"),
]

def equal(a,b):
    if len(a)!=len(b):return False
    def normalized(rows):return sorted([list(r.values()) for r in rows],key=lambda r:str(r[0]))
    for x,y in zip(normalized(a),normalized(b)):
        if len(x)!=len(y):return False
        for i,j in zip(x,y):
            if i is None or j is None:
                if i!=j:return False
            else:
                try:
                    if not math.isclose(float(i),float(j),rel_tol=1e-5,abs_tol=.001):return False
                except (TypeError,ValueError):
                    if str(i)!=str(j):return False
    return True

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-few-shot',action='store_true');args=parser.parse_args()
    def evaluate(case):
        level,question,gold=case;start=time.time()
        expected=query(gold)['rows']
        try:
            result=single_query(question,UserContext.demo_admin(),use_few_shot=not args.no_few_shot)
            passed=equal(expected,result['rows'])
            record={'level':level,'question':question,'passed':passed,'gold_sql':gold,'generated_sql':result['sql'],'expected':expected,'actual':result['rows'],'retrieved_tables':[t['table_name'] for t in result['retrieval']['tables']]}
        except Exception as e: record={'level':level,'question':question,'passed':False,'error':str(e),'gold_sql':gold}
        record['seconds']=round(time.time()-start,2)
        print(json.dumps({'level':level,'passed':record['passed'],'question':question},ensure_ascii=False),flush=True)
        return record
    with ThreadPoolExecutor(2) as ex: records=list(ex.map(evaluate,CASES))
    summary={'test_count':len(records),'passed':sum(r['passed'] for r in records),'execution_accuracy':sum(r['passed'] for r in records)/len(records),'few_shot':not args.no_few_shot,'note':'Small synthetic validation set, not enterprise benchmark or the resume 91% claim','cases':records}
    out=Path('artifacts/evaluation-'+('baseline' if args.no_few_shot else 'few-shot')+'.json');out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(summary,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'},ensure_ascii=False))

if __name__=='__main__': main()
