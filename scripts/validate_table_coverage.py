"""52 张业务表的端到端覆盖验收（确定性检查，默认不调用生成模型）。

四类检查，逐表逐项记录：
1. MySQL：表存在、有数据、字段与目录一致
2. 向量索引：表级与字段级向量是否齐全
3. 检索召回：以「表名」和「中文描述」两种提问，hybrid 检索能否召回该表（hit@4 / hit@1）
4. 权限与数据区域：逐角色逐表验证放行与拒绝、隐藏字段不可选、区域过滤真的写进 SQL

用法：
    .venv/Scripts/python.exe scripts/validate_table_coverage.py
    .venv/Scripts/python.exe scripts/validate_table_coverage.py --llm-sample 6   # 另抽 6 张表跑真实问数

输出：artifacts/table-coverage-52.json
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymysql
from security import SecurityError, UserContext

from textile.catalog import CATALOG
from textile.extended_catalog import DOMAINS
from textile.models import embed_batch
from textile.permissions import HIDDEN_FIELDS, REGION_BOUND_ROLES, ROLES, TABLES_BY_ROLE
from textile.retrieval import COLLECTION, documents, hybrid_search, milvus
from textile.security import TextileSecurity
from textile.settings import DB, ROOT

TABLES = sorted(CATALOG)
REGION = '华东'
BATCH = 10


def mysql_checks():
    """表存在、行数、字段与目录是否一致。"""
    out = {}
    with pymysql.connect(**DB) as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        for table in TABLES:
            cur.execute(f'SELECT COUNT(*) AS n FROM `{table}`')
            rows = cur.fetchone()['n']
            cur.execute(f'SHOW COLUMNS FROM `{table}`')
            columns = {r['Field'] for r in cur.fetchall()}
            catalog_columns = set(CATALOG[table][1])
            out[table] = {'rows': rows, 'has_data': rows > 0,
                          'columns_match': columns == catalog_columns,
                          'missing_in_db': sorted(catalog_columns - columns),
                          'extra_in_db': sorted(columns - catalog_columns)}
    return out


def index_checks():
    """一次遍历向量集合，统计每张表的表级/字段级向量数。"""
    expected_tables = {d['table_name'] for d in documents() if d['kind'] == 'table'}
    expected_fields = Counter(d['table_name'] for d in documents() if d['kind'] == 'field')
    actual_tables = Counter()
    actual_fields = Counter()
    client = milvus()
    iterator = client.query_iterator(collection_name=COLLECTION, batch_size=500, filter='',
                                     output_fields=['kind', 'table_name'])
    total = 0
    try:
        while batch := iterator.next():
            for row in batch:
                total += 1
                if row['kind'] == 'table':
                    actual_tables[row['table_name']] += 1
                elif row['kind'] == 'field':
                    actual_fields[row['table_name']] += 1
    finally:
        iterator.close()
    out = {}
    for table in TABLES:
        want_fields = expected_fields.get(table, 0)
        out[table] = {'table_vectors': actual_tables.get(table, 0),
                      'field_vectors': actual_fields.get(table, 0),
                      'expected_fields': want_fields,
                      'indexed': actual_tables.get(table, 0) == 1 and actual_fields.get(table, 0) >= want_fields}
    return out, {'entities': total, 'tables_indexed': len(actual_tables)}


def retrieval_checks():
    """表名提问（容易）与纯中文描述提问（更接近真实用户）两种召回对比。"""
    from textile.security import allowed_catalog
    allowed = allowed_catalog(UserContext('evaluation', 'admin'))
    questions = {}
    for table in TABLES:
        desc = CATALOG[table][0]
        questions[table] = (f'{table} 表的{desc}数据有哪些', f'{desc}相关的数据有哪些')
    texts = [q for pair in questions.values() for q in pair]
    vectors = {}
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        for text, vector in zip(chunk, embed_batch(chunk)):
            vectors[text] = vector
    out = {}
    for table, (by_name, by_desc) in questions.items():
        rows_name = [h['table_name'] for h in hybrid_search(by_name, vectors[by_name], 'table', allowed, 4)]
        rows_desc = [h['table_name'] for h in hybrid_search(by_desc, vectors[by_desc], 'table', allowed, 4)]
        out[table] = {'by_name_top4': rows_name, 'by_desc_top4': rows_desc,
                      'hit4_by_name': table in rows_name, 'hit1_by_name': rows_name[:1] == [table],
                      'hit4_by_desc': table in rows_desc}
    return out


def permission_checks():
    """逐角色逐表验证：放行/拒绝与角色矩阵一致、隐藏字段不可选、区域过滤生效。"""
    security = TextileSecurity()
    out = defaultdict(dict)
    for role in ROLES:
        user = UserContext(role, role, REGION if role in REGION_BOUND_ROLES else None)
        for table in TABLES:
            column = next(iter(CATALOG[table][1]))
            sql = f'SELECT {column} FROM {table} LIMIT 1'
            try:
                security.secure_sql(sql, user)
                allowed = True
                rewritten = None
            except SecurityError:
                allowed = False
                rewritten = None
            expected = table in TABLES_BY_ROLE[role]
            record = {'allowed': allowed, 'expected': expected, 'matches_matrix': allowed == expected}
            if allowed:
                hidden = [f for f in CATALOG[table][1] if f in HIDDEN_FIELDS.get(role, set())]
                if hidden:
                    try:
                        security.secure_sql(f'SELECT {hidden[0]} FROM {table} LIMIT 1', user)
                        record['hidden_field_blocked'] = False
                    except SecurityError:
                        record['hidden_field_blocked'] = True
                if user.region and 'region' in CATALOG[table][1]:
                    rewritten = str(security.secure_sql(sql, user))
                    record['region_filtered'] = REGION in rewritten
            out[role][table] = record
    return {role: dict(tables) for role, tables in out.items()}


def llm_sample(count):
    """可选：抽 N 张表跑真实问数（消耗模型额度），验证 NL→SQL→执行链路。

    结果比对复用 evaluation 的标准比较器 equal()：忽略列名与行序、数值带容差。
    用裸 == 会把「列名叫 record_count 而不是 n」误判为失败。
    """
    if count <= 0:
        return {}
    from textile.agent import single_query
    from textile.db import query
    from scripts.evaluate_textile import equal
    by_domain = defaultdict(list)
    for table in TABLES:
        by_domain[DOMAINS.get(table, 'core')].append(table)
    # 每个域抽一张，保证样本跨域而不是挤在同一个业务域。
    picked = [sorted(tables)[0] for _, tables in sorted(by_domain.items())][:count]
    results = {}
    for table in picked:
        question = f'{CATALOG[table][0]}（{table}）当前有多少条记录？只返回记录数，不四舍五入。'
        try:
            actual = single_query(question, UserContext('evaluation', 'admin'))
            expected = query(f'SELECT COUNT(*) AS n FROM `{table}`')['rows']
            results[table] = {'question': question, 'passed': equal(expected, actual['rows']),
                              'expected': expected, 'actual': actual['rows'], 'sql': actual['sql']}
        except Exception as exc:
            results[table] = {'question': question, 'passed': False, 'error': str(exc)[:300]}
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--llm-sample', type=int, default=0)
    args = parser.parse_args()
    if not os.environ.get('DASHSCOPE_API_KEY'):
        # 检索召回检查要调 embedding；缺 key 时在 models 深处抛 KeyError 很难排查。
        raise SystemExit('缺少 DASHSCOPE_API_KEY：检索召回检查需要 embedding 调用，请先设置环境变量。')
    started = time.time()

    print(f'业务表 {len(TABLES)} 张；开始确定性检查……')
    mysql_rows = mysql_checks()
    index_rows, index_meta = index_checks()
    print(f'  向量集合共 {index_meta["entities"]} 条实体，覆盖 {index_meta["tables_indexed"]} 张表')
    retrieval_rows = retrieval_checks()
    permission_rows = permission_checks()
    llm_rows = llm_sample(args.llm_sample)

    tables = {}
    failures = []
    for table in TABLES:
        record = {'domain': DOMAINS.get(table, 'core'), 'description': CATALOG[table][0],
                  'mysql': mysql_rows[table], 'index': index_rows[table], 'retrieval': retrieval_rows[table]}
        record['ok'] = bool(mysql_rows[table]['has_data'] and mysql_rows[table]['columns_match']
                            and index_rows[table]['indexed'] and retrieval_rows[table]['hit4_by_name'])
        if table in llm_rows:
            record['llm_sample'] = llm_rows[table]
            record['ok'] = record['ok'] and llm_rows[table]['passed']
        tables[table] = record
        if not record['ok']:
            failures.append({'table': table, 'mysql_ok': mysql_rows[table]['has_data'] and mysql_rows[table]['columns_match'],
                             'indexed': index_rows[table]['indexed'],
                             'hit4_by_name': retrieval_rows[table]['hit4_by_name'],
                             'hit4_by_desc': retrieval_rows[table]['hit4_by_desc']})

    permission_failures = [{'role': role, 'table': table, **rec}
                           for role, per_table in permission_rows.items()
                           for table, rec in per_table.items()
                           if not rec['matches_matrix'] or rec.get('hidden_field_blocked') is False]

    summary = {
        'checked_at': datetime.now().isoformat(timespec='seconds'),
        'seconds': round(time.time() - started, 1),
        'tables': len(TABLES),
        'domains': dict(Counter(DOMAINS.get(t, 'core') for t in TABLES)),
        'mysql_ok': sum(1 for t in TABLES if mysql_rows[t]['has_data'] and mysql_rows[t]['columns_match']),
        'indexed_ok': sum(1 for t in TABLES if index_rows[t]['indexed']),
        'hit4_by_name_ok': sum(1 for t in TABLES if retrieval_rows[t]['hit4_by_name']),
        'hit4_by_desc_ok': sum(1 for t in TABLES if retrieval_rows[t]['hit4_by_desc']),
        'permission_matrix_ok': sum(1 for role in permission_rows for rec in permission_rows[role].values()
                                    if rec['matches_matrix']),
        'permission_checks': sum(len(v) for v in permission_rows.values()),
        'llm_sampled': len(llm_rows),
        'llm_passed': sum(1 for r in llm_rows.values() if r['passed']),
        'tables_fully_ok': sum(1 for t in TABLES if tables[t]['ok']),
        'index_entities': index_meta['entities'],
    }
    artifact = {'summary': summary, 'tables': tables, 'table_failures': failures,
                'permission_failures': permission_failures,
                'note': '确定性覆盖验收；检索用表名与中文描述两种提问。不代表生产准确率。'}
    target = ROOT / 'artifacts' / 'table-coverage-52.json'
    target.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if failures:
        print('\n未完全通过的表：')
        for item in failures:
            print('  ', json.dumps(item, ensure_ascii=False))
    if permission_failures:
        print('\n权限矩阵不一致：')
        for item in permission_failures[:10]:
            print('  ', json.dumps(item, ensure_ascii=False))
    print('\n输出：' + str(target))


if __name__ == '__main__':
    main()
