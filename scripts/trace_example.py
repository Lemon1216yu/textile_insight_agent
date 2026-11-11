"""Generate an actual, reviewable query trace outside the business website."""
import sys,json
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.agent import single_query
from textile.settings import ROOT
from security import UserContext

def main():
    question='2026年8月按客户名称统计已完成订单的营业收入，按下单日期归属月份，收入降序排列。'
    events=[]
    result=single_query(question,UserContext('inspection','admin'),
                        emit=lambda stage,message,*details:events.append(dict(stage=stage,message=message)))
    target=ROOT/'artifacts'/'storage-inspection'
    target.mkdir(parents=True,exist_ok=True)
    result['checked_at']=datetime.now().isoformat(timespec='seconds')
    result['events']=events
    (target/'query-trace.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    r=result['retrieval']
    lines=['# 一次真实问数的输入与输出','',question,'',
           '当前运行口径按下单日期归属；交付日期口径是待接入的新指标方案。','',
           '## 1. 表召回','',*[f"- `{t['table_name']}`：相似度 {t['score']}" for t in r['tables']],
           '', '## 2. 字段召回','',*[f"- `{f['table_name']}.{f['name']}`：{f['text']}" for f in r['fields']],
           '', '## 3. Join 路径','', '```json',json.dumps({'paths':r['paths'],'relations':r['relations']},ensure_ascii=False,indent=2),'```',
           '', '## 4. 指标召回','',*[f"- {m['name']}：{m['text']}" for m in r['metrics']],
           '', '## 5. 实际注入模型的 Schema','', '```text',r['schema'],'```',
           '', '## 6. 经过安全校验、实际执行的 SQL','', '```sql',result['sql'],'```',
           '', '## 7. MySQL 返回的结果','', '```json',json.dumps(result['rows'],ensure_ascii=False,indent=2,default=str),'```',
           '', '## 8. 执行诊断与纠错记录','', '```json',json.dumps({'execution':result['execution'],'attempts':result['attempts']},ensure_ascii=False,indent=2,default=str),'```',
           '', '说明：此脚本实际调用 Embedding 和 SQL 模型并执行 MySQL；到结果集结束，没有调用报告模型。完整网站链路随后调用报告节点。']
    (target/'query-trace.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'success':result['success'],'rows':result['rows'],'sql':result['sql'],'output':str(target/'query-trace.md')},ensure_ascii=False,default=str))

if __name__=='__main__': main()
