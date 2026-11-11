"""Publish the Python metric catalog into MySQL, then sync cache and Milvus.

Why this exists: `migrate_platform.py` inserts metric rows with INSERT IGNORE, so it only ever
writes the *first* version of each metric. Any later edit to a metric's wording, formula,
dependencies or caveats stayed in Python source and never reached the running system - the
runtime kept serving the original published definition. That silently disabled metric tuning
(the FIN-006 cross-table caveat was one casualty).

Contract:
  * `textile/metric_catalog.py` is the authoring surface (single source of truth).
  * MySQL `metric_registry` is the published master data the runtime reads.
  * Publishing is fingerprint based: unchanged catalog -> no writes, no invalidation.
  * Redis `textile:metrics:published:v1` is dropped on change, so readers reload immediately.
  * Result caches are keyed by `metrics_revision()`, so a published change invalidates them too.
  * Milvus metric vectors are rebuilt only when the metric text actually changed.

Usage:
    .\\.venv\\Scripts\\python.exe scripts\\publish_metrics.py [--dry-run] [--force] [--skip-index]
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pymysql

from textile.metric_catalog import METRIC_DEFINITIONS, definition_text
from textile.settings import DB

METRIC_CACHE_KEY = 'textile:metrics:published:v1'
INDEX_FINGERPRINT_KEY = 'textile:index:metric_fingerprint'


def fingerprint(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def admin_connect():
    return pymysql.connect(**{**DB, 'user': 'root', 'password': os.environ['TEXTILE_MYSQL_ROOT_PASSWORD']})


def ensure_publication_table(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS metric_publication (
      id TINYINT PRIMARY KEY, fingerprint CHAR(64) NOT NULL, metric_count INT NOT NULL,
      published_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6))''')


def stored_fingerprint(cur):
    ensure_publication_table(cur)
    cur.execute('SELECT fingerprint FROM metric_publication WHERE id=1')
    row = cur.fetchone()
    return row[0] if row else None


def publish(dry_run=False, force=False, skip_index=False):
    source = fingerprint(METRIC_DEFINITIONS)
    with admin_connect() as conn, conn.cursor() as cur:
        previous = stored_fingerprint(cur)
        unchanged = previous == source and not force
        cur.execute('SELECT code, definition FROM metric_registry')
        published = {code: (json.loads(raw) if isinstance(raw, str) else raw) for code, raw in cur.fetchall()}
        changed, added = [], []
        for m in METRIC_DEFINITIONS:
            old = published.get(m['code'])
            if old is None:
                added.append(m['code'])
            elif json.dumps(old, sort_keys=True, ensure_ascii=False) != json.dumps(m, sort_keys=True, ensure_ascii=False):
                changed.append(m['code'])
        orphaned = sorted(set(published) - {m['code'] for m in METRIC_DEFINITIONS})
        plan = {'source_fingerprint': source, 'published_fingerprint': previous, 'unchanged': unchanged,
                'added': added, 'changed': changed, 'orphaned': orphaned, 'metric_count': len(METRIC_DEFINITIONS)}
        if dry_run:
            plan['applied'] = False
            return plan
        if unchanged:
            plan['applied'] = False
            return plan
        for m in METRIC_DEFINITIONS:
            cur.execute('''INSERT INTO metric_registry(code,name,status,version,definition) VALUES(%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE name=VALUES(name),status=VALUES(status),
                                                   version=VALUES(version),definition=VALUES(definition)''',
                        (m['code'], m['name'], m['status'], m['version'], json.dumps(m, ensure_ascii=False)))
        cur.execute('''INSERT INTO metric_publication(id,fingerprint,metric_count) VALUES(1,%s,%s)
                       ON DUPLICATE KEY UPDATE fingerprint=VALUES(fingerprint),metric_count=VALUES(metric_count)''',
                    (source, len(METRIC_DEFINITIONS)))
        plan['applied'] = True
    from textile.registry import redis_client
    cache = redis_client()
    dropped = int(cache.delete(METRIC_CACHE_KEY) or 0)
    metric_text = fingerprint([definition_text(m) for m in METRIC_DEFINITIONS])
    if not skip_index:
        previous_text = cache.get(INDEX_FINGERPRINT_KEY)
        if previous_text != metric_text:
            from textile.retrieval import build_index
            plan['milvus'] = build_index()
            cache.set(INDEX_FINGERPRINT_KEY, metric_text)
    plan['cache_keys_dropped'] = dropped
    plan['metric_text_fingerprint'] = metric_text
    return plan


def main():
    parser = argparse.ArgumentParser(description='Publish metric catalog into MySQL and sync caches.')
    parser.add_argument('--dry-run', action='store_true', help='report the diff without writing')
    parser.add_argument('--force', action='store_true', help='republish even when the fingerprint matches')
    parser.add_argument('--skip-index', action='store_true', help='do not touch the Milvus vector index')
    args = parser.parse_args()
    plan = publish(dry_run=args.dry_run, force=args.force, skip_index=args.skip_index)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if plan.get('unchanged') and not plan.get('applied'):
        print('Metric catalog unchanged; nothing published.')
    elif plan.get('applied'):
        print(f"Published {plan['metric_count']} metrics; added={plan['added']} changed={plan['changed']}"
              f"{'; orphaned=' + str(plan['orphaned']) if plan['orphaned'] else ''}")


if __name__ == '__main__':
    main()
