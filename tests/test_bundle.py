import hashlib
import json
import threading
import pytest
from app.api import LauncherAPI
from app.network import Cancelled
from app.storage import PROFILES, atomic_json
from app.sync import SyncEngine, validate_manifest

def pack(tmp_path, payload=b'jar-content'):
    bundle=tmp_path/'bundle'
    (bundle/'mods').mkdir(parents=True)
    (bundle/'mods/a.jar').write_bytes(payload)
    data={'schemaVersion':1,'name':'Revolution', 'version':'test', **{k:v for k,v in PROFILES['modern'].items() if k!='javaMajor'}, 'files':[{'path':'mods/a.jar','name':'Test Mod','size':len(payload),'sha256':hashlib.sha256(payload).hexdigest(),'source':{'type':'bundle'}}]}
    atomic_json(bundle/'manifest.json',data)
    return bundle,data

def test_remote_manifest_cannot_request_bundled_files(tmp_path):
    bundle,data=pack(tmp_path)
    with pytest.raises(ValueError, match='Локальне джерело'):
        validate_manifest(data, PROFILES['modern'],tmp_path/'instance')
    validate_manifest(data,PROFILES['modern'],bundle,allow_bundle=True)

def test_offline_bundle_install_repair_and_instance_isolation(tmp_path,monkeypatch):
    bundle,data=pack(tmp_path)
    monkeypatch.setattr('app.sync.download',lambda *a,**kw: pytest.fail('Bundle contacted network'))
    api=LauncherAPI(tmp_path/'data',bundle_dir=bundle)
    assert api.snapshot()['bundle']=={'available':True,'total':1}
    api._job_sync()
    root=api.store.instance_dir()
    assert (root/'mods/a.jar').read_bytes()==b'jar-content'
    assert api.snapshot()['integrity']['state']=='healthy'
    assert api.snapshot()['mods'][0]['name']=='Test Mod'
    (root/'mods/a.jar').write_bytes(b'damaged')
    (root/'mods/user.jar').write_bytes(b'user')
    (root/'saves').mkdir()
    (root/'saves/world.dat').write_bytes(b'world')
    api._job_check()
    assert api.integrity['state']=='updates'
    api._job_sync()
    assert (root/'mods/a.jar').read_bytes()==b'jar-content'
    assert (root/'mods/user.jar').read_bytes()==b'user'
    assert (root/'saves/world.dat').read_bytes()==b'world'
    api.command('create_instance',{'name':'Other','profile':'modern'})
    assert not api.snapshot()['bundle']['available']
    assert not list((api.store.instance_dir()/'mods').glob('*.jar'))

def test_corrupted_bundle_does_not_replace_existing_mod(tmp_path):
    bundle,data=pack(tmp_path)
    root=tmp_path/'instance'
    (root/'mods').mkdir(parents=True)
    (root/'mods/a.jar').write_bytes(b'existing')
    (bundle/'mods/a.jar').write_bytes(b'wrong-bytes')
    with pytest.raises(ValueError):
        SyncEngine(root,bundle_root=bundle).sync(data,PROFILES['modern'])
    assert (root/'mods/a.jar').read_bytes()==b'existing'

def test_bundled_copy_cancellation_does_not_commit(tmp_path):
    bundle,data=pack(tmp_path,b'x'*(3*1024**2))
    cancel=threading.Event()
    def progress(**kw):
        if kw.get('phase')=='download': cancel.set()
    root=tmp_path/'instance'
    with pytest.raises(Cancelled):
        SyncEngine(root,progress,cancel,bundle_root=bundle).sync(data,PROFILES['modern'])
    assert not (root/'mods/a.jar').exists()

def test_server_manifest_overrides_local_bundle(tmp_path,monkeypatch):
    bundle,data=pack(tmp_path)
    api=LauncherAPI(tmp_path/'data',bundle_dir=bundle)
    api.store.data['manifestUrl']='https://example.org/manifest.json'
    assert not api.snapshot()['bundle']['available']
    remote={**data,'files':[]}
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from app.releases import canonical_bytes
    import base64
    key=Ed25519PrivateKey.generate()
    api.store.data['manifestPublicKey']=base64.b64encode(key.public_key().public_bytes_raw()).decode()
    remote.update(packId='revolution',revision=1)
    envelope={'payload':remote,'signature':base64.b64encode(key.sign(canonical_bytes(remote))).decode()}
    monkeypatch.setattr('app.api.get_json',lambda url:envelope)
    assert api._manifest()['files']==[]

def test_bundle_path_traversal_rejected(tmp_path):
    bundle,data=pack(tmp_path)
    data['files'][0]['path']='mods/../../secret.jar'
    with pytest.raises(ValueError):
        SyncEngine(tmp_path/'instance',bundle_root=bundle).sync(data,PROFILES['modern'])

def test_bundle_rejects_ambiguous_url(tmp_path):
    bundle,data=pack(tmp_path)
    data['files'][0]['url']='https://example.org/a.jar'
    with pytest.raises(ValueError):
        validate_manifest(data,PROFILES['modern'],bundle,allow_bundle=True)
