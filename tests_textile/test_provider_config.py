from fastapi.testclient import TestClient
from textile.app import app,auth
from textile import provider_config as cfg,models
from security import UserContext
import pytest

def test_admin_setup_and_rotation(tmp_path,monkeypatch):
    monkeypatch.setattr(cfg,'STORE',tmp_path/'sealed')
    monkeypatch.setattr(cfg,'LLM_KEY','')
    monkeypatch.delenv('DASHSCOPE_API_KEY',raising=False)
    monkeypatch.setattr(cfg,'synchronize_index',lambda:388)
    monkeypatch.setattr(cfg,'probe',lambda key:'demo-model')
    monkeypatch.setattr('textile.app.audit',lambda *a:None)
    with TestClient(app) as c:
        try:
            path='/api/admin/model-settings'
            assert c.get(path).status_code==401
            app.dependency_overrides[auth]=lambda:UserContext('s','sales','华东')
            assert c.post(path,json={'api_key':'test-credential-A'}).status_code==403
            app.dependency_overrides[auth]=lambda:UserContext('a','admin')
            assert not c.get(path).json()['configured']
            for key in ['test-credential-A','test-credential-B']:
                result=c.post(path,json={'api_key':key})
                assert result.status_code==200 and result.json()['vectors']==388
                assert key not in result.text+c.get(path).text and key.encode() not in cfg.STORE.read_bytes()
                assert models.llm().client.api_key==key and models.embedding_client().api_key==key
            def invalid(key):raise ValueError('连接失败')
            monkeypatch.setattr(cfg,'probe',invalid)
            assert c.post(path,json={'api_key':'test-invalid'}).status_code==400
            assert cfg.credentials()[0]=='test-credential-B'
        finally:app.dependency_overrides.pop(auth,None)
