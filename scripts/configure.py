"""Generate only project-local credentials; never print API keys."""
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
env = root / '.env'
if env.exists():
    print('Existing .env preserved')
else:
    values = {
        'TEXTILE_MYSQL_ROOT_PASSWORD': secrets.token_urlsafe(24),
        'TEXTILE_DB_PASSWORD': secrets.token_urlsafe(24),
        'TEXTILE_MINIO_PASSWORD': secrets.token_urlsafe(24),
        'TEXTILE_SESSION_SECRET': secrets.token_urlsafe(32),
    }
    env.write_text('\n'.join(f'{k}={v}' for k,v in values.items())+'\n', encoding='utf-8')
    print('Created .env with generated local credentials; model keys use existing environment variables')
