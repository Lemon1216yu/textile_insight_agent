"""产物写入工具：覆盖前自动存档上一次结果，避免基线证据被静默覆盖。

为什么需要它：本项目多次出现"重跑后旧产物被覆盖、文档却仍指向该路径"的事故
（一次 52/52 评测产物、一次 8/8 抽样产物都这样丢过）。归档命名带毫秒，避免同一秒
内两次覆盖互相顶掉（评审发现的缺陷：秒级时间戳会静默丢基线）。
"""
import json
import time
from pathlib import Path


def write_json(data, path):
    """写 JSON；目标已存在时先另存为 `<name>-prev-<YYYYmmdd-HHMMSS-mmm>.json`。

    返回存档文件路径（Path），没有旧文件时返回 None。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)   # 支持多级目录（原实现只支持单级）
    archived = None
    if path.exists():
        stamp = time.strftime('%Y%m%d-%H%M%S') + f"-{int(time.time() * 1000) % 1000:03d}"
        archived = path.with_name(f'{path.stem}-prev-{stamp}.json')
        suffix = 1
        while archived.exists():
            archived = path.with_name(f'{path.stem}-prev-{stamp}-{suffix}.json')
            suffix += 1
        archived.write_bytes(path.read_bytes())
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return archived
