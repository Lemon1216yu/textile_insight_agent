"""Additive, idempotent platform migration. Existing metrics/accounts are preserved."""
import sys,os,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pymysql
from textile.settings import DB
from textile.metric_catalog import METRIC_DEFINITIONS

def main():
    with pymysql.connect(**{**DB,'user':'root','password':os.environ['TEXTILE_MYSQL_ROOT_PASSWORD']}) as conn,conn.cursor() as cur:
        cur.execute('''CREATE TABLE IF NOT EXISTS metric_registry (
          code VARCHAR(30) PRIMARY KEY, name VARCHAR(100) NOT NULL, status VARCHAR(20) NOT NULL,
          version VARCHAR(20) NOT NULL, definition JSON NOT NULL,
          updated_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6))''')
        for m in METRIC_DEFINITIONS:
            cur.execute('INSERT IGNORE INTO metric_registry(code,name,status,version,definition) VALUES(%s,%s,%s,%s,%s)',
                        (m['code'],m['name'],m['status'],m['version'],json.dumps(m,ensure_ascii=False)))
        cur.execute('''CREATE TABLE IF NOT EXISTS audit_events (
          event_id BIGINT AUTO_INCREMENT PRIMARY KEY, occurred_at TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP(6),
          username VARCHAR(50), action VARCHAR(50), detail JSON, INDEX idx_audit_user_time(username,occurred_at))''')
        cur.execute("SHOW COLUMNS FROM sys_users LIKE 'session_version'")
        if not cur.fetchone():cur.execute('ALTER TABLE sys_users ADD COLUMN session_version INT NOT NULL DEFAULT 1')
        cur.execute("GRANT SELECT ON textile_insight.metric_registry TO 'textile_app'@'%'")
        cur.execute("GRANT SELECT,INSERT ON textile_insight.audit_events TO 'textile_app'@'%'")
    from textile.registry import redis_client
    redis_client().delete('textile:metrics:published:v1')
    print('Platform migration complete; existing rows preserved.')
if __name__=='__main__':main()
