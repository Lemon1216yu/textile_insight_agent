"""Shared, local-only model credentials for the API and worker on this host."""
import base64, hashlib, os, tempfile, threading
from cryptography.fernet import Fernet
from textile.settings import ROOT, LLM_KEY, LLM_URL, EMBED_URL, MODELS, EMBED_MODEL

STORE = ROOT / '.env.model-key'
LOCK = threading.Lock()
DASHSCOPE = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

def cipher():
    secret=os.environ['TEXTILE_SESSION_SECRET']
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(('model-key:'+secret).encode()).digest()))

def credentials():
    if STORE.is_file():
        key=cipher().decrypt(STORE.read_bytes()).decode()
        return key,key,DASHSCOPE,DASHSCOPE
    return LLM_KEY,os.getenv('DASHSCOPE_API_KEY',''),LLM_URL,EMBED_URL

def configured():
    return all(credentials()[:2])

def save(key):
    encrypted=cipher().encrypt(key.encode())
    fd,tmp=tempfile.mkstemp(dir=STORE.parent,prefix='.env.model-key.')
    try:
        with os.fdopen(fd,'wb') as f: f.write(encrypted)
        os.replace(tmp,STORE)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def probe(key):
    from openai import OpenAI
    with OpenAI(api_key=key,base_url=DASHSCOPE,timeout=20,max_retries=0) as client:
        try:
            vec=client.embeddings.create(model=EMBED_MODEL,input=['连接测试'],dimensions=256)
            if len(vec.data[0].embedding)!=256: raise ValueError()
        except Exception:
            raise ValueError('向量模型测试失败，请检查百炼密钥、地域和 Embedding 额度。') from None
        for model in MODELS:
            try:
                result=client.chat.completions.create(model=model,messages=[{'role':'user','content':'回复 OK'}],
                    max_tokens=48,**({'extra_body':{'enable_thinking':False}} if model.startswith('qwen') else {}))
                if result.choices[0].message.content:return model
            except Exception:pass
    raise ValueError('向量模型可用，但生成模型均未返回回答，请检查模型开通状态和额度。')
def synchronize_index():
    from scripts.publish_metrics import INDEX_FINGERPRINT_KEY,fingerprint
    from textile.registry import get_metrics,redis_client
    from textile.metric_catalog import definition_text,METRIC_DEFINITIONS
    from textile.retrieval import documents,build_index,index_count
    metrics=sorted(get_metrics(),key=lambda m:m['code'])
    revision=fingerprint([definition_text(m) for m in metrics])
    cache=redis_client()
    expected=len(documents())
    previous=cache.get('textile:index:published-text:v2')
    if previous is None and cache.get(INDEX_FINGERPRINT_KEY)==fingerprint([definition_text(m) for m in METRIC_DEFINITIONS]) and revision==fingerprint([definition_text(m) for m in sorted(METRIC_DEFINITIONS,key=lambda m:m['code'])]):
        previous=revision
    if previous!=revision or index_count()!=expected:
        build_index()
        if index_count()!=expected: raise RuntimeError('向量索引未就绪')
    cache.set('textile:index:published-text:v2',revision)
    return expected
