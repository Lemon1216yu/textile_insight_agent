"""Explicit local settings. Model secrets stay in environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT=os.getenv('TEXTILE_ENV','dev')
if ENVIRONMENT not in {'dev','test','prod'}:raise ValueError('TEXTILE_ENV must be dev, test or prod')
if ENVIRONMENT!='dev' and not (ROOT/('.env.'+ENVIRONMENT)).exists():
    raise RuntimeError('Create .env.'+ENVIRONMENT+' with an isolated database before starting this environment')
load_dotenv(ROOT / ('.env.'+ENVIRONMENT))
load_dotenv(ROOT / '.env')
DB = dict(host=os.getenv('TEXTILE_DB_HOST', '127.0.0.1'),
          port=int(os.getenv('TEXTILE_DB_PORT', '3318')),
          user=os.getenv('TEXTILE_DB_USER', 'textile_reader'),
          password=os.getenv('TEXTILE_DB_PASSWORD', ''),
          database=os.getenv('TEXTILE_DB_NAME','textile_insight'), charset='utf8mb4', autocommit=True,
          connect_timeout=5, read_timeout=12, write_timeout=12)
# 应用账号：仅用于用户账户表（sys_users）的读与更新，不能执行 DDL。
APP_DB = {**DB, 'user': os.getenv('TEXTILE_APP_USER', 'textile_app')}
MILVUS_URI = os.getenv('MILVUS_URI', 'http://127.0.0.1:19530')
MODEL = os.getenv('TEXTILE_LLM_MODEL', 'qwen3.8-flash')
# 模型链：百炼免费额度按模型独立计量，首选模型额度耗尽时自动切换到后面的模型。
# 第一个是首选模型（也是评测基线所用模型），其余为备选。
MODELS = [m.strip() for m in os.getenv('TEXTILE_LLM_MODELS', MODEL).split(',') if m.strip()] or [MODEL]
LLM_URL = os.getenv('TEXTILE_LLM_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
LLM_KEY = os.getenv('TEXTILE_LLM_API_KEY') or os.getenv('DASHSCOPE_API_KEY') or ''
EMBED_URL = os.getenv('TEXTILE_EMBED_BASE_URL', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
EMBED_MODEL = os.getenv('TEXTILE_EMBED_MODEL', 'text-embedding-v3')
def _int_env(name, default, minimum=1):
    """配置解析容错：空串/非法值回落到默认值，并按最小值收敛。

    评审 F8：`TEXTILE_QUERY_TIMEOUT_MS=''` 会让 int() 抛 ValueError，`import textile.settings`
    直接失败；而阈值过小（如 1ms）在真实数据上会把正常查询全判成超时。
    """
    raw = (os.getenv(name) or '').strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(value, minimum)


COLLECTION = os.getenv('TEXTILE_MILVUS_COLLECTION','textile_schema_metrics_v2')
# A8 SQL 资源治理：语句超时由 MySQL 的 max_execution_time 强制（仅只读 SELECT），
# 慢查询阈值用于结构化日志与 /api/health 计数。
QUERY_TIMEOUT_MS = _int_env('TEXTILE_QUERY_TIMEOUT_MS', 8000, 100)
SLOW_QUERY_MS = _int_env('TEXTILE_SLOW_QUERY_MS', 200, 1)
DATA_PERIOD = '2026-03-01 至 2026-08-31'
