"""还原演示账号密码为统一的 demo123。

背景：/api/password 要求新密码至少 10 个字符，而演示初始密码 demo123 只有 7 位，
因此改密后无法再通过 API 还原。本脚本用应用写账号直接更新 sys_users，
并递增 session_version 让旧会话立即失效（与改密接口行为一致）。

用法：
    .\.venv\Scripts\python.exe scripts\restore_demo_passwords.py [username ...]
不带参数时还原全部演示账号。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textile.app import hash_password, _conn  # noqa: E402

DEMO_PASSWORD = 'demo123'
DEMO_USERS = ['admin', 'executive', 'finance', 'sales_east', 'production', 'warehouse']


def restore(usernames):
    with _conn() as conn, conn.cursor() as cur:
        for name in usernames:
            cur.execute(
                'UPDATE sys_users SET password_hash=%s, session_version=session_version+1 WHERE username=%s',
                (hash_password(DEMO_PASSWORD), name))
            print(f'{name}: rows={cur.rowcount}')
        cur.execute('SELECT user_id,username,role,region,active,session_version FROM sys_users ORDER BY user_id')
        print('--- sys_users ---')
        for row in cur.fetchall():
            print(row)


if __name__ == '__main__':
    restore(sys.argv[1:] or DEMO_USERS)
