r"""校验 .env.example 与代码实际读取的配置键一致，防止模板随代码漂移。

用法：.\.venv\Scripts\python.exe scripts\check_env_contract.py
退出码 1 表示：模板缺少代码读取的键，或占位符键里出现了真实值。
只从系统环境变量读取的密钥（DASHSCOPE_API_KEY 等）不计入模板要求。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / '.env.example'
# 这些键在模板里必须是占位符，绝不能出现真实值
PLACEHOLDER_KEYS = ('TEXTILE_DB_PASSWORD', 'TEXTILE_MYSQL_ROOT_PASSWORD',
                    'TEXTILE_MINIO_PASSWORD', 'TEXTILE_SESSION_SECRET')
PLACEHOLDER = 'GENERATED_BY_CONFIGURE'
# 只从环境变量读取的密钥，不要求写进模板
EXTERNAL_KEYS = {'DASHSCOPE_API_KEY', 'DEEPSEEK_API_KEY'}
SKIP_DIRS = {'teaching_mvp', '.venv', 'node_modules', '__pycache__'}

ENV_PATTERNS = (r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]{3,})['\"]",
                r"os\.environ(?:\.get)?\[\s*['\"]([A-Z][A-Z0-9_]{3,})['\"]")


def template_pairs():
    pairs = {}
    for line in TEMPLATE.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            pairs[key.strip()] = value.strip()
    return pairs


def code_keys():
    keys = set()
    for py in ROOT.rglob('*.py'):
        if SKIP_DIRS & set(py.parts):
            continue
        text = py.read_text(encoding='utf-8', errors='ignore')
        for pattern in ENV_PATTERNS:
            keys |= set(re.findall(pattern, text))
    return {k for k in keys if k.startswith('TEXTILE_') or k == 'MILVUS_URI'}


def main():
    template = template_pairs()
    required = code_keys() - EXTERNAL_KEYS
    missing = sorted(required - set(template))
    bad = sorted(k for k in PLACEHOLDER_KEYS if template.get(k) != PLACEHOLDER)
    print(f'模板键 {len(template)} 个 / 代码读取 {len(required)} 个')
    print('缺少的键:', missing or '(无)')
    print('占位符异常:', bad or '(无)')
    if missing or bad:
        print('FAIL: .env.example 与代码配置契约不一致')
        return 1
    print('OK: 配置契约一致')
    return 0


if __name__ == '__main__':
    sys.exit(main())
