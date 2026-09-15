"""Small live routing smoke set; not the planned 30-50 case benchmark."""
import sys,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.understanding import understand
from textile.settings import ROOT
from security import UserContext

CASES=[
 ('2026年8月营业收入是多少元？只返回收入。','query','simple'),
 ('2026年8月整体生产良品率是多少？','query','simple'),
 ('最新库存数量合计是多少米？','query',None),
 ('2026年8月按客户名称统计营业收入，收入降序。','query','complex'),
 ('2026年8月经营利润是多少元？销售毛利减期间费用，只返回经营利润。','query','complex'),
 ('分析2026年7至8月相对5至6月的利润变化，分别查看收入毛利、费用和产品结构，并给出待核实因素。','analysis','complex'),
 ('那上个月呢？','clarify',None),
 ('帮我写一首关于月亮的诗。','clarify',None),
]
if __name__=='__main__':
    records=[]
    for question,intent,complexity in CASES:
        result=understand(question,UserContext('validation','admin'))
        passed=not result.fallback and result.intent==intent and (complexity is None or result.complexity==complexity)
        records.append(dict(question=question,expected_intent=intent,expected_complexity=complexity,
                            passed=passed,actual=result.model_dump()))
        print(json.dumps({'question':question,'passed':passed,'intent':result.intent,'complexity':result.complexity},ensure_ascii=False),flush=True)
    out=ROOT/'artifacts'/'routing-smoke.json'
    out.write_text(json.dumps({'count':len(records),'passed':sum(r['passed'] for r in records),'cases':records},ensure_ascii=False,indent=2),encoding='utf-8')
