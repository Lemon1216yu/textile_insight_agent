"""A4 问数模式结果解释：把「口径 / 公式 / 单位 / 时间字段 / 来源表」解释给用户。

设计取舍（为什么确定性拼装，而不是让模型写一段解释）：
1. 口径是治理资产：定义、公式、单位、时间字段都已落在指标知识库（metric_registry）里，
   让模型复述一遍只会引入编造风险，且每次措辞都不一样，无法被断言。
2. 本项目要求结论可复现：拼装结果可以被测试直接断言（含单位、含指标编码、不含无关指标）。
3. 不增加模型调用：解释随问数结果一起返回，零额外额度消耗。

三条"不得错误归属/不得泄漏内部细节"的硬约束（均由评审与真实验证发现后固化）：
- **口径**只认理解步骤识别出的指标编码 `understanding.metric_codes`（再补齐其依赖指标）。
  检索层的 `linked['metrics']` 是"给模型的候选"，含语义相近的无关指标（例如问调拨米数时召回
  库存周转次数），把它当作结果口径就是错误归属。
- **来源表**从真实执行的 SQL 解析（sqlglot）；解析失败才回落到检索候选，且必须在 notes 里
  标明"来源为候选、未验证"，不能与从 SQL 解析出的来源混为一谈。
- **对外文本不得出现内部占位符/空槽**：跨表指标的 table 是 `__operating_profit__` 这类
  内部占位符（不是真实表名），对外归 None；time_field 为空时整句省略，不产生「时间字段：。」。

解释只做"复述元数据 + 计数 + 解析表名"，不参与任何数值计算；数值一律以 rows 为准。
"""
import sqlglot

NO_METRIC_NOTE = '本次问题未命中指标知识库，口径按业务表字段直接聚合。'
SOURCE_NOTE = '解释由指标知识库元数据拼装，不调用模型；数值以查询返回的 rows 为准。'
CANDIDATE_SOURCE_NOTE = '来源业务表为检索候选（SQL 解析失败），未经执行验证。'
UNREGISTERED = '未登记'


def _field(obj, key, default=None):
    """同时兼容 pydantic 模型与 dict（single_query 两种调用路径都会出现）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _public_table(table):
    """跨表指标在主数据里用 `__xxx__` 占位符代替单一事实表，对外不得暴露该内部值。"""
    return None if (not table or str(table).startswith('__')) else table


def _metric_codes(understanding, registry):
    """主指标 + 其依赖指标（依赖关系来自指标知识库，递归补齐；成环时靠 codes 去重终止）。"""
    primary = []
    for code in (_field(understanding, 'metric_codes') or []):
        if code in registry and code not in primary:
            primary.append(code)
    codes = list(primary)
    pending = list(primary)
    while pending:
        for dep in (registry.get(pending.pop(), {}).get('dependencies') or []):
            if dep in registry and dep not in codes:
                codes.append(dep)
                pending.append(dep)
    return primary, codes


def _tables_from_sql(sql):
    """从真实执行的 SQL 解析来源表；解析失败返回空列表（不猜）。"""
    if not sql:
        return []
    try:
        tree = sqlglot.parse_one(sql, read='mysql')
        if tree is None:
            return []
    except Exception:
        return []
    ctes = {cte.alias_or_name for cte in tree.find_all(sqlglot.exp.CTE)}
    names = []
    for table in tree.find_all(sqlglot.exp.Table):
        name = table.name
        if name and name not in ctes and name not in names:
            names.append(name)
    return names


def _metric_view(metric, role):
    """对外结构：主数据缺字段时降级为"未登记"，不让解释层抛异常影响查询结果。"""
    return {'code': metric.get('code'), 'name': metric.get('name'),
            'unit': metric.get('unit') or UNREGISTERED,
            'definition': metric.get('definition') or UNREGISTERED,
            'formula': metric.get('formula') or UNREGISTERED,
            'time_field': metric.get('time_field') or '',
            'table': _public_table(metric.get('table')),
            'role': role,
            'caveats': list(metric.get('caveats') or [])}


def explain(question, understanding, linked, rows, registry, sql=None):
    """返回结构化解释。

    keys:
      summary       : 一句话口径说明（含单位；有时间字段时才写时间字段）
      metrics       : 命中指标的治理元数据（role 区分 primary/dependency）；跨表指标的 table 为 None
      source_tables : 从执行 SQL 解析出的业务表（解析失败时回落检索候选，并在 notes 说明）
      row_count     : 返回行数（只计数，不做数值判断）
      notes         : 备注（解释生成方式 + 来源可信度 + 指标自身的限制 caveats）
    """
    registry = registry or {}
    primary_codes, all_codes = _metric_codes(understanding, registry)
    metrics = [_metric_view(registry[c], 'primary' if c in primary_codes else 'dependency')
               for c in all_codes]
    parsed_tables = _tables_from_sql(sql)
    if parsed_tables:
        tables = parsed_tables
    else:
        tables = [t.get('table_name') for t in (_field(linked, 'tables') or [])
                  if isinstance(t, dict) and t.get('table_name')]
    rows = rows or []
    primary = [m for m in metrics if m['role'] == 'primary']

    if len(primary) == 1:
        m = primary[0]
        summary = (f"口径：{m['name']}（{m['code']}）。定义：{m['definition']}；"
                   f"计算：{m['formula']}；单位：{m['unit']}；")
        if m['time_field']:
            summary += f"时间字段：{m['time_field']}。"
    elif primary:
        detail = '；'.join(f"{m['name']}（{m['code']}，单位 {m['unit']}）" for m in primary)
        summary = f"口径：本次结果涉及 {len(primary)} 个指标：{detail}。各指标定义与公式见 metrics 字段。"
    else:
        summary = NO_METRIC_NOTE
    dependencies = [m for m in metrics if m['role'] == 'dependency']
    if dependencies:
        summary += (' 依赖指标：'
                    + '、'.join(f"{m['name']}（{m['code']}）" for m in dependencies) + '。')
    if tables:
        summary += f" 来源业务表：{'、'.join(tables)}。"
    summary += f" 返回 {len(rows)} 行。"

    notes = [SOURCE_NOTE]
    if tables and not parsed_tables:
        notes.append(CANDIDATE_SOURCE_NOTE)
    for m in metrics:
        for caveat in (m.get('caveats') or []):
            notes.append(f"{m['name']}：{caveat}")

    return {
        'summary': summary,
        'metrics': metrics,
        'source_tables': tables,
        'source_tables_from_sql': bool(parsed_tables),
        'row_count': len(rows),
        'notes': notes,
    }
