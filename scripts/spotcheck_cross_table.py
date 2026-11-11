"""Spot-check the cross-table metric class end to end (real model calls).

Three published metrics are composed from dependencies (FIN-005 经营利润, FIN-006 期间费用率,
INV-005 库存周转次数). They used to fail because the model saw an empty "authoritative
expression" and joined detail rows (CARTESIAN product inflating numerator/denominator).

Run after any prompt/metric edit:
    .\\.venv\\Scripts\\python.exe scripts\\spotcheck_cross_table.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from security import UserContext
from scripts.evaluate_textile import equal
from textile.agent import single_query
from textile.metric_catalog import compile_sql
from textile.models import llm
from textile.registry import get_metrics
from textile.db import query

CODES = ['FIN-005', 'FIN-006', 'INV-005', 'SAL-008', 'FIN-002']


def main():
    metrics = {m['code']: m for m in get_metrics()}
    failures = 0
    for code in CODES:
        m = metrics.get(code)
        if not m:
            print(f'{code}: MISSING from published master data')
            failures += 1
            continue
        question = (f"2026年8月{m['name']}是多少？按指标{m['code']}的正式管理口径，"
                    f"仅返回一个数值，单位{m['unit']}，不四舍五入。")
        gold = query(compile_sql(m, '2026-08-01', '2026-09-01'))['rows']
        start = time.time()
        try:
            actual = single_query(question, UserContext('spotcheck', 'admin'))
            passed = equal(gold, actual['rows'])
            joined = 'JOIN' in actual['sql'].upper() and 'SELECT' in actual['sql'].upper()
            cross = 'CROSS JOIN' in actual['sql'].upper()
            print(f"{code:8s} {'PASS' if passed else 'FAIL'} | {round(time.time()-start,1)}s "
                  f"| model={llm().last_model} | cross_join={cross} | row_join={joined}")
            print(f"         gold={gold[:1]} actual={actual['rows'][:1]}")
            if not passed:
                failures += 1
                print(f"         sql={actual['sql'][:300]}")
        except Exception as exc:
            failures += 1
            print(f'{code:8s} ERROR | {type(exc).__name__}: {str(exc)[:200]}')
    print(f'\nspot check: {len(CODES)-failures}/{len(CODES)} passed')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
