import copy
import io
import zipfile
import pytest
from tools.pack_audit import scan,dependency_checks
from tools.modrinth_add import resolve
from tools.release_tool import init_key
from tools.publish_release import verify_folder

def version(pid,vid,deps=()):
    return {"id":vid,"project_id":pid,"game_versions":["1.21.1"],"loaders":["neoforge"],
            "dependencies":list(deps),"version_type":"release","date_published":"2026-01-01"}
def required(pid,vid=None):return {"project_id":pid,"version_id":vid,"dependency_type":"required"}

def test_recursive_required_modrinth_dependencies_are_locked_and_cycles_end():
    records={"a":version("A","a",[required("B","b")]),"b":version("B","b",[required("A","a")])}
    result=resolve("a",{},lambda url:records[url.rsplit("/",1)[-1]])
    assert {k:v["id"] for k,v in result.items()}=={"A":"a","B":"b"}

def test_resolver_rejects_conflicting_existing_pin():
    records={"a":version("A","a",[required("B","b-new")]),"b-new":version("B","b-new")}
    with pytest.raises(ValueError,match="Конфлікт"):
        resolve("a",{"B":{"version":version("B","b-old"),"file":"b-old.jar"}},lambda url:records[url.rsplit("/",1)[-1]])

def test_new_version_cannot_break_other_existing_mod():
    installed={"A":{"version":version("A","old"),"file":"a.jar"},
               "B":{"version":version("B","b",[required("A","old")]),"file":"b.jar"}}
    with pytest.raises(ValueError,match="порушує"):
        resolve("new",installed,lambda url:version("A","new"))

def test_missing_dependency_and_duplicate_ids_are_actionable():
    data={"file":"a.jar","nested":[],"metadata":{"mods":[{"modId":"a","version":"1"}],"dependencies":{"a":[{"modId":"missing","type":"required"}]}}}
    checks,missing,duplicates=dependency_checks([data,copy.deepcopy(data)],"21.1.250")
    assert missing[0]["dependency"]["modId"]=="missing"
    assert "a" in duplicates

def test_top_level_fabric_only_mod_rejected_but_nested_library_is_allowed():
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,"w") as jar:jar.writestr("fabric.mod.json",'{"id":"library","version":"1"}')
    with pytest.raises(ValueError,match="Fabric-only"):scan(io.BytesIO(buffer.getvalue()),"library.jar")
    assert scan(io.BytesIO(buffer.getvalue()),"parent.jar!/library.jar",depth=1)["kind"]=="library"

def test_signing_key_never_overwrites_existing_private_key(tmp_path):
    path=tmp_path/"key.pem"
    public=init_key(path)
    original=path.read_bytes()
    assert len(public)==44
    with pytest.raises(FileExistsError):init_key(path)
    assert path.read_bytes()==original

def test_resume_finds_draft_missing_from_tag_endpoint(monkeypatch):
    from tools import publish_release as publisher
    calls=[]
    def fake(*args,**kwargs):
        calls.append(args[1])
        if "/tags/" in args[1]:return None
        return [{"id":123,"tag_name":"pack-r1","draft":True}]
    monkeypatch.setattr(publisher,"gh",fake)
    assert publisher.find_release("owner/repo","pack-r1")["id"]==123
    assert len(calls)==2

def test_published_release_lookup_does_not_search_or_modify(monkeypatch):
    from tools import publish_release as publisher
    def fake(*args,**kwargs):
        assert args==("api","repos/owner/repo/releases/tags/pack-r1")
        return {"id":123,"draft":False,"tag_name":"pack-r1"}
    monkeypatch.setattr(publisher,"gh",fake)
    assert publisher.find_release("owner/repo","pack-r1")["draft"] is False
