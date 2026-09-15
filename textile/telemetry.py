"""Local structured usage events; no keys or prompt contents are logged."""
import contextvars,json,time
from textile.registry import redis_client
usage_context=contextvars.ContextVar('usage_owner',default='system')

def record_usage(model,usage):
    if not usage:return
    owner=usage_context.get()
    data={'user':owner,'model':model,'input_tokens':usage.prompt_tokens,'output_tokens':getattr(usage,'completion_tokens',0),
          'total_tokens':usage.total_tokens,'time':time.time()}
    try:
        r=redis_client();day=time.strftime('%Y-%m-%d')
        key=f'textile:tokens:{owner}:{day}'
        pipe=r.pipeline();pipe.incrby(key,usage.total_tokens);pipe.expire(key,86400*8)
        pipe.lpush('textile:usage',json.dumps(data));pipe.ltrim('textile:usage',0,4999);pipe.execute()
    except Exception:
        import logging
        logging.getLogger(__name__).warning('usage_record_unavailable')
