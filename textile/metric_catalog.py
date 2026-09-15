"""纺织制造企业管理指标知识库（模拟配置）。

本指标库按纺织制造行业通用管理实践编写，覆盖销售、财务、生产、采购、库存五个业务域。
每条指标包含编码、名称、定义、公式、时间口径、单位、可分析维度、负责部门、版本、适用范围、
管理目标与使用限制。所有指标公式可被 compile_sql 确定性编译为只读 SELECT。

重要声明：本指标口径、管理目标与角色可见范围均为本项目设计的模拟配置，
用于演示企业指标治理与权限控制，不代表东莞德永佳纺织制衣有限公司或其他任何企业的真实内部制度。
数据仅覆盖 2026-03-01 至 2026-08-31 的模拟业务样本。
"""
COMMON_ROLES = ['admin', 'executive', 'finance']
SALES_ROLES = COMMON_ROLES + ['sales']
WAREHOUSE_ROLES = COMMON_ROLES + ['sales', 'warehouse']
PRODUCTION_ROLES = COMMON_ROLES + ['production']

DEFAULT_SCOPE = '全公司口径；销售、仓储等角色按授权区域或字段过滤。数据覆盖 2026-03-01 至 2026-08-31 模拟样本。'
SIMULATED_NOTE = '本指标为模拟配置，不代表真实企业内部制度。'


def metric(code, name, domain, unit, definition, formula, table, expression, time_field, *,
           filters='1=1', roles=None, dimensions=None, owner=None, caveats=None,
           target=None, kind='flow', dependencies=None, scope=None):
    return dict(code=code, name=name, domain=domain, unit=unit, definition=definition,
                formula=formula, table=table, expression=expression, time_field=time_field,
                filters=filters, roles=roles or COMMON_ROLES, dimensions=dimensions or [],
                owner=owner or domain + '部', caveats=caveats or [], target=target,
                aggregation=kind, dependencies=dependencies or [],
                version='1.0', effective_from='2026-03-01', status='published',
                scope=scope or DEFAULT_SCOPE,
                currency='CNY' if unit in ['元', '元/米', '元/千克', '元/客户'] else None,
                null_policy='分母为 0 或没有样本时返回 NULL，界面显示暂无数据；不得当作 0% 或达标。')


# 销售域统一确认口径：已完成且实际交付，按交付日期归属月份。
REVENUE_FILTER = "order_status='已完成' AND delivery_date IS NOT NULL"

METRIC_DEFINITIONS = [
    # ============ 销售域 ============
    metric('SAL-001', '确认销售收入', '销售', '元',
           '报告期内已完成并实际交付订单的不含税销售收入，按实际交付日期归属月份确认。',
           'Σ已完成且已交付订单的不含税金额', 'sales_orders', 'SUM(net_amount)', 'delivery_date',
           filters=REVENUE_FILTER, roles=SALES_ROLES,
           dimensions=['销售区域', '客户', '面料品类', '面料产品'], owner='财务部',
           caveats=['按交付月而非下单月统计；不含生产中及已取消订单。',
                    '本阶段为管理口径，未纳入退货红字与收入调整凭证，不能代替财务报表营业收入。',
                    SIMULATED_NOTE]),
    metric('SAL-002', '已交付销售量', '销售', '米',
           '报告期内已完成并实际交付的面料数量。',
           'Σ已交付面料米数', 'sales_orders', 'SUM(quantity)', 'delivery_date',
           filters=REVENUE_FILTER, roles=SALES_ROLES,
           dimensions=['销售区域', '客户', '面料产品']),
    metric('SAL-003', '已交付订单数', '销售', '笔',
           '报告期内已完成且实际交付的订单笔数。',
           'COUNT(已完成且已交付订单)', 'sales_orders', 'COUNT(order_id)', 'delivery_date',
           filters=REVENUE_FILTER, roles=SALES_ROLES, dimensions=['销售区域', '客户']),
    metric('SAL-004', '平均销售单价', '销售', '元/米',
           '确认销售收入除以对应已交付销售米数，按销量加权。',
           '确认销售收入 ÷ 已交付销售量', 'sales_orders',
           'SUM(net_amount)/NULLIF(SUM(quantity),0)', 'delivery_date',
           filters=REVENUE_FILTER, roles=SALES_ROLES, dimensions=['面料产品', '客户'],
           dependencies=['SAL-001', 'SAL-002'],
           caveats=['不同面料混合后的均价受产品结构影响，不可直接判断调价效果。']),
    metric('SAL-005', '订单准时交付率', '销售', '%',
           '报告期实际交付的完成订单中，交付日不晚于承诺日的比例。',
           '准时交付订单数 ÷ 本期已交付订单数 × 100%', 'sales_orders',
           'SUM(CASE WHEN delivery_date<=promised_date THEN 1 ELSE 0 END)/NULLIF(COUNT(order_id),0)*100',
           'delivery_date', filters=REVENUE_FILTER, roles=SALES_ROLES,
           dimensions=['客户', '销售区域'], target={'operator': '>=', 'value': 95},
           caveats=['按已交付样本计算；尚未交付的逾期订单不在分母中，需另看逾期未交付订单数。']),
    metric('SAL-006', '逾期未交付订单数', '销售', '笔',
           '截至报告期末，承诺交期已过但仍未交付的有效订单笔数。',
           'COUNT(承诺日期≤截止日 且截止日尚未交付的有效订单)', 'sales_orders',
           'COUNT(order_id)', 'order_date',
           filters="order_status<>'已取消' AND promised_date < '{end}' AND (delivery_date IS NULL OR delivery_date >= '{end}')",
           roles=SALES_ROLES, dimensions=['客户', '销售区域'], kind='asof',
           target={'operator': '<=', 'value': 0},
           caveats=['按期末状态重建；样本只有当前订单状态，历史取消时点未建模。']),
    metric('SAL-007', '逾期未交付订单金额', '销售', '元',
           '截至报告期末，承诺交期已过但仍未交付的有效订单不含税金额。',
           'Σ(承诺日期≤截止日 且尚未交付的有效订单金额)', 'sales_orders',
           'SUM(net_amount)', 'order_date',
           filters="order_status<>'已取消' AND promised_date < '{end}' AND (delivery_date IS NULL OR delivery_date >= '{end}')",
           roles=SALES_ROLES, dimensions=['客户', '销售区域'], kind='asof',
           caveats=['与逾期未交付订单数同口径；金额为订单不含税净额，不代表逾期违约金。']),
    metric('SAL-008', '订单取消率', '销售', '%',
           '报告期内下单的有效订单中，最终被取消的订单占比。',
           '取消订单数 ÷ 全部有效订单数 × 100%', 'sales_orders',
           'SUM(CASE WHEN order_status=\'已取消\' THEN 1 ELSE 0 END)/NULLIF(COUNT(order_id),0)*100',
           'order_date', roles=SALES_ROLES, dimensions=['客户', '销售区域'],
           target={'operator': '<=', 'value': 10},
           caveats=['按下单月统计；生产中和已完成订单均视为未取消。']),
    metric('SAL-009', '活跃客户客单价', '销售', '元/客户',
           '报告期确认销售收入除以当期有实际交付的客户数。',
           '确认销售收入 ÷ 已交付客户数', 'sales_orders',
           'SUM(net_amount)/NULLIF(COUNT(DISTINCT customer_id),0)', 'delivery_date',
           filters=REVENUE_FILTER, roles=SALES_ROLES, dimensions=['销售区域'],
           dependencies=['SAL-001'],
           caveats=['分母为有交付的客户数，不是客户档案全量；反映实际交易客单水平。']),

    # ============ 财务域 ============
    metric('FIN-001', '实际销售成本', '财务', '元',
           '与已交付销售收入对应的订单实际销售成本。',
           'Σ已交付订单的实际销售成本', 'sales_orders', 'SUM(cost_amount)', 'delivery_date',
           filters=REVENUE_FILTER, roles=COMMON_ROLES, dimensions=['销售区域', '客户', '面料产品'],
           caveats=['使用订单实际成本，不使用产品标准成本代替。']),
    metric('FIN-002', '销售毛利', '财务', '元',
           '同批已交付订单的确认销售收入减实际销售成本。',
           '确认销售收入 − 实际销售成本', 'sales_orders',
           'SUM(net_amount-cost_amount)', 'delivery_date', filters=REVENUE_FILTER,
           roles=COMMON_ROLES, dimensions=['销售区域', '客户', '面料品类', '面料产品'],
           dependencies=['SAL-001', 'FIN-001']),
    metric('FIN-003', '销售毛利率', '财务', '%',
           '汇总销售毛利除以汇总确认销售收入。',
           'Σ(收入−销售成本) ÷ Σ收入 × 100%', 'sales_orders',
           'SUM(net_amount-cost_amount)/NULLIF(SUM(net_amount),0)*100', 'delivery_date',
           filters=REVENUE_FILTER, roles=COMMON_ROLES, dimensions=['销售区域', '客户', '面料产品'],
           dependencies=['FIN-002', 'SAL-001'], target={'operator': '>=', 'value': 28},
           caveats=['不能对订单毛利率做简单平均；收入为 0 时无有效毛利率。']),
    metric('FIN-004', '期间费用', '财务', '元',
           '报告期费用凭证对应的销售、管理和财务费用总额。',
           'Σ销售费用 + Σ管理费用 + Σ财务费用', 'finance_expenses', 'SUM(amount)', 'expense_date',
           roles=COMMON_ROLES, dimensions=['销售区域', '费用类别'],
           caveats=['按费用发生日归属；本阶段不含所得税和营业外损益。']),
    metric('FIN-005', '经营利润（管理口径）', '财务', '元',
           '同一期间、同一授权区域内的销售毛利减期间费用。',
           '销售毛利 − 期间费用', '__operating_profit__', '', '',
           roles=COMMON_ROLES, dimensions=['销售区域'], dependencies=['FIN-002', 'FIN-004'],
           caveats=['订单和费用必须各自汇总后相减，不可逐行 JOIN。',
                    '为简化管理口径，不等同于法定营业利润或净利润。']),
    metric('FIN-006', '期间费用率', '财务', '%',
           '同一期间和区域的期间费用占确认销售收入比例。',
           '期间费用 ÷ 确认销售收入 × 100%', '__expense_ratio__', '', '',
           roles=COMMON_ROLES, dimensions=['销售区域'], dependencies=['FIN-004', 'SAL-001'],
           caveats=['分子与分母来自不同事实表，必须各自独立聚合后再相除，禁止 JOIN 明细行。',
                    '分母为 0 或没有样本时返回 NULL，不得当作 0%。'],
           target={'operator': '<=', 'value': 8}),
    metric('FIN-007', '单位销售成本', '财务', '元/米',
           '已交付订单的实际销售成本除以已交付销售米数。',
           'Σ实际销售成本 ÷ Σ已交付米数', 'sales_orders',
           'SUM(cost_amount)/NULLIF(SUM(quantity),0)', 'delivery_date',
           filters=REVENUE_FILTER, roles=COMMON_ROLES, dimensions=['面料产品'],
           caveats=['与产品标准成本对比可识别订单成本异常；受产品结构影响。']),

    # ============ 生产域 ============
    metric('PRD-001', '实际产量', '生产', '米',
           '按生产日期汇总的实际完工米数，包含不良品。',
           'Σ实际产出米数', 'production_batches', 'SUM(actual_meters)', 'production_date',
           roles=PRODUCTION_ROLES, dimensions=['车间', '面料产品']),
    metric('PRD-002', '生产良品率', '生产', '%',
           '良品米数占实际产量的比例，按产量加权。',
           '(Σ实际产量 − Σ不良米数) ÷ Σ实际产量 × 100%', 'production_batches',
           '(SUM(actual_meters)-SUM(defect_meters))/NULLIF(SUM(actual_meters),0)*100',
           'production_date', roles=PRODUCTION_ROLES, dimensions=['车间', '面料产品'],
           dependencies=['PRD-001'], target={'operator': '>=', 'value': 97},
           caveats=['包含全部批次首次完工数据，未区分返工后良品率。']),
    metric('PRD-003', '生产计划达成率', '生产', '%',
           '报告期实际产量与计划产量之比，允许超过 100%。',
           'Σ实际产出米数 ÷ Σ计划米数 × 100%', 'production_batches',
           'SUM(actual_meters)/NULLIF(SUM(planned_meters),0)*100', 'production_date',
           roles=PRODUCTION_ROLES, dimensions=['车间', '面料产品'],
           target={'operator': '>=', 'value': 95}),
    metric('PRD-004', '单位生产成本', '生产', '元/米',
           '材料、人工、能源成本合计除以实际产量。',
           'Σ(材料成本+人工成本+能源成本) ÷ Σ实际产量', 'production_batches',
           'SUM(material_cost+labor_cost+energy_cost)/NULLIF(SUM(actual_meters),0)',
           'production_date', roles=PRODUCTION_ROLES, dimensions=['车间', '面料产品'],
           caveats=['不包含制造费用分摊与在制品成本；用于车间成本观察，不替代财务产品成本核算。']),
    metric('PRD-005', '材料成本占比', '生产', '%',
           '材料成本占已采集生产成本的比例。',
           'Σ材料成本 ÷ Σ(材料+人工+能源成本) × 100%', 'production_batches',
           'SUM(material_cost)/NULLIF(SUM(material_cost+labor_cost+energy_cost),0)*100',
           'production_date', roles=PRODUCTION_ROLES, dimensions=['车间', '面料产品'],
           caveats=['材料价格波动会直接改变占比，需结合采购均价观察。']),
    metric('PRD-006', '生产批次数量', '生产', '笔',
           '报告期内开工的生产批次总数。',
           'COUNT(生产批次)', 'production_batches', 'COUNT(batch_id)', 'production_date',
           roles=PRODUCTION_ROLES, dimensions=['车间'],
           caveats=['含全部状态批次；与产量指标配合看批次规模。']),

    # ============ 采购域 ============
    metric('PUR-001', '采购金额', '采购', '元',
           '按采购日期统计的原材料不含税采购金额。',
           'Σ采购订单不含税金额', 'purchase_orders', 'SUM(amount)', 'purchase_date',
           roles=COMMON_ROLES, dimensions=['供应商', '原料名称', '销售区域'],
           caveats=['采购额不直接作为当期销售成本。']),
    metric('PUR-002', '供应商准时到货率', '采购', '%',
           '本期实际到货采购订单中，不晚于承诺日到货的比例。',
           '准时到货笔数 ÷ 本期已到货笔数 × 100%', 'purchase_orders',
           'SUM(CASE WHEN received_date<=promised_date THEN 1 ELSE 0 END)/NULLIF(COUNT(purchase_id),0)*100',
           'received_date', filters='received_date IS NOT NULL', roles=COMMON_ROLES,
           dimensions=['供应商', '原料名称'], target={'operator': '>=', 'value': 95}),
    metric('PUR-003', '原料采购均价', '采购', '元/千克',
           '采购总额除以采购重量，按重量加权。',
           'Σ采购金额 ÷ Σ采购千克数', 'purchase_orders',
           'SUM(amount)/NULLIF(SUM(quantity_kg),0)', 'purchase_date',
           roles=COMMON_ROLES, dimensions=['原料名称', '供应商'],
           caveats=['跨原料类型的均价仅用于结构观察，需按原料名称比较。']),
    metric('PUR-004', '采购订单笔数', '采购', '笔',
           '报告期内下达的原材料采购订单笔数。',
           'COUNT(采购订单)', 'purchase_orders', 'COUNT(purchase_id)', 'purchase_date',
           roles=COMMON_ROLES, dimensions=['供应商', '原料名称']),
    metric('PUR-005', '平均采购到货周期', '采购', '天',
           '已到货采购订单从下单到实际到货的平均天数。',
           'Σ(实际到货日 − 下单日) ÷ 已到货笔数', 'purchase_orders',
           'AVG(TIMESTAMPDIFF(DAY,purchase_date,received_date))', 'received_date',
           filters='received_date IS NOT NULL', roles=COMMON_ROLES, dimensions=['供应商', '原料名称'],
           caveats=['仅统计已到货订单；未到货订单不计入平均。']),

    # ============ 库存域 ============
    metric('INV-001', '期末库存数量', '库存', '米',
           '报告期末及以前最近一个快照日的成品库存米数。',
           'Σ期末有效库存快照的数量', 'inventory_snapshots', 'SUM(quantity)', 'snapshot_date',
           roles=WAREHOUSE_ROLES, dimensions=['仓库', '销售区域', '面料产品'], kind='snapshot',
           caveats=['同一时点库存可按仓库汇总；不同月份的库存不可直接相加。']),
    metric('INV-002', '期末库存金额', '库存', '元',
           '期末有效库存快照的库存成本金额。',
           'Σ期末有效快照的库存成本金额', 'inventory_snapshots', 'SUM(inventory_value)', 'snapshot_date',
           roles=COMMON_ROLES + ['warehouse'], dimensions=['仓库', '销售区域', '面料产品'], kind='snapshot',
           caveats=['以库存成本估值，不是预计售价；不包含跌价准备。']),
    metric('INV-003', '90天以上库龄占比', '库存', '%',
           '期末 90 天以上库龄米数占期末库存米数的比例。',
           'Σ90天以上库存米数 ÷ Σ期末库存米数 × 100%', 'inventory_snapshots',
           'SUM(aged_90_meters)/NULLIF(SUM(quantity),0)*100', 'snapshot_date',
           roles=WAREHOUSE_ROLES, dimensions=['仓库', '面料产品'], kind='snapshot',
           target={'operator': '<=', 'value': 15},
           caveats=['长库龄不必然等于呆滞或应报废，需结合订单需求、品质与季节性判断。']),
    metric('INV-004', '长库龄库存数量', '库存', '米',
           '期末快照中库龄超过 90 天的库存米数。',
           'Σ90天以上库存米数', 'inventory_snapshots', 'SUM(aged_90_meters)', 'snapshot_date',
           roles=WAREHOUSE_ROLES, dimensions=['仓库', '面料产品'], kind='snapshot'),
    metric('INV-005', '库存周转次数', '库存', '次',
           '报告期已交付销量与期末库存之比（简化口径）。',
           '报告期已交付销量 ÷ 期末库存数量', '__inventory_turnover__', '', '',
           roles=COMMON_ROLES + ['warehouse'], dimensions=['面料产品'],
           dependencies=['SAL-002', 'INV-001'],
           caveats=['简化口径：未使用期初期末平均库存，也未折算销售成本；用于观察周转快慢的相对变化。']),
]

METRICS_INDEX = [(m['code'], m['name'], m['formula']) for m in METRIC_DEFINITIONS]


def definition_text(m):
    text=(f"{m['code']} {m['name']}；域：{m['domain']}；定义：{m['definition']}；公式：{m['formula']}；"
          f"单位：{m['unit']}；时间字段：{m['time_field']}；过滤：{m['filters']}；聚合：{m['aggregation']}；")
    if str(m['table']).startswith('__'):
        # Cross-table metrics have no single-table expression; the empty
        # placeholder used to reach the model as a blank "authoritative
        # expression", which made it invent its own (and wrong) join shape.
        deps='、'.join(m.get('dependencies') or []) or '多个基础指标'
        text+=(f"权威计算方式：本指标不是单表聚合，须先把依赖指标（{deps}）各自独立聚合，"
               f"再用标量子查询按「{m['formula']}」组合；"
               f"严禁把不同粒度的事实表 JOIN 明细行，否则会因笛卡尔积放大分子或分母；")
    else:
        text+=f"权威计算表达式（不得自行改变分子分母）：{m['expression']}；"
    text+=(f"维度：{'、'.join(m['dimensions']) or '无'}；负责人：{m['owner']}；"
           f"注意事项：{'；'.join(m['caveats']) or '无'}；适用范围：{m['scope']}；版本：{m['version']}")
    return text


def compile_sql(m, start, end, definitions=None):
    """Dates validated by the API; formulas come from curated catalog, never user SQL."""
    if m['table'].startswith('__'):
        if definitions is None:
            from textile.registry import get_metrics
            definitions = get_metrics()
        by_code = {x['code']: x for x in definitions}
        revenue = compile_sql(by_code['SAL-001'], start, end, definitions)
        gross = compile_sql(by_code['FIN-002'], start, end, definitions)
        expenses = compile_sql(by_code['FIN-004'], start, end, definitions)
        if m['table'] == '__operating_profit__':
            return f'SELECT ({gross})-({expenses}) AS value'
        if m['table'] == '__expense_ratio__':
            return f'SELECT ({expenses})/NULLIF(({revenue}),0)*100 AS value'
        if m['table'] == '__inventory_turnover__':
            sales_qty = ("SELECT SUM(quantity) FROM sales_orders "
                         f"WHERE order_status='已完成' AND delivery_date IS NOT NULL AND delivery_date>='{start}' AND delivery_date<'{end}'")
            stock = ("SELECT SUM(quantity) FROM inventory_snapshots "
                     f"WHERE snapshot_date=(SELECT MAX(snapshot_date) FROM inventory_snapshots WHERE snapshot_date<'{end}')")
            return f'SELECT ({sales_qty})/NULLIF(({stock}),0) AS value'
    table = m['table']
    field = m['time_field']
    filters = m['filters'].format(end=end)
    if m['aggregation'] == 'snapshot':
        condition = f"{field}=(SELECT MAX({field}) FROM {table} WHERE {field}<'{end}')"
    elif m['aggregation'] == 'asof':
        condition = f"{field}<'{end}'"
    else:
        condition = f"{field}>='{start}' AND {field}<'{end}'"
    return f"SELECT {m['expression']} AS value FROM {table} WHERE ({filters}) AND {condition}"


# 兼容接口：供检索与 Agent 使用的 (名称, 完整定义文本) 列表。
METRICS = [(m['name'], definition_text(m)) for m in METRIC_DEFINITIONS]
