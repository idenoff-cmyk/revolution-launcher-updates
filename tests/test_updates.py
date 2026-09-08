import base64
import copy
import hashlib
import json
import threading
from pathlib import Path
from unittest.mock import Mock
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.api import LauncherAPI
from app.cache import ObjectCache
from app.storage import PROFILES, Store, atomic_json
from app.releases import canonical_bytes, verify_release
from test_bundle import pack
from test_core import entry, manifest, fake_downloader

def signed(payload, key):
    return {"payload":payload, "signature":base64.b64encode(key.sign(canonical_bytes(payload))).decode()}

def channel(tmp_path, monkeypatch):
    bundle, _ = pack(tmp_path)
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    api = LauncherAPI(tmp_path/"data", bundle_dir=bundle,
        defaults={"manifestUrl":"https://example.org/manifest.json", "manifestPublicKey":pub})
    payload = {**manifest([entry("b.jar", b"new")]), "packId":"revolution", "revision":1, "version":"2026.1", "notes":["Новий мод"]}
    monkeypatch.setattr("app.api.get_json", lambda url: signed(payload, key))
    monkeypatch.setattr("app.sync.download", fake_downloader({"b.jar":b"new"}))
    return api, payload, key, pub

def test_signed_release_installs_then_rejects_replay_and_same_revision_mutation(tmp_path, monkeypatch):
    api, payload, key, pub = channel(tmp_path, monkeypatch)
    api._job_sync()
    root = api.store.instance_dir()
    assert (root/"mods/b.jar").read_bytes() == b"new"
    assert not (root/"mods/a.jar").exists()
    assert api.updates["signed"]
    payload["revision"] = 2
    api._job_sync()
    payload["revision"] = 1
    with pytest.raises(ValueError, match="стару"): api._job_sync()
    payload["revision"] = 2
    payload["version"] = "mutated"
    with pytest.raises(ValueError, match="стару"): api._job_sync()
    assert (root/"mods/b.jar").read_bytes() == b"new"

def test_tampered_signature_never_changes_pack(tmp_path, monkeypatch):
    api, payload, key, pub = channel(tmp_path, monkeypatch)
    api._job_sync()
    document = signed(payload, key)
    document["payload"] = {**payload, "files":[]}
    monkeypatch.setattr("app.api.get_json", lambda url: document)
    with pytest.raises(ValueError, match="Підпис"): api._job_sync()
    assert len(api.mods) == 1
    assert (api.store.instance_dir()/"mods/b.jar").exists()

@pytest.mark.parametrize("mutation", [
    {"minecraft":"1.12.1"}, {"loader":"forge"}, {"revision":True}, {"packId":"other"},
    {"notes":"bad"}, {"version":None}, {"files":[entry("../escape.jar")]},
])
def test_signed_invalid_payload_rejected(tmp_path, monkeypatch, mutation):
    api,payload,key,pub = channel(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        verify_release(signed({**payload, **mutation},key),pub,PROFILES["modern"],api.store.instance_dir(),"https://example.org")

def test_background_installs_bundle_and_defers_while_game_or_worker_active(tmp_path):
    bundle,_=pack(tmp_path)
    api=LauncherAPI(tmp_path/"data", bundle_dir=bundle)
    api.job["busy"]=True
    assert not api._try_maintenance()
    api.job["busy"]=False
    api.process=Mock()
    api.process.poll.return_value=None
    assert not api._try_maintenance()
    api.process=None
    assert api._try_maintenance()
    api.worker.join(timeout=5)
    assert not api.job["busy"] and not api.job["error"]
    assert api.integrity["state"]=="healthy"
    assert (api.store.instance_dir()/"mods/a.jar").exists()
    api.command("create_instance", {"name":"Custom", "profile":"modern"})
    assert not api._try_maintenance()
    assert not list((api.store.instance_dir()/"mods").glob("*.jar"))

def test_loader_transition_and_no_offline_bundle_downgrade(tmp_path, monkeypatch):
    api,payload,key,pub=channel(tmp_path,monkeypatch)
    payload["loaderVersion"]="21.1.251"
    api._job_sync()
    assert api.store.profile()["loaderVersion"]=="21.1.251"
    assert Store(api.store.root).profile()["loaderVersion"]=="21.1.251"
    api.store.data["manifestUrl"]=""
    api._job_sync()
    assert not (api.store.instance_dir()/"mods/a.jar").exists()
    assert (api.store.instance_dir()/"mods/b.jar").exists()

def test_network_failure_preserves_installed_release(tmp_path,monkeypatch):
    api,payload,key,pub=channel(tmp_path,monkeypatch)
    api._job_sync()
    monkeypatch.setattr("app.api.get_json",Mock(side_effect=ConnectionError("offline")))
    with pytest.raises(ConnectionError): api._job_sync()
    assert (api.store.instance_dir()/"mods/b.jar").exists()
    assert not (api.store.instance_dir()/"mods/a.jar").exists()

def test_cache_detects_corruption_and_copies_isolated_bytes(tmp_path):
    cache=ObjectCache(tmp_path/"cache/objects")
    f=entry("a.jar",b"original")
    src=tmp_path/"source";src.write_bytes(b"original")
    cache.remember(f,src)
    dest=tmp_path/"installed"
    assert cache.restore(f,dest)
    dest.write_bytes(b"modified")
    assert cache.path(f["sha256"]).read_bytes()==b"original"
    cache.path(f["sha256"]).write_bytes(b"corrupt")
    assert not cache.restore(f,dest)
    assert not cache.path(f["sha256"]).exists()

def test_cache_repairs_without_redownload(tmp_path,monkeypatch):
    api,payload,key,pub=channel(tmp_path,monkeypatch)
    api._job_sync()
    (api.store.instance_dir()/"mods/b.jar").write_bytes(b"corrupt")
    monkeypatch.setattr("app.sync.download",Mock(side_effect=AssertionError("Network download")))
    api._job_sync()
    assert (api.store.instance_dir()/"mods/b.jar").read_bytes()==b"new"

def test_public_client_id_defaults_and_saved_preferences_migrate(tmp_path):
    store=Store(tmp_path)
    store.data.update(microsoftClientId="",ram=8);store.save()
    upgraded=Store(tmp_path,{"manifestPublicKey":"public", "manifestUrl":"https://example.org/m.json"})
    assert upgraded.data["microsoftClientId"]=="6a13d8b7-ae7a-4772-bf45-47051eb16dee"
    assert upgraded.data["ram"]==8
    assert upgraded.data["manifestUrl"]=="https://example.org/m.json"
