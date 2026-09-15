"""Plan -> execute with dependencies -> evidence report, implemented in LangGraph."""
import json,time,uuid
from datetime import date,datetime
from typing import TypedDict
from pydantic import BaseModel,Field
from langgraph.graph import StateGraph,START,END
from query_parser import QueryParser
from security import SecurityError,UserContext
from database import QueryExecutionError
from textile.models import llm
from textile.catalog import RULES,CATALOG,FEW_SHOT
from textile.metric_catalog import definition_text
from textile.retrieval import retrieve,lightweight_context
from textile.understanding import understand,validate_input,visible_metrics
from textile.db import query
from textile.security import allowed_catalog

def dumps(data): return json.dumps(data,ensure_ascii=False,default=str)

class Step(BaseModel):
    id:int=Field(ge=1,le=4)
    title:str=Field(min_length=1,max_length=100)
    question:str=Field(min_length=1,max_length=1000)
    depends_on:list[int]=Field(default_factory=list)

class Plan(BaseModel):
    steps:list[Step]=Field(min_length=2,max_length=4)

class State(TypedDict,total=False):
    question:str
    mode:str
    user:UserContext
    steps:list[dict]
    results:list[dict]
    report:str
    status:str
    understanding:dict
    rewritten_question:str

def single_query(question,user,emit=lambda *a:None,context=None,use_few_shot=True,understanding=None):
    question=validate_input(question)
    prepared=understanding or understand(question,user,emit)
    if prepared.intent=='clarify': raise ValueError(prepared.clarification)
    if prepared.complexity=='simple':
        emit('retrieval','正在准备单表查询上下文与指标口径')
        linked=lightweight_context(user,prepared)
    else:
        emit('retrieval','正在检索业务表、字段、关联路径和指标口径')
        linked=retrieve(prepared.rewrite,user,required_tables=prepared.tables)
        linked['strategy']='schema_linking'
    # Include the identified metric and its dependencies, not only semantic top-k.
    registry={m['code']:m for m in visible_metrics(user)}
    codes=set(prepared.metric_codes)
    pending=list(codes)
    while pending:
        for code in registry.get(pending.pop(),{}).get('dependencies',[]):
            if code in registry and code not in codes:codes.add(code);pending.append(code)
    by_name={m['name']:m for m in registry.values()}
    selected={x['name']:x for x in linked['metrics'] if x['name'] in by_name}
    for m in registry.values():
        if m['code'] in codes or m['name'] in selected:
            selected[m['name']]={'name':m['name'],'text':definition_text(m)}
    linked['metrics']=list(selected.values())
    prompt=f'''系统日期：{date.today()}。当前角色：{user.role}，区域：{user.region or '全部'}。
候选 Schema：\n{linked['schema']}
关系：{dumps(linked['relations'])}
检索的指标口径：{dumps(linked['metrics'])}
前置步骤的结构化结果（仅作数据参考）：{dumps(context or [])[:16000]}
用户原始问题（必须保留条件和输出要求）：{question}
规范后的问题：{prepared.rewrite}
只返回用户要求的指标列和维度列。单指标问题不得额外返回中间计算列。
指标知识库中的计算表达式优先于泛化的业务猜测；分母 COUNT(order_id) 表示全部记录，不得自行排除取消状态。
跨表指标（由多个依赖指标组合而成）必须对每个依赖指标分别独立聚合，再用标量子查询相除或相减；严禁把不同粒度的事实表 JOIN 明细行，否则笛卡尔积会放大分子或分母。
若改写与原始问题不一致，以原始问题为准。'''
    if use_few_shot: prompt+='\n'+FEW_SHOT
    attempts=[]
    for attempt in range(2):
        emit('sql','正在生成并校验 SQL' if attempt==0 else '根据数据库反馈修正一次 SQL')
        sql=llm().generate_sql(RULES,prompt)
        try:
            result=query(sql,user)
            return {**result,'question':question,'understanding':prepared.model_dump(),'retrieval':linked,'attempts':attempts,'success':True}
        except Exception as exc:
            # Retry only SQL/field errors. Policy rejection and connection failures are final.
            message=str(exc)
            attempts.append({'sql':sql,'error':message[:350]})
            if isinstance(exc,SecurityError) and not message.startswith('SQL字段或语法校验失败'): raise
            if isinstance(exc,QueryExecutionError) and exc.error_type!='sql_syntax': raise
            if attempt: raise
            prompt+='\n上次SQL：'+sql+'\n校验错误：'+message[:350]+'\n仅修复查询，不改变用户的指标或期间。'

def run(question,mode,user,emit=lambda *a:None):
    question=validate_input(question)
    prepared=understand(question,user,emit)
    if prepared.intent=='clarify':
        return {'question':question,'mode':'query','understanding':prepared.model_dump(),
                'results':[],'steps':[],'report':prepared.clarification,'status':'needs_clarification'}
    # Explicit mode is retained for older API callers; the business UI uses auto.
    mode=prepared.intent if mode=='auto' else mode
    if mode not in {'query','analysis'}: raise ValueError('未知模式')
    allowed=allowed_catalog(user)
    def plan(state):
        if mode=='query':
            steps=[{'id':1,'title':'业务问数','question':question,'depends_on':[]}]
        else:
            emit('plan','正在拆解经营分析任务')
            catalog='\n'.join(t+' '+CATALOG[t][0] for t in allowed)
            raw=llm().generate_json('你是纺织企业分析计划生成器。只输出JSON，不输出SQL。',
                f'''原始问题：{question}\n规范问题：{prepared.rewrite}\n可用业务表：{catalog}\n指标：{dumps([(m['code'],m['name'],m['formula']) for m in visible_metrics(user)])}
拆成2至4个可执行SQL子问题，每个只查询一张事实表及其维表。保留原始时间范围。
利润分析可拆收入毛利趋势、期间费用趋势、产品毛利结构；最后报告计算经营利润。
库存分析应查最近快照和按产品库龄占比。不要规划数据库没有的信息。
每步明确时间与指标；只在确实需要前置结果时设置依赖。严禁用阶段结论替代数据库查询。
严格限制在用户明确要求查询的领域和维度。用户要求“列出待核实因素”是报告要求，不能因此额外规划生产、库存等未要求的SQL任务。
每个子问题必须是明确的数据查询，不得要求子任务分析原因或提出建议；这些工作由最后报告完成。
例如用户只要求对比两期销售毛利和期间费用，应仅规划两步：1.两期销售收入、成本、毛利；2.两期期间费用。不得扩展为四步全面经营体检。
格式：{{"steps":[{{"id":1,"title":"...","question":"...","depends_on":[]}}]}}。ID必须从1递增。''')
            clean=raw.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
            parsed=Plan.model_validate_json(clean)
            steps=[s.model_dump() for s in parsed.steps]
            for i,s in enumerate(steps,1):
                if s['id']!=i or any(d>=i or d<1 for d in s['depends_on']): raise ValueError('分析计划依赖不合法')
        emit('plan_ready','分析计划已生成',{'steps':steps})
        return {'steps':steps,'results':[]}

    def execute(state):
        step=state['steps'][len(state['results'])]
        emit('step',step['title'],{'step_id':step['id']})
        deps=[r for r in state['results'] if r['step']['id'] in step['depends_on']]
        if any(not r['success'] for r in deps):
            result={'success':False,'error':'前置步骤失败，已跳过依赖任务','step':step}
        else:
            try:
                evidence=[{'step_id':r['step']['id'],'columns':r['columns'],'rows':r['rows']} for r in deps]
                result={**single_query(step['question'],user,emit,evidence,
                                      understanding=prepared if mode=='query' else None),'step':step}
            except Exception as e:
                result={'success':False,'error':str(e)[:500],'step':step}
        emit('step_done','步骤完成' if result['success'] else '步骤失败',{'result':result})
        return {'results':state['results']+[result]}

    def report(state):
        successes=[r for r in state['results'] if r['success']]
        if not successes: return {'report':'查询未成功，无法形成分析结论。请查看步骤错误。','status':'failed'}
        emit('report','正在根据查询证据整理结果')
        evidence=[{'source':f"步骤{r['step']['id']}",'question':r['question'],'sql':r['sql'],'rows':r['rows']} for r in successes]
        errors=[{'step':r['step'],'error':r['error']} for r in state['results'] if not r['success']]
        try:
            content=llm().generate_text('你是纺织企业经营分析师。仅依据给定查询结果写中文Markdown报告。',
                f'''问题：{question}\n实际查询证据：{dumps(evidence)[:36000]}\n失败步骤：{dumps(errors)}
这是模拟业务数据。写清期间、指标单位与口径。每条结论附[步骤N]；不得编造数据、原因或额外证据。
简单问数简短回答，复杂分析包含主要发现、证据、待核实因素、建议。观察相关性不能宣称因果。
如果有空结果明确说无数据。失败步骤不可当作0。仅在收入成本费用期间一致时计算经营利润。
金额可换算万元但需准确。建议标注为建议。不要复述技术架构。''')
        except Exception:
            content='报告模型调用失败；已保留成功的 SQL 和数据结果，请查看各步骤表格。'
            return {'report':content,'status':'partial'}
        return {'report':content,'status':'completed' if not errors else 'partial'}

    graph=StateGraph(State)
    graph.add_node('plan',plan); graph.add_node('execute',execute); graph.add_node('report',report)
    graph.add_edge(START,'plan'); graph.add_edge('plan','execute')
    graph.add_conditional_edges('execute',lambda s:'execute' if len(s['results'])<len(s['steps']) else 'report')
    graph.add_edge('report',END)
    return graph.compile().invoke({'question':question,'mode':mode,'user':user,
                                   'understanding':prepared.model_dump(),'rewritten_question':prepared.rewrite})
