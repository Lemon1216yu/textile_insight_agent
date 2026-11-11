import json
import pytest
from security import UserContext
from textile import understanding as u
from textile import agent
from textile.retrieval import lightweight_context

ADMIN=UserContext('test','admin')

def mock_model(monkeypatch, payload):
    class Model:
        def generate_json(self,*args):
            if isinstance(payload,Exception): raise payload
            return json.dumps(payload,ensure_ascii=False)
    monkeypatch.setattr(u,'llm',lambda:Model())

def payload(**values):
    return dict(intent='query',complexity='simple',rewrite='2026年8月营业收入是多少元？',
                tables=['sales_orders'],metric_codes=['SAL-001'],**values)

@pytest.mark.parametrize('question',['','  ','a'*1201,'收入\x00'])
def test_invalid_input_never_calls_model(monkeypatch,question):
    monkeypatch.setattr(u,'llm',lambda:pytest.fail('invalid input reached LLM'))
    with pytest.raises(ValueError):u.understand(question,ADMIN)

def test_single_table_lightweight_and_restricted_fields(monkeypatch):
    mock_model(monkeypatch,payload())
    sales=UserContext('s','sales','华东')
    result=u.understand('2026年8月营业收入是多少元？',sales)
    linked=lightweight_context(sales,result)
    assert linked['strategy']=='lightweight'
    assert 'net_amount' in linked['schema'] and 'cost_amount' not in linked['schema']
    assert linked['metrics'][0]['name']

def test_cross_table_metric_cannot_enter_lightweight(monkeypatch):
    p=payload();p['metric_codes']=['FIN-005']
    mock_model(monkeypatch,p)
    result=u.understand('2026年8月经营利润是多少？',ADMIN)
    assert result.complexity=='complex'

def test_customer_grouping_cannot_use_sales_only(monkeypatch):
    mock_model(monkeypatch,payload())
    assert u.understand('2026年8月按客户名称统计收入',ADMIN).complexity=='complex'

@pytest.mark.parametrize('model_result',[{'intent':'unknown'},RuntimeError('unavailable'),
    dict(intent='query',complexity='simple',rewrite='读取账户',tables=['sys_users'])])
def test_failure_keeps_original_and_full_linking(monkeypatch,model_result):
    mock_model(monkeypatch,model_result)
    result=u.understand('2026年8月收入，只返回收入',ADMIN)
    assert result.fallback and result.rewrite=='2026年8月收入，只返回收入'
    assert result.intent=='query' and result.complexity=='complex'

def test_clarification_does_not_execute(monkeypatch):
    mock_model(monkeypatch,dict(intent='clarify',complexity='complex',rewrite='那上个月呢？',
                               clarification='请补充要查询的指标。'))
    monkeypatch.setattr(agent,'query',lambda *a:pytest.fail('clarification executed SQL'))
    result=agent.run('那上个月呢？','auto',ADMIN)
    assert result['status']=='needs_clarification' and result['results']==[]

def test_auto_single_query_reuses_understanding(monkeypatch):
    prepared=u.Understanding(**payload())
    calls=[]
    monkeypatch.setattr(agent,'understand',lambda *a:prepared)
    def single(question,user,emit,context,**kwargs):
        calls.append(kwargs['understanding'])
        return {'success':True,'question':question,'sql':'SELECT 1','rows':[{'value':1}],'columns':['value']}
    monkeypatch.setattr(agent,'single_query',single)
    class Reporter:
        def generate_text(self,*args):return '收入为1元。[步骤1]'
    monkeypatch.setattr(agent,'llm',lambda:Reporter())
    result=agent.run(prepared.rewrite,'auto',ADMIN)
    assert result['mode']=='query' and result['status']=='completed' and calls==[prepared]

def test_analysis_subtasks_reuse_query_pipeline(monkeypatch):
    prepared=u.Understanding(intent='analysis',complexity='complex',rewrite='分析收入与费用')
    monkeypatch.setattr(agent,'understand',lambda *a:prepared)
    class Planner:
        def generate_text(self,system,prompt):
            if '计划生成器' in system:
                return json.dumps({'steps':[{'id':1,'title':'收入','question':'收入多少','depends_on':[]},
                                            {'id':2,'title':'费用','question':'费用多少','depends_on':[1]}]})
            return '汇总结果'
        generate_json=generate_text
    monkeypatch.setattr(agent,'llm',lambda:Planner())
    calls=[]
    def single(question,user,emit,context,**kwargs):
        calls.append((context,kwargs['understanding']))
        return {'success':True,'question':question,'sql':'SELECT 1','rows':[{'value':1}],'columns':['value']}
    monkeypatch.setattr(agent,'single_query',single)
    result=agent.run('分析收入与费用','auto',ADMIN)
    assert result['mode']=='analysis' and len(calls)==2
    assert calls[0]==([],None) and calls[1][0][0]['step_id']==1
