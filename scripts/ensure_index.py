"""Rebuild the Milvus schema/metric index when it is missing or out of sync.

Uses the exact live vector count (count(*)), not `get_collection_stats()['row_count']`:
that statistic is approximate and roughly doubles right after an upsert, which made this
check unreliable (it could report "ready" for a collection that still needed rebuilding).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from textile.retrieval import build_index, documents, index_count, milvus
from textile.settings import COLLECTION

m = milvus()
expected = len(documents())
live = index_count() if m.has_collection(COLLECTION) else 0
if not m.has_collection(COLLECTION) or live != expected:
    print(build_index())
else:
    print(f'Milvus index ready: {live} vectors match {expected} documents')
