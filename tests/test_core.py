import hashlib
import json
import os
import socket
import struct
import threading
from pathlib import Path
import pytest
from app.storage import PROFILES, Store, atomic_json, validate_profile, offline_uuid
from app.sync import SyncEngine, safe_path, validate_manifest
from app.network import file_hash, download, Cancelled, ping_server, read_varint, read_exact, varint

def entry(name, contents=b"a", **extra):
    return {"path": "mods/" + name, "sha256": hashlib.sha256(contents).hexdigest(), "size": len(contents), "url": "https://cdn.example.org/" + name, **extra}

def manifest(files):
    return {"schemaVersion": 1, **{k:v for k,v in PROFILES["modern"].items() if k != "javaMajor"}, "files": files}

@pytest.mark.parametrize("name", ["../outside.jar", "mods/../../outside.jar", "mods/C:bad.jar", "mods/a\\b.jar", "mods/NUL.jar", "mods/bad. ", "/mods/x.jar", "saves/world.dat", "mods//foo.jar", "mods/./foo.jar"])
def test_path_rejects_escape_and_windows_special_files(tmp_path, name):
    with pytest.raises(ValueError): safe_path(tmp_path, name)

def test_incompatible_pair_rejected():
    with pytest.raises(ValueError): validate_profile("1.12.1", "neoforge", "21.1.250")
    assert validate_profile("1.21.1", "neoforge", "21.1.250") == 21

def test_manifest_rejects_duplicate_case(tmp_path):
    with pytest.raises(ValueError): validate_manifest(manifest([entry("A.jar"), entry("a.jar")]), PROFILES["modern"], tmp_path)

def test_offline_uuid_matches_java_known_value():
    assert offline_uuid("Notch") == "b50ad385829d3141a2167e7d7539ba7f"

def fake_downloader(blobs):
    def write(url, path, sha, **kwargs):
        data = blobs[url.rsplit("/", 1)[-1]]
        Path(path).write_bytes(data)
        if file_hash(path) != sha: raise ValueError("hash mismatch")
    return write

def test_sync_updates_managed_preserves_unmanaged_and_worlds(tmp_path, monkeypatch):
    (tmp_path / "mods").mkdir()
    (tmp_path / "saves").mkdir()
    (tmp_path / "mods/old.jar").write_bytes(b"old")
    (tmp_path / "mods/user.jar").write_bytes(b"mine")
    (tmp_path / "saves/world.dat").write_bytes(b"world")
    atomic_json(tmp_path / ".revolution/managed.json", manifest([entry("old.jar", b"old")]))
    monkeypatch.setattr("app.sync.download", fake_downloader({"new.jar": b"new"}))
    result = SyncEngine(tmp_path).sync(manifest([entry("new.jar", b"new")]), PROFILES["modern"])
    assert result["removed"] == 1
    assert not (tmp_path / "mods/old.jar").exists()
    assert (tmp_path / "mods/new.jar").read_bytes() == b"new"
    assert (tmp_path / "mods/user.jar").read_bytes() == b"mine"
    assert (tmp_path / "saves/world.dat").read_bytes() == b"world"

def test_corrupt_download_leaves_installed_pack_intact(tmp_path, monkeypatch):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods/a.jar").write_bytes(b"original")
    monkeypatch.setattr("app.sync.download", fake_downloader({"a.jar": b"corrupt"}))
    with pytest.raises(ValueError): SyncEngine(tmp_path).sync(manifest([entry("a.jar", b"expected")]), PROFILES["modern"])
    assert (tmp_path / "mods/a.jar").read_bytes() == b"original"

def test_commit_failure_rolls_back_files_and_ledger(tmp_path, monkeypatch):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods/a.jar").write_bytes(b"old")
    old = manifest([entry("a.jar", b"old")])
    atomic_json(tmp_path / ".revolution/managed.json", old)
    monkeypatch.setattr("app.sync.download", fake_downloader({"a.jar": b"new", "b.jar": b"b"}))
    real_replace = os.replace
    def replace(src, dst):
        if "stage" in Path(src).parts and Path(dst).name == "b.jar": raise OSError("disk full")
        return real_replace(src, dst)
    monkeypatch.setattr("app.sync.os.replace", replace)
    with pytest.raises(OSError): SyncEngine(tmp_path).sync(manifest([entry("a.jar", b"new"), entry("b.jar", b"b")]), PROFILES["modern"])
    assert (tmp_path / "mods/a.jar").read_bytes() == b"old"
    assert not (tmp_path / "mods/b.jar").exists()
    assert json.loads((tmp_path / ".revolution/managed.json").read_text()) == old

def test_recovery_after_interrupted_commit(tmp_path):
    (tmp_path / "mods").mkdir()
    (tmp_path / "mods/a.jar").write_bytes(b"new")
    (tmp_path / ".revolution/backup/mods").mkdir(parents=True)
    (tmp_path / ".revolution/backup/mods/a.jar").write_bytes(b"old")
    old = manifest([entry("a.jar", b"old")])
    atomic_json(tmp_path / ".revolution/transaction.json", {"old":old, "items":[{"path":"mods/a.jar", "existed":True}]})
    SyncEngine(tmp_path)
    assert (tmp_path / "mods/a.jar").read_bytes() == b"old"
    assert not (tmp_path / ".revolution/transaction.json").exists()

def test_cancellation_before_commit_preserves_files(tmp_path, monkeypatch):
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled): SyncEngine(tmp_path, cancel=cancel).sync(manifest([entry("a.jar")]), PROFILES["modern"])
    assert not (tmp_path / "mods/a.jar").exists()

def test_preserved_configuration_is_never_overwritten(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/client.toml").write_text("custom")
    f = {**entry("unused"), "path":"config/client.toml", "preserve":True}
    result = SyncEngine(tmp_path).sync(manifest([f]), PROFILES["modern"])
    assert result["preserved"] == 1
    assert (tmp_path / "config/client.toml").read_text() == "custom"

def test_actual_tcp_status_protocol(tmp_path):
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    port = server.getsockname()[1]
    def serve():
        with server, server.accept()[0] as conn:
            read_exact(conn, read_varint(conn))
            read_exact(conn, 2)
            body = json.dumps({"players":{"online":18,"max":250},"version":{"name":"NeoForge 1.21.1"}}).encode()
            packet = b"\x00" + varint(len(body)) + body
            conn.sendall(varint(len(packet)) + packet)
            assert read_exact(conn, 2) == b"\x09\x01"
            nonce = read_exact(conn, 8)
            conn.sendall(b"\x09\x01" + nonce)
    t = threading.Thread(target=serve)
    t.start()
    result = ping_server("127.0.0.1", port)
    t.join(2)
    assert result["online"] == 18 and result["max"] == 250 and result["state"] == "online"
    assert result["ping"] >= 0

def test_actual_http_stream_hash_and_size(tmp_path):
    from http.server import BaseHTTPRequestHandler, HTTPServer
    data = b"test mod" * 10000
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = HTTPServer(("127.0.0.1",0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/mod.jar"
        download(url, tmp_path / "mod.jar", hashlib.sha256(data).hexdigest(), size=len(data), local=True)
        assert (tmp_path / "mod.jar").read_bytes() == data
        with pytest.raises(ValueError): download(url, tmp_path / "bad.jar", "0"*64, local=True)
    finally:
        server.shutdown()
        server.server_close()

def test_settings_persist_and_instances_isolate(tmp_path):
    store = Store(tmp_path)
    store.data["ram"] = 8
    store.save()
    assert Store(tmp_path).data["ram"] == 8
    assert store.instance_dir({"id":"first"}) != store.instance_dir({"id":"second"})

def test_api_rejects_invalid_settings_and_guards_mutations(tmp_path):
    from app.api import LauncherAPI
    api = LauncherAPI(tmp_path)
    assert not api.command("save_settings", {"ram":100})["ok"]
    assert not api.command("save_settings", {"manifestUrl":"http://example.org/manifest.json"})["ok"]
    assert api.command("save_settings", {"ram":8})["ok"]
    api.job["busy"] = True
    assert not api.command("offline", {"name":"Tester"})["ok"]
    api.shutdown.set()

def test_api_exports_real_manifest_with_hashes(tmp_path):
    from app.api import LauncherAPI
    api = LauncherAPI(tmp_path / "data")
    root = api.store.instance_dir()
    (root / "mods").mkdir()
    (root / "mods/example.jar").write_bytes(b"a test artifact")
    output = tmp_path / "manifest.json"
    class Window:
        def create_file_dialog(self, *args, **kwargs): return [str(output)]
    api.window = Window()
    result = api.command("export_manifest", {"baseUrl":"https://cdn.example.org/pack"})
    assert result["ok"] and result["count"] == 1
    data = json.loads(output.read_text())
    assert data["files"][0]["sha256"] == hashlib.sha256(b"a test artifact").hexdigest()
    assert data["files"][0]["url"] == "https://cdn.example.org/pack/mods/example.jar"

def test_modrinth_mismatched_version_is_rejected(monkeypatch):
    from app.sync import resolve_source
    monkeypatch.setattr("app.sync.get_json", lambda url: {"project_id":"project", "game_versions":["1.20.1"], "loaders":["neoforge"], "files":[]})
    f = entry("example.jar")
    del f["url"]
    f["source"] = {"type":"modrinth", "projectId":"project", "versionId":"version"}
    with pytest.raises(ValueError): resolve_source(f, PROFILES["modern"])

def test_curseforge_restricted_file_is_not_bypassed(monkeypatch):
    from app.sync import resolve_source
    monkeypatch.setattr("app.sync.get_json", lambda *args, **kwargs: {"data":{"modId":42, "gameVersions":["1.21.1","NeoForge"], "downloadUrl":None}})
    f = entry("example.jar")
    del f["url"]
    f["source"] = {"type":"curseforge", "projectId":42, "versionId":12}
    with pytest.raises(ValueError): resolve_source(f, PROFILES["modern"], "test-key")

def test_processor_nonzero_exit_cannot_mark_installation_ready(tmp_path):
    import sys
    from app.installer import run_processor
    with (tmp_path / "processor.log").open("w") as log:
        with pytest.raises(ValueError):
            run_processor([sys.executable, "-c", "raise SystemExit(7)"], tmp_path, log, threading.Event())

def test_processor_cancellation_terminates_child(tmp_path):
    import sys
    from app.installer import run_processor
    cancel = threading.Event()
    cancel.set()
    with (tmp_path / "processor.log").open("w") as log:
        with pytest.raises(Cancelled):
            run_processor([sys.executable, "-c", "import time;time.sleep(60)"], tmp_path, log, cancel)
