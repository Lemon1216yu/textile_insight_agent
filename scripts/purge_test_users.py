"""按 user_id 备份并删除测试残留账号（sys_users）。

测试套件会创建 temp_/ops_/sales_ 临时账号；业务写账号 textile_app 无 DELETE 权限，
因此用运维账号清理，避免 sys_users 里堆积停用垃圾行。

用法：
    .\.venv\Scripts\python.exe scripts\purge_test_users.py 58 59 61
不带参数时只列出账号清单，不做任何修改。
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pymysql
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
sys.path.insert(0, str(ROOT))

from textile.settings import DB  # noqa: E402

ADMIN_DB = {**DB, 'user': 'root', 'password': os.environ.get('TEXTILE_MYSQL_ROOT_PASSWORD', '')}


def main(ids):
    with pymysql.connect(**ADMIN_DB) as conn, conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute('SELECT user_id,username,role,region,active FROM sys_users ORDER BY user_id')
        rows = cur.fetchall()
        if not ids:
            print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
            print('未指定 user_id，仅列出。')
            return
        targets = [r for r in rows if r['user_id'] in ids]
        missing = sorted(set(ids) - {r['user_id'] for r in targets})
        if missing:
            print(f'以下 user_id 不存在：{missing}')
        backup = ROOT / 'artifacts' / f'test-user-cleanup-{datetime.now():%Y%m%d-%H%M%S}.json'
        backup.write_text(json.dumps(targets, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        print(f'已备份 {len(targets)} 行 -> {backup}')
        if targets:
            cur.executemany('DELETE FROM sys_users WHERE user_id=%s', [(r['user_id'],) for r in targets])
            print(f'已删除 {cur.rowcount} 行')
        cur.execute('SELECT user_id,username,role,active FROM sys_users ORDER BY user_id')
        print('剩余账号：', json.dumps(cur.fetchall(), ensure_ascii=False, default=str))


if __name__ == '__main__':
    main([int(x) for x in sys.argv[1:]])
