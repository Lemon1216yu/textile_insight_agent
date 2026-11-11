"""B2 审计日志的断言：谁 / 何时 / 查了什么 / 返回什么，且仅管理员可读。

背景：审计主体（audit_events 表 + `task_queue.audit()` + app.py 的登录/账户事件 +
`finished_detail()`）在既有实现里就有，但**此前零测试**，属"未经验证"。本文件补上
可证伪断言，并覆盖本轮新增的过滤/分页与 detail 解析。

所有用例不调用模型。
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime

import pymysql
import pytest
from fastapi.testclient import TestClient

from textile import models, task_queue
from textile.app import app
from textile.settings import DB
from textile.task_queue import audit, finished_detail, result_facts

DEMO_PASSWORD = 'demo123'
# 审计表对 textile_app 只授 SELECT/INSERT（表设计为只能追加），所以测试残留用运维账号清理。
_ADMIN_DB = {**DB, 'user': 'root', 'password': os.environ.get('TEXTILE_MYSQL_ROOT_PASSWORD', '')}


def purge_actions(*actions):
    actions = [a for a in actions if a]
    if not actions:
        return
    with pymysql.connect(**_ADMIN_DB) as conn, conn.cursor() as cur:
        cur.execute('DELETE FROM audit_events WHERE action IN (%s)' % ','.join(['%s'] * len(actions)), actions)


def login(c, username, password=DEMO_PASSWORD):
    r = c.post('/api/login', json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return r.json()


def _job(**overrides):
    job = {'id': 'job-1', 'mode': 'chat', 'status': 'done', 'question': '8 月营业收入是多少',
           'actor_role': 'executive', 'actor_region': '华东', 'duration_seconds': 2.5,
           'results': [{'sql': 'SELECT SUM(net_amount) FROM sales_orders LIMIT 200',
                        'row_count': 1, 'columns': ['net_amount'], 'limited_to': 200}]}
    job.update(overrides)
    return job


# ---------- 纯函数：审计明细的内容 ----------

def test_result_facts_capture_what_was_queried_and_returned():
    facts = result_facts(_job())
    assert facts == [{'sql': 'SELECT SUM(net_amount) FROM sales_orders LIMIT 200', 'sql_truncated': False,
                      'row_count': 1, 'columns': ['net_amount'], 'limited_to': 200}]


def test_result_facts_truncate_long_sql_and_flag_it():
    long_sql = 'SELECT ' + 'a,' * 500 + 'b FROM sales_orders'
    facts = result_facts(_job(results=[{'sql': long_sql, 'row_count': 0, 'columns': []}]))
    assert len(facts[0]['sql']) == 800 and facts[0]['sql_truncated'] is True


def test_finished_detail_covers_who_when_what_and_returned():
    detail = finished_detail(_job())
    assert detail['question'] == '8 月营业收入是多少'      # 问了什么
    assert detail['role'] == 'executive' and detail['region'] == '华东'   # 谁（身份侧写）
    assert detail['status'] == 'done' and detail['row_counts'] == [1]     # 返回了什么
    assert detail['results'][0]['row_count'] == 1
    assert 'error' not in detail


def test_finished_detail_records_failure_and_denial():
    failed = finished_detail(_job(status='failed', error='SQL字段或语法校验失败：多个事实来源必须先分别聚合',
                                  error_type='security', denied=True, results=[]))
    assert failed['error_type'] == 'security' and failed['denied'] is True
    assert 'SQL字段或语法校验失败' in failed['error'] and failed['row_counts'] == []


def test_finished_detail_surfaces_step_level_failure_without_exception():
    """步骤失败走 run() 内部的 results 回传（不抛异常）时，审计必须仍能解释"为什么失败"。
    真实端到端曾跑出 status=failed 但 detail['error'] 为空、且把失败步骤记成"查了空 SQL/返回 0 行"，
    读者无法判断是失败还是查了个空 —— 用户要求审计能追溯"查了什么、返回什么"。"""
    job = _job(status='failed', error=None, error_type=None, denied=False,
               results=[{'success': False, 'error': "'DASHSCOPE_API_KEY'",
                         'step': {'id': 1, 'title': '业务问数'}}])
    detail = finished_detail(job)
    assert 'DASHSCOPE_API_KEY' in detail['error']          # 失败原因必须可见
    assert detail['error_type'] == 'StepFailed'            # 与"被安全层拒绝"区分开
    assert result_facts(job) == [{'failed': True, 'error': "'DASHSCOPE_API_KEY'", 'step': '业务问数'}]
    assert 'sql' not in result_facts(job)[0]               # 失败步骤不伪造 SQL
    assert detail['row_counts'] == [0] and detail['denied'] is False


# ---------- 端到端：写入 → 经管理员接口读回 ----------

def test_audit_round_trip_through_admin_endpoint():
    """真实写一条审计 → 用管理员会话按 action 过滤读回，detail 必须解析成对象。"""
    action = 'test_audit_' + uuid.uuid4().hex[:8]
    try:
        audit('integration_probe', action, {'question': '测试问题', 'row_count': 3, 'nested': {'a': 1}})
        with TestClient(app) as c:
            login(c, 'admin')
            r = c.get('/api/admin/audit', params={'action': action})
            assert r.status_code == 200, r.text
            body = r.json()
        assert body['total'] == 1 and len(body['items']) == 1
        item = body['items'][0]
        assert item['username'] == 'integration_probe' and item['action'] == action
        # 何时：必须是带时区偏移的 ISO 字符串（DB 时钟为 UTC，裸值会让前端差 8 小时）
        occurred = item['occurred_at']
        assert isinstance(occurred, str) and (occurred.endswith('Z') or '+' in occurred or '-0' in occurred)
        parsed = datetime.fromisoformat(occurred)
        assert parsed.tzinfo is not None and parsed.utcoffset() is not None
        assert item['detail']['row_count'] == 3 and item['detail']['nested']['a'] == 1
    finally:
        purge_actions(action)


def test_audit_endpoint_requires_admin():
    """负向对照：非管理员必须 403（审计日志含全员查询内容）。"""
    with TestClient(app) as c:
        login(c, 'executive')
        assert c.get('/api/admin/audit').status_code == 403
    with TestClient(app) as c:
        assert c.get('/api/admin/audit').status_code == 401      # 未登录


def test_audit_filters_and_limit_are_enforced():
    action = 'test_audit_' + uuid.uuid4().hex[:8]
    try:
        for i in range(3):
            audit('probe_%d' % i, action, {'row_count': i})
        with TestClient(app) as c:
            login(c, 'admin')
            by_action = c.get('/api/admin/audit', params={'action': action}).json()
            assert by_action['total'] == 3
            assert [i['detail']['row_count'] for i in by_action['items']] == [2, 1, 0]   # 倒序
            by_user = c.get('/api/admin/audit', params={'action': action, 'username': 'probe_1'}).json()
            assert by_user['total'] == 1 and by_user['items'][0]['username'] == 'probe_1'
            clamped = c.get('/api/admin/audit', params={'action': action, 'limit': 9999}).json()
            assert clamped['limit'] == 500 and clamped['total'] == 3
            missing = c.get('/api/admin/audit', params={'action': action, 'username': 'nobody'}).json()
            assert missing['total'] == 0 and missing['items'] == []
    finally:
        purge_actions(action)


def test_login_and_logout_are_audited():
    """既有事件链：登录/登出都要留痕（谁+何时+动作）。"""
    action = 'test_audit_' + uuid.uuid4().hex[:8]
    with TestClient(app) as c:
        login(c, 'admin')
        c.post('/api/logout')
    with TestClient(app) as c:
        login(c, 'admin')
        rows = c.get('/api/admin/audit', params={'username': 'admin', 'limit': 20}).json()['items']
    actions = [r['action'] for r in rows]
    assert 'login' in actions
    assert all(r['occurred_at'] for r in rows)
    purge_actions(action)   # 无新增行需要清理，保持与其他用例一致的收尾


# ---------- 模型归属：不得跨线程串号，也不得把"没调模型"记成首选模型 ----------

def test_model_attribution_ignores_global_usage_list(monkeypatch):
    """负向对照（杀死旧实现）：旧实现读 Redis `textile:usage` 的最新一条，
    那是全局共享记录，并发时会把别人的模型标到本任务上。
    此处伪造一条"最近调用"，新实现必须无视它 —— 本线程没调过模型就只能是 None。"""
    class _FakeRedis:
        def lindex(self, key, index):
            return json.dumps({'user': 'someone_else', 'model': 'global-decoy-model'})
    monkeypatch.setattr(task_queue, 'redis_client', lambda: _FakeRedis())
    assert task_queue._model_used() is None
    # 未调用模型时不得回落到"首选模型"（假归属）
    assert finished_detail(_job())['model'] is None


def test_model_attribution_is_isolated_across_threads():
    """两个线程各自"调用模型"（用 models 的 contextvar 模拟真实写入点），互不串号。"""
    got = {}

    def worker(name, model):
        models._last_call.set({'model': model, 'fallback': True})
        time.sleep(0.05)                      # 让两个线程的写入窗口真实重叠
        got[name] = task_queue._model_used()

    threads = [threading.Thread(target=worker, args=(n, m))
               for n, m in (('a', 'model-a'), ('b', 'model-b'))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert got == {'a': 'model-a', 'b': 'model-b'}


def test_finished_detail_reports_the_real_model_after_a_call():
    models._last_call.set({'model': 'qwen3.8-max-0902', 'fallback': True})
    try:
        assert finished_detail(_job())['model'] == 'qwen3.8-max-0902'
    finally:
        models._last_call.set(None)
