"""A4 结果解释的断言：口径/单位/来源必须来自指标元数据与真实 SQL，且不得错误归属或泄漏内部值。

全部为确定性测试：不连数据库、不调模型。

负向对照来自两轮独立评审发现的真实缺陷：
- 检索层候选指标（linked['metrics']）含语义相近的无关指标，不得被写成"结果口径"；
- 来源表必须来自执行的 SQL，不能照抄检索候选表；回落候选时必须在 notes 里标明；
- 跨表指标的 `table` 是 `__expense_ratio__` 这类内部占位符，对外必须归 None；
- `time_field` 为空时不得产生「时间字段：。」这种残句。
"""
import pytest

from textile import explain as e

METRIC_SAL = {'code': 'SAL-001', 'name': '营业收入', 'unit': '元', 'domain': '销售',
              'definition': '已完成且已交付订单的净额合计', 'formula': 'Σ net_amount',
              'time_field': 'delivery_date', 'table': 'sales_orders', 'caveats': []}
# 跨表指标：生产库里的真实占位符是 __expense_ratio__，且 time_field 为空
METRIC_FIN = {'code': 'FIN-006', 'name': '期间费用率', 'unit': '%', 'domain': '财务',
              'definition': '期间费用占营业收入的比例', 'formula': '期间费用 ÷ 营业收入 × 100%',
              'time_field': '', 'table': '__expense_ratio__',
              'dependencies': ['SAL-001'], 'caveats': ['简化口径：未包含财务费用。']}
METRIC_TURN = {'code': 'INV-005', 'name': '库存周转次数', 'unit': '次', 'domain': '库存',
               'definition': '销售成本与平均库存之比', 'formula': '销售成本 ÷ 平均库存',
               'time_field': 'snapshot_date', 'table': 'inventory_snapshots', 'caveats': []}
METRIC_BROKEN = {'code': 'BAD-001', 'name': '缺字段指标'}          # 主数据缺定义/公式/单位
REGISTRY = {m['code']: m for m in (METRIC_SAL, METRIC_FIN, METRIC_TURN, METRIC_BROKEN)}


def understanding(**values):
    base = dict(intent='query', complexity='simple', metric_codes=['SAL-001'],
                tables=['sales_orders'], rewrite='2026年8月营业收入是多少元？')
    base.update(values)
    return base


def linked(**values):
    """linked['metrics'] 是检索候选：这里刻意放入无关指标，验证不会被写成口径。"""
    base = {'metrics': [{'name': '营业收入', 'text': '...'}, {'name': '库存周转次数', 'text': '...'}],
            'tables': [{'table_name': 'sales_orders'}, {'table_name': 'inventory_snapshots'}]}
    base.update(values)
    return base


def test_single_metric_explains_definition_unit_and_time_field():
    out = e.explain('2026年8月营业收入是多少元？', understanding(), linked(), [{'v': 1}], REGISTRY)
    assert out['row_count'] == 1 and out['source_tables_from_sql'] is False
    m = out['metrics'][0]
    assert (m['code'], m['unit'], m['time_field'], m['role']) == ('SAL-001', '元', 'delivery_date', 'primary')
    for fragment in ['SAL-001', '营业收入', '元', 'delivery_date', '已完成且已交付订单的净额合计', 'Σ net_amount']:
        assert fragment in out['summary']


def test_retrieval_candidates_are_never_reported_as_metric():
    """负向对照：检索候选里的无关指标不得出现在解释里（真实数据上发现过该缺陷）。"""
    out = e.explain('2026年8月营业收入是多少元？', understanding(), linked(), [{'v': 1}], REGISTRY)
    assert [m['code'] for m in out['metrics']] == ['SAL-001']
    assert 'INV-005' not in out['summary'] and '库存周转次数' not in out['summary']


def test_dependencies_are_listed_with_roles():
    out = e.explain('2026年8月期间费用率是多少？', understanding(metric_codes=['FIN-006']),
                    linked(), [{'v': 4.760421}], REGISTRY)
    assert [(m['code'], m['role']) for m in out['metrics']] == [('FIN-006', 'primary'), ('SAL-001', 'dependency')]
    assert '依赖指标：营业收入（SAL-001）' in out['summary']


def test_cross_table_placeholder_is_hidden_and_empty_time_field_is_omitted():
    """对外不得出现内部占位符，也不得出现「时间字段：。」残句。"""
    out = e.explain('2026年8月期间费用率是多少？', understanding(metric_codes=['FIN-006']),
                    linked(), [{'v': 4.760421}], REGISTRY)
    fin = out['metrics'][0]
    assert fin['table'] is None
    assert not any(str(m['table']).startswith('__') for m in out['metrics'])
    assert '时间字段：。' not in out['summary'] and '时间字段' not in out['summary']


def test_source_tables_come_from_executed_sql_not_candidates():
    sql = ('SELECT d.warehouse_name,SUM(f.transferred_meters) FROM stock_transfers f '
           'JOIN dim_warehouses d ON f.warehouse_id=d.warehouse_id GROUP BY d.warehouse_name')
    out = e.explain('调拨米数按仓库汇总', understanding(metric_codes=[], tables=['stock_transfers']),
                    linked(), [{'a': 1}], REGISTRY, sql=sql)
    assert out['source_tables'] == ['stock_transfers', 'dim_warehouses']
    assert out['source_tables_from_sql'] is True
    assert 'inventory_snapshots' not in out['source_tables']
    assert e.CANDIDATE_SOURCE_NOTE not in out['notes']


def test_cte_alias_is_not_reported_as_table():
    sql = 'WITH recent AS (SELECT * FROM stock_transfers) SELECT * FROM recent'
    out = e.explain('q', understanding(metric_codes=[]), linked(), [], REGISTRY, sql=sql)
    assert out['source_tables'] == ['stock_transfers']


def test_unparsable_sql_falls_back_to_candidates_and_says_so():
    """回落候选表必须显式标注"未经执行验证"，不能与 SQL 解析出的来源混为一谈。"""
    out = e.explain('q', understanding(metric_codes=[]), linked(metrics=[]), [], REGISTRY, sql='不是SQL')
    assert out['source_tables'] == ['sales_orders', 'inventory_snapshots']
    assert out['source_tables_from_sql'] is False
    assert e.CANDIDATE_SOURCE_NOTE in out['notes']


def test_metric_caveats_become_notes():
    out = e.explain('2026年8月期间费用率是多少？', understanding(metric_codes=['FIN-006']),
                    linked(), [{'v': 4.760421}], REGISTRY)
    assert any('未包含财务费用' in n for n in out['notes'])
    assert out['notes'][0] == e.SOURCE_NOTE


def test_without_metric_falls_back_to_table_level_sentence():
    out = e.explain('查询扩展业务表stock_transfers，按仓库汇总调拨米数。',
                    understanding(metric_codes=[], tables=['stock_transfers']),
                    linked(), [{'a': 1}, {'a': 2}], REGISTRY)
    assert out['metrics'] == [] and out['row_count'] == 2
    assert out['summary'].startswith(e.NO_METRIC_NOTE)


@pytest.mark.parametrize('rows', [[], None])
def test_empty_result_still_produces_explanation(rows):
    out = e.explain('2026年8月营业收入是多少元？', understanding(), linked(), rows, REGISTRY)
    assert out['row_count'] == 0 and 'SAL-001' in out['summary']


def test_maindata_missing_fields_degrades_instead_of_crashing():
    """主数据缺字段时降级为"未登记"，不得抛 KeyError（评审 F4）。"""
    out = e.explain('q', understanding(metric_codes=['BAD-001']), linked(metrics=[]), [], REGISTRY)
    bad = out['metrics'][0]
    assert bad['unit'] == e.UNREGISTERED and bad['formula'] == e.UNREGISTERED
    assert 'BAD-001' in out['summary']


def test_pydantic_like_object_is_supported():
    """single_query 传入的是 Understanding 模型，run() 路径传入的是 model_dump() 字典。"""

    class Obj:
        metric_codes = ['SAL-001']

    out = e.explain('q', Obj(), linked(), [{'v': 1}], REGISTRY)
    assert [m['code'] for m in out['metrics']] == ['SAL-001']


def test_unknown_metric_code_is_ignored_not_invented():
    out = e.explain('q', understanding(metric_codes=['NOPE-999']), linked(metrics=[]), [], REGISTRY)
    assert out['metrics'] == [] and out['summary'].startswith(e.NO_METRIC_NOTE)


def test_dependency_cycle_terminates():
    a = {'code': 'C-1', 'name': '环A', 'unit': '元', 'definition': 'x', 'formula': 'y',
         'time_field': 'd', 'table': 't', 'dependencies': ['C-2'], 'caveats': []}
    b = {'code': 'C-2', 'name': '环B', 'unit': '元', 'definition': 'x', 'formula': 'y',
         'time_field': 'd', 'table': 't', 'dependencies': ['C-1'], 'caveats': []}
    out = e.explain('q', understanding(metric_codes=['C-1']), linked(metrics=[]), [],
                    {'C-1': a, 'C-2': b})
    assert [m['code'] for m in out['metrics']] == ['C-1', 'C-2']
