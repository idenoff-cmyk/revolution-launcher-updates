import json
import os
import time
from unittest.mock import Mock
import pytest
from app.diagnostics import collect_report, redact, analyze_ai
from app.storage import PROFILES
from app.api import LauncherAPI

def test_redaction_of_credentials_paths_and_contacts():
    text = r'C:\Users\Alice\game --accessToken SECRET1 authorization: Bearer SECRET2'
    text += '\n{"refresh_token": "SECRET3", "password":"SECRET4"} alice@example.org 127.0.0.1'
    result=redact(text)
    for secret in ["Alice","SECRET1","SECRET2","SECRET3","SECRET4","alice@example.org","127.0.0.1"]:
        assert secret not in result

def test_local_evidence_is_bounded_and_stale_crashes_are_ignored(tmp_path):
    root=tmp_path/"instance"
    (root/"logs").mkdir(parents=True)
    (root/"crash-reports").mkdir()
    stale=root/"crash-reports/old.txt"
    stale.write_text("OutOfMemoryError: Java heap space")
    os.utime(stale,(1,1))
    (root/"logs/latest.log").write_text("padding\n"*20000+"\nMissing mandatory dependencies: fabric_api\n")
    report=collect_report(root,tmp_path,PROFILES["modern"],6,[],since=time.time()-10)
    assert len(report["preview"])<=64000
    assert [x["id"] for x in report["findings"]]==["dependencies"]
    assert "fabric_api" in report["findings"][0]["evidence"]
    assert "crash-reports/old.txt" not in report["sources"]

def test_successful_log_does_not_invent_crash(tmp_path):
    (tmp_path/"logs").mkdir()
    (tmp_path/"logs/latest.log").write_text("Minecraft started successfully")
    report=collect_report(tmp_path,tmp_path,PROFILES["modern"],6,[])
    assert not report["findings"]

def test_no_ai_network_without_matching_report_and_explicit_consent(tmp_path,monkeypatch):
    api=LauncherAPI(tmp_path)
    api._collect_diagnostics("Missing mandatory dependencies")
    api.store.data.update(aiProvider="gemini",aiModel="test-model")
    spy=Mock(side_effect=AssertionError("No upload authorized"))
    monkeypatch.setattr("app.api.analyze_ai",spy)
    assert not api.command("ai",{})["ok"]
    assert not api.command("ai",{"consent":True,"reportId":"old"})["ok"]
    assert not api.command("ai",{"consent":True,"reportId":api.diagnostics["id"],"provider":"ollama","model":"test-model"})["ok"]
    assert not spy.called

def test_ai_receives_exact_preview_and_cannot_mutate_game(tmp_path,monkeypatch):
    api=LauncherAPI(tmp_path)
    api._collect_diagnostics("AccessDeniedException")
    preview=api.diagnostics["preview"]
    api.store.data.update(aiProvider="ollama",aiModel="local-model")
    def analyze(report,provider,model,key,cancel):
        assert report["preview"]==preview
        return "<script>doSomething()</script> Пояснення"
    monkeypatch.setattr("app.api.analyze_ai",analyze)
    result=api.command("ai",{"consent":True,"reportId":api.diagnostics["id"],"provider":"ollama","model":"local-model"})
    assert result["ok"]
    api.worker.join(5)
    assert api.diagnostics["ai"]["state"]=="ready"
    assert not list((api.store.instance_dir()/"mods").glob("*"))

def test_ai_config_and_secrets_stay_out_of_snapshot(tmp_path,monkeypatch):
    api=LauncherAPI(tmp_path)
    key=Mock()
    monkeypatch.setattr("app.api.secret_set",key)
    monkeypatch.setattr("app.api.threading.Thread",Mock())
    assert api.command("save_settings",{"aiProvider":"gemini","aiModel":"model","geminiKey":"PRIVATE"})["ok"]
    assert "PRIVATE" not in json.dumps(api.snapshot())
    key.assert_called_once_with("gemini","PRIVATE")

class Response:
    def __init__(self,data,status=200):self.data=data;self.status_code=status
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def iter_content(self,size):yield json.dumps(self.data).encode()

def test_ollama_cloud_alias_is_rejected_before_any_logs_are_sent(monkeypatch):
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            assert url.endswith("/api/show")
            assert kwargs["json"]=={"model":"my-alias"}
            return Response({"remote_host":"https://ollama.com","remote_model":"remote"})
    monkeypatch.setattr("requests.Session",Session)
    with pytest.raises(ValueError,match="не надіслано"):
        analyze_ai({"hasLogs":True,"preview":"PRIVATE LOGS"},"ollama","my-alias")

def test_gemini_http_contract_redaction_and_no_tool_execution(monkeypatch):
    class Session:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            assert url=="https://generativelanguage.googleapis.com/v1beta/models/test-model:generateContent"
            assert kwargs["headers"]=={"x-goog-api-key":"secret"}
            assert kwargs["allow_redirects"] is False
            assert kwargs["json"]["contents"][0]["parts"][0]["text"]=="visible report"
            assert "tools" not in kwargs["json"]
            return Response({"candidates":[{"content":{"parts":[{"text":"analysis","thought":True},{"text":"Перевір Java. access_token: SECRET"}]}}]})
    monkeypatch.setattr("requests.Session",Session)
    text=analyze_ai({"hasLogs":True,"preview":"visible report"},"gemini","test-model","secret")
    assert "SECRET" not in text and "analysis" not in text and "Перевір Java" in text
