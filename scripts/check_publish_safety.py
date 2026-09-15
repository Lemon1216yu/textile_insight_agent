r"""推送前安全检查：确认已跟踪文件里不含本地 .env 的真实密钥值。

用法：.\.venv\Scripts\python.exe scripts\check_publish_safety.py
退出码 1 = 有真实密钥出现在已跟踪文件里，禁止推送。
只输出命中的键名与「文件:行号」，绝不打印密钥值本身。

判定规则：键名含 PASSWORD / SECRET / TOKEN / API_KEY 才算密钥；
模型名、base_url、主机端口这类公开配置即使与 .env 相同也不算泄漏。
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / '.env'
SECRET_NAME = re.compile(r'PASSWORD|SECRET|TOKEN|API_KEY')
# 形态启发式：只提示、不判定失败
HEURISTICS = ((r'sk-[A-Za-z0-9]{16,}', 'sk- 形式密钥'),
              (r'-----BEGIN [A-Z ]*PRIVATE KEY-----', '私钥块'))


def git_grep(pattern, fixed=False):
    args = ['git', 'grep', '-n', '-I']
    args += ['-F'] if fixed else ['-E']
    args += [pattern, '--', '.']
    out = subprocess.run(args, capture_output=True, text=True, encoding='utf-8',
                         errors='ignore', cwd=str(ROOT))
    return [line for line in out.stdout.splitlines() if line.strip()]


def secret_values():
    """本地 .env + 进程环境里的真实密钥值。"""
    found = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key, value = key.strip(), value.strip().strip('"').strip("'")
                if SECRET_NAME.search(key) and len(value) >= 8:
                    found[key] = value
    for key in ('DASHSCOPE_API_KEY', 'DEEPSEEK_API_KEY', 'GITHUB_TOKEN'):
        value = os.environ.get(key, '')
        if len(value) >= 8:
            found[key] = value
    return found


def main():
    secrets = secret_values()
    print(f'待比对密钥键: {sorted(secrets) or "(无)"}')
    leaks = []
    for key, value in secrets.items():
        hits = git_grep(value, fixed=True)
        if hits:
            leaks.append((key, hits))
            print(f'  泄漏 {key}:')
            for hit in hits[:5]:
                print('    ', hit[:140])
        else:
            print(f'  未泄漏 {key}')
    print()
    for pattern, label in HEURISTICS:
        hits = git_grep(pattern)
        print(f'形态检查 {label}: {len(hits)} 处')
        for hit in hits[:5]:
            print('    ', hit[:140])
    print()
    if leaks:
        print('FAIL: 已跟踪文件含真实密钥，禁止推送')
        return 1
    print('OK: 未发现真实密钥，可以推送')
    return 0


if __name__ == '__main__':
    sys.exit(main())
