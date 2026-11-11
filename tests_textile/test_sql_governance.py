"""A8 SQL 资源治理的断言：超时真实生效、计数不可丢、health 真暴露、LIMIT 真收敛。

第一版只有 9 例、被独立评审的变异测试存活 5/10（"health 暴露""结果带 execution.governance"
"成功/失败都计数"三条承诺无法被证伪）。本版针对那 5 个存活变异体逐条补断言：
  M6 stats 忽略配置 → test_stats_reflect_configured_thresholds
  M7 结果丢掉 governance 键 → test_execution_governance_present_and_kind_slow
  M8 成功路径不计数 → 同上（先 reset 再断言 queries 增加）
  M9 失败路径不计数 → test_failed_query_also_counts
  M10 health 丢字段 → test_health_exposes_sql_governance
另补：翻译层超时识别（评审 F1）、跨进程计数（F3）、内层 LIMIT 收敛与非法改写拒绝（F6）。
全部用例不调用模型。
"""
import logging
import subprocess
import sys
import threading
from pathlib import Path

import pymysql
import pytest
import sqlglot

from database import QueryExecutionError
from security import SecurityError, UserContext
from textile import governance
from textile.security import TextileSecurity

ADMIN = UserContext('test', 'admin')
SLOW_SQL = 'SELECT COUNT(order_id) AS n FROM sales_orders'
# 负向对照需要一条"确定会被超时检查抓到"的语句（探针实测见 AI_WORKLOG 任务 4）：
# 小表 COUNT 会在首次检查前跑完、SLEEP 被中断时不报错，只有自连接稳定报 3024。
HEAVY_SQL = 'SELECT COUNT(*) FROM sales_orders a JOIN sales_orders b ON 1=1'


def _connection(timeout_ms=None):
    from textile.settings import DB
    conn = pymysql.connect(**DB)
    if timeout_ms is not None:
        governance.apply_timeout(conn, timeout_ms)
    return conn


# ---------- 超时机制 ----------

def test_is_timeout_recognises_both_mysql_interrupt_codes():
    assert governance.is_timeout(pymysql.err.OperationalError(3024, 'Query execution was interrupted'))
    assert governance.is_timeout(pymysql.err.OperationalError(1317, 'Query execution was interrupted'))
    assert not governance.is_timeout(pymysql.err.OperationalError(1064, 'You have an error in your SQL syntax'))


def test_is_timeout_recognises_translated_timeout_from_real_entry():
    """评审 F1：真实入口把 3024 翻译成 QueryExecutionError(error_type='query_timeout')，
    原始码与文本都丢了；只认原始码会把超时错记成普通 error。"""
    translated = QueryExecutionError('query_timeout', 'SQL 执行超时，请缩小时间范围或减少返回列后重试',
                                     {'error_code': 3024, 'sql': SLOW_SQL})
    assert governance.is_timeout(translated)
    assert not governance.is_timeout(QueryExecutionError('sql_syntax', '语法错误', {'error_code': 1064}))


def test_apply_timeout_sets_the_session_variable():
    conn = _connection()
    try:
        governance.apply_timeout(conn, 4321)
        with conn.cursor() as c:
            c.execute('SELECT @@SESSION.max_execution_time')
            assert c.fetchone()[0] == 4321
    finally:
        conn.close()


def test_timeout_actually_interrupts_a_normal_query():
    """负向对照：1 毫秒阈值下，耗时只读查询必须被杀（证明超时不是摆设）。"""
    conn = _connection()
    try:
        governance.apply_timeout(conn, 1)
        with pytest.raises(pymysql.err.OperationalError) as excinfo:
            with conn.cursor() as c:
                c.execute(HEAVY_SQL)
                c.fetchall()
        assert governance.is_timeout(excinfo.value)
    finally:
        conn.close()


def test_same_query_succeeds_under_default_timeout():
    """正对照：默认阈值下同一条查询必须成功（排除"语句本身有问题"）。"""
    conn = _connection()
    try:
        governance.apply_timeout(conn, 8000)
        with conn.cursor() as c:
            c.execute(HEAVY_SQL)
            assert c.fetchone()[0] > 0
    finally:
        conn.close()


# ---------- 计数与日志 ----------

def test_governance_counts_slow_and_timeout_and_logs(caplog):
    governance.COUNTERS.reset()
    timeout_error = QueryExecutionError('query_timeout', '超时', {'error_code': 3024})
    with caplog.at_level(logging.WARNING, logger='textile.sql'):
        governance.record(SLOW_SQL, 250, slow_ms=200)
        governance.record(SLOW_SQL, 9000, timeout_ms=8000, error=timeout_error)
        ok = governance.record(SLOW_SQL, 12, slow_ms=200)
    snap = governance.COUNTERS.snapshot()
    assert (snap['queries'], snap['slow_queries'], snap['timeouts']) == (3, 1, 1)
    assert ok['kind'] == 'ok' and 'elapsed_ms' in ok
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith('sql_slow') for m in messages)
    assert any(m.startswith('sql_timeout') for m in messages)


def test_non_timeout_error_is_not_counted_as_timeout():
    """负向对照：语法错误不能被算成超时，否则"超时数"会虚高。"""
    governance.COUNTERS.reset()
    governance.record(SLOW_SQL, 5, slow_ms=200, error=pymysql.err.ProgrammingError(1064, 'syntax error'))
    assert governance.COUNTERS.snapshot()['timeouts'] == 0


def test_counters_are_thread_safe():
    """并发写计数不得丢（评审要求补的强度）：16 线程 × 500 次必须精确等于 8000。"""
    governance.COUNTERS.reset()
    threads = [threading.Thread(target=lambda: [governance.record(SLOW_SQL, 1, slow_ms=200) for _ in range(500)])
               for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert governance.COUNTERS.snapshot()['queries'] == 8000


# ---------- db.query 接入（杀掉 M7/M8/M9） ----------

def test_execution_governance_present_and_kind_slow(monkeypatch):
    """成功路径必须计数并回传 execution.governance；阈值配置必须真的生效。"""
    import textile.db as tdb
    governance.COUNTERS.reset()
    monkeypatch.setattr(tdb, 'SLOW_QUERY_MS', 0)          # 任何耗时都算慢查询
    result = tdb.query(SLOW_SQL)
    assert result['execution']['governance']['kind'] == 'slow'
    assert result['execution']['governance']['elapsed_ms'] >= 0
    assert governance.COUNTERS.snapshot()['queries'] == 1
    assert governance.COUNTERS.snapshot()['slow_queries'] == 1


def test_failed_query_also_counts():
    """失败路径（含安全层拒绝）也必须计入 queries，否则"被拦下的查询"不可见。"""
    import textile.db as tdb
    governance.COUNTERS.reset()
    with pytest.raises(SecurityError):
        tdb.query('SELECT SLEEP(9)')
    snap = governance.COUNTERS.snapshot()
    assert snap['queries'] == 1 and snap['timeouts'] == 0


# ---------- health 暴露（杀掉 M10/M6） ----------

def test_health_exposes_sql_governance():
    from textile.app import health
    block = health()['sql_governance']
    assert block['scope'] == 'process'
    assert {'queries', 'slow_queries', 'timeouts', 'query_timeout_ms', 'slow_query_ms'} <= set(block)
    assert 'shared' in block and 'shared_available' in block


def test_health_probe_does_not_pollute_counters():
    """健康检查自己的探活查询不得计入治理统计（否则数字是自我污染）。"""
    from textile.app import health
    governance.COUNTERS.reset()
    health()
    assert governance.COUNTERS.snapshot()['queries'] == 0


def test_stats_reflect_configured_thresholds(monkeypatch):
    """阈值必须来自配置而不是硬编码（存活变异体 M6）。"""
    import textile.settings as settings
    monkeypatch.setattr(settings, 'QUERY_TIMEOUT_MS', 1234)
    monkeypatch.setattr(settings, 'SLOW_QUERY_MS', 7)
    stats = governance.stats()
    assert (stats['query_timeout_ms'], stats['slow_query_ms']) == (1234, 7)


def test_shared_counters_are_visible_across_processes(tmp_path):
    """评审 F3：真实查询在 arq worker 进程执行，API 进程必须能在 Redis 里读到汇总。"""
    child = tmp_path / 'child.py'
    child.write_text(
        'import sys\n'
        f'sys.path.insert(0, r"{Path(__file__).resolve().parents[1]}")\n'
        'from textile import governance\n'
        'for _ in range(3): governance.record("SELECT 1", 1, slow_ms=200)\n',
        encoding='utf-8')
    before = governance.stats()
    if not before['shared_available']:
        pytest.skip('Redis 不可用，跨进程计数无法验证')
    subprocess.run([sys.executable, str(child)], check=True, capture_output=True)
    after = governance.stats()
    assert after['shared']['queries'] >= before['shared']['queries'] + 3


# ---------- LIMIT 强制与安全层（F6） ----------

def test_security_injects_limit_when_missing_and_clamps_large_limit():
    security = TextileSecurity()
    assert 'LIMIT 200' in str(security.secure_sql('SELECT order_id FROM sales_orders', ADMIN)).upper()
    assert 'LIMIT 200' in str(security.secure_sql('SELECT order_id FROM sales_orders LIMIT 99999', ADMIN)).upper()


def test_inner_subquery_and_cte_limits_are_clamped_too():
    """评审 F6：内层 LIMIT 不收敛时，"最多 200 行"只是外层截断，内层仍可物化巨量行。"""
    security = TextileSecurity()
    subquery = str(security.secure_sql(
        'SELECT x.n FROM (SELECT order_id AS n FROM sales_orders LIMIT 99999) AS x', ADMIN))
    cte = str(security.secure_sql(
        'WITH c AS (SELECT order_id AS n FROM sales_orders LIMIT 99999) SELECT n FROM c', ADMIN))
    for sql in (subquery, cte):
        assert '99999' not in sql
        assert sql.upper().count('LIMIT 200') == 2      # 内层 + 外层各一次


def test_union_with_limit_is_clamped_and_stays_parseable():
    """评审 F6 附带：旧实现把 LIMIT 加在 UNION 外层会生成语法非法语句（执行时才报 1064）；
    现在每个分支各自收敛到 200，改写结果仍然合法可解析。"""
    out = str(TextileSecurity().secure_sql(
        'SELECT order_id FROM sales_orders LIMIT 99999 UNION ALL SELECT order_id FROM sales_orders LIMIT 99999',
        ADMIN))
    assert '99999' not in out
    assert out.upper().count('LIMIT 200') == 2
    sqlglot.parse_one(out, read='mysql')


def test_security_rejects_sleep_so_timeout_cannot_be_weaponised():
    """负向对照：SLEEP 类耗资源函数必须被安全层拒绝（超时是兜底，不是唯一防线）。"""
    with pytest.raises(SecurityError):
        TextileSecurity().secure_sql('SELECT SLEEP(9)', ADMIN)


def test_stats_have_expected_keys():
    stats = governance.stats()
    assert stats['scope'] == 'process'
    assert {'queries', 'slow_queries', 'timeouts', 'query_timeout_ms', 'slow_query_ms'} <= set(stats)
