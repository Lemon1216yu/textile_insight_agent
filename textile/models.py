"""Reuse teaching LLMClient interface with independent chat/embedding providers.

多模型自动切换
--------------
百炼的免费额度是**按模型独立计量**的：某个模型 403 FreeTierOnly 时，其他模型往往仍有额度。
因此这里不再把模型写死成单个，而是按 `TEXTILE_LLM_MODELS`（逗号分隔，第一个为首选）依次尝试：

1. 额度耗尽/限流（403 FreeTierOnly、429）→ 把该模型标记为冷却并切换下一个；
2. 冷却状态写入 Redis（`textile:llm:exhausted:<model>`），API、worker、评测脚本共享，
   避免每个请求都重复撞同一堵墙；冷却到期后首选模型自动恢复尝试；
3. 冷却中的模型排在候选末尾兜底，全部新模型都失败时仍会再试一次；
4. 非额度类错误（网络、参数不兼容）不会误判为额度问题；厂商特有参数
   （qwen 的 enable_thinking、response_format）在不被支持时会去掉重试。

实际生效的模型记录在 `TextileLLM.last_model`，用量按模型分别落 Redis（textile:usage）。
"""
import os
import time
import contextvars
from functools import lru_cache

from openai import OpenAI

from llm_client import LLMClient
from textile.settings import LLM_KEY, LLM_URL, MODEL, MODELS, EMBED_MODEL, EMBED_URL

COOLDOWN_SECONDS = int(os.getenv('TEXTILE_LLM_COOLDOWN_SECONDS', '300'))
EXHAUSTED_KEY = 'textile:llm:exhausted:'

# 进程内冷却缓存：避免每次调用都往返 Redis。
_local_until = {}

# 每次调用实际使用的模型：用 contextvar 隔离，多线程/多任务并发评测时不会互相覆盖
# （实例属性 last_model 在并发下会被别的线程改写，不能作为逐例证据）。
_last_call = contextvars.ContextVar('llm_last_call', default=None)


def last_call():
    """当前上下文（线程/任务）最近一次调用实际使用的模型与是否发生降级。"""
    value = _last_call.get()
    return value or {'model': MODELS[0], 'fallback': False}


def _quota_error(exc):
    """是否为“值得换模型重试”的额度/限流错误。"""
    text = str(exc)
    return any(token in text for token in
               ('FreeTierOnly', 'Free quota exhausted', 'AllocationQuota',
                'insufficient_quota', ' 429', 'RateLimit', 'rate limit'))


def _in_cooldown(model):
    if _local_until.get(model, 0) > time.time():
        return True
    try:
        from textile.registry import redis_client
        if redis_client().exists(EXHAUSTED_KEY + model):
            _local_until[model] = time.time() + 30
            return True
    except Exception:
        pass
    return False


def _mark_exhausted(model, reason=''):
    _local_until[model] = time.time() + COOLDOWN_SECONDS
    try:
        from textile.registry import redis_client
        redis_client().setex(EXHAUSTED_KEY + model, COOLDOWN_SECONDS, (reason or '1')[:200])
    except Exception:
        pass


def clear_cooldown(model=None):
    """清除某个模型（或全部模型）的额度冷却，用于恢复后立即重试。"""
    targets = [model] if model else list(MODELS)
    for m in targets:
        _local_until.pop(m, None)
        try:
            from textile.registry import redis_client
            redis_client().delete(EXHAUSTED_KEY + m)
        except Exception:
            pass


def model_status():
    """当前模型链状态，供 /api/health 与运维观察。"""
    return [{'model': m, 'cooling': _in_cooldown(m)} for m in MODELS]


class TextileLLM(LLMClient):
    def __init__(self):
        self.client = OpenAI(api_key=LLM_KEY, base_url=LLM_URL, timeout=75, max_retries=1)
        self.models = MODELS
        self.model = MODELS[0]
        self.last_model = MODELS[0]
        self.last_fallback = False
        self.embedding_model = EMBED_MODEL
        self.temperature = 0.1
        self.max_tokens = 2400

    def _candidates(self):
        """可用的模型在前，冷却中的模型排在末尾兜底。"""
        fresh = [m for m in self.models if not _in_cooldown(m)]
        cooling = [m for m in self.models if m not in fresh]
        return fresh + cooling

    def _call(self, model, system_msg, prompt, json_mode, extra_body):
        kwargs = {'model': model,
                  'messages': [{'role': 'system', 'content': system_msg}, {'role': 'user', 'content': prompt}],
                  'temperature': self.temperature, 'max_tokens': self.max_tokens}
        if extra_body is not None:
            kwargs['extra_body'] = extra_body
        if json_mode:
            kwargs['response_format'] = {'type': 'json_object'}
        return self.client.chat.completions.create(**kwargs)

    def generate_text(self, system_msg: str, prompt: str, *, json_mode=False) -> str:
        errors = []
        for model in self._candidates():
            # 百炼 qwen3.5+ 默认开启思考模式，SQL/分析生成需显式关闭；其他厂商不支持该参数。
            extra_body = {'enable_thinking': False} if model.startswith('qwen') else None
            try:
                response = self._call(model, system_msg, prompt, json_mode, extra_body)
            except Exception as exc:
                if _quota_error(exc):
                    _mark_exhausted(model, str(exc))
                    errors.append(f'{model}: 额度耗尽或限流，已切换')
                    continue
                if extra_body is not None or json_mode:
                    # 厂商特有参数不被支持：去掉后重试同一模型一次。
                    try:
                        response = self._call(model, system_msg, prompt, False, None)
                    except Exception as exc2:
                        errors.append(f'{model}: {str(exc2)[:120]}')
                        continue
                else:
                    errors.append(f'{model}: {str(exc)[:120]}')
                    continue
            content = (response.choices[0].message.content or '').strip()
            if not content:
                errors.append(f'{model}: 返回空内容')
                continue
            self.model = self.last_model = model
            self.last_fallback = model != self.models[0]
            _last_call.set({'model': model, 'fallback': self.last_fallback})
            from textile.telemetry import record_usage
            record_usage(model, response.usage)
            return content
        raise RuntimeError('全部模型均不可用；' + '；'.join(errors))

    def generate_json(self, system_msg: str, prompt: str) -> str:
        return self.generate_text(system_msg, prompt, json_mode=True)


@lru_cache(maxsize=1)
def llm(): return TextileLLM()


@lru_cache(maxsize=1)
def embedding_client():
    return OpenAI(api_key=os.environ['DASHSCOPE_API_KEY'], base_url=EMBED_URL, timeout=45, max_retries=1)


def embed_batch(texts):
    result = embedding_client().embeddings.create(model=EMBED_MODEL, input=texts, dimensions=256)
    return [r.embedding for r in sorted(result.data, key=lambda r: r.index)]


@lru_cache(maxsize=128)
def embed(text): return embed_batch([text])[0]
