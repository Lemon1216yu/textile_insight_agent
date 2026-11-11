import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from textile.provider_config import synchronize_index
if __name__=='__main__':
    print(f'Milvus index ready: {synchronize_index()} vectors')
