"""Build an isolated candidate pack with required Modrinth dependencies; never publish."""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from urllib.parse import quote, urlencode
import requests
from app.network import get_json, checked_url, download, USER_AGENT
from app.storage import atomic_json
from app.sync import ALLOWED, safe_path
from .pack_audit import audit

BASE = "https://api.modrinth.com/v2/"

def compatible(version):
    return "1.21.1" in version.get("game_versions",[]) and "neoforge" in version.get("loaders",[])

def identify(pack):
    hashes = {}
    for path in sorted((Path(pack)/"mods").glob("*.jar")):
        safe_path(pack,path.relative_to(pack).as_posix())
        with path.open("rb") as f: hashes[hashlib.file_digest(f,"sha512").hexdigest()] = path.name
    with requests.post(BASE+"version_files",json={"hashes":list(hashes),"algorithm":"sha512"},
                       headers={"User-Agent":USER_AGENT},timeout=(10,30),allow_redirects=False) as response:
        response.raise_for_status()
        if len(response.content)>8*1024**2: raise ValueError("Завеликі метадані Modrinth.")
        versions = response.json()
    return {v["project_id"]:{"version":v,"file":hashes[h]} for h,v in versions.items() if h in hashes}

def resolve(version_id, installed, fetch=get_json):
    chosen={key:value["version"] for key,value in installed.items()}
    root=fetch(BASE+"version/"+quote(version_id,safe=""))
    chosen[root["project_id"]]=root
    pending=[root]; visited=set()
    while pending:
        version=pending.pop()
        if version["id"] in visited: continue
        if len(visited)>400: raise ValueError("Надто великий граф залежностей.")
        visited.add(version["id"])
        if not compatible(version): raise ValueError("Версія Modrinth несумісна з Minecraft 1.21.1 / NeoForge: "+version["id"])
        for dep in version.get("dependencies",[]):
            if dep["dependency_type"]!="required": continue
            pid, vid=dep.get("project_id"),dep.get("version_id")
            if vid:
                target=fetch(BASE+"version/"+quote(vid,safe=""))
                if pid and target["project_id"]!=pid: raise ValueError("Невідповідність ID залежності Modrinth.")
            elif pid:
                if pid in chosen: target=chosen[pid]
                else:
                    query=urlencode({"loaders":json.dumps(["neoforge"]),"game_versions":json.dumps(["1.21.1"]),"include_changelog":"false"})
                    candidates=fetch(BASE+"project/"+quote(pid,safe="")+"/version?"+query)
                    candidates=[v for v in candidates if compatible(v) and v.get("version_type")=="release" and v.get("project_id")==pid]
                    if not candidates: raise ValueError("Немає стабільної сумісної залежності: "+pid)
                    target=max(candidates,key=lambda v:v["date_published"])
            else: raise ValueError("Залежність потрібно додати вручну: "+str(dep.get("file_name")))
            pid=target["project_id"]
            if pid in chosen and chosen[pid]["id"]!=target["id"]:
                raise ValueError("Конфлікт зафіксованих версій залежності: "+pid+". Узгодь версію з іншими модами.")
            chosen[pid]=target;pending.append(target)
    # Inspect all selected versions, including existing mods that depend on the replaced one.
    for version in chosen.values():
        for dep in version.get("dependencies",[]):
            pid,vid=dep.get("project_id"),dep.get("version_id")
            target=chosen.get(pid)
            if not pid and vid: target=next((v for v in chosen.values() if v["id"]==vid),None)
            if dep["dependency_type"]=="incompatible" and target and (not vid or target["id"]==vid):
                raise ValueError("Несумісні моди Modrinth: "+version["id"]+" / "+target["id"])
            if dep["dependency_type"]=="required" and target and vid and target["id"]!=vid:
                raise ValueError("Зміна порушує зафіксовану залежність "+version["id"])
    return chosen

def candidate(pack,out,version_id,java):
    pack,out=Path(pack).resolve(),Path(out).resolve()
    if out.exists() or out.is_relative_to(pack): raise ValueError("Вибери нову папку за межами вихідної збірки.")
    installed=identify(pack)
    chosen=resolve(version_id,installed)
    out.mkdir(parents=True)
    replacements={data["file"] for pid,data in installed.items() if pid in chosen and chosen[pid]["id"]!=data["version"]["id"]}
    for directory in ALLOWED:
        for path in (pack/directory).rglob("*"):
            if not path.is_file(): continue
            rel=path.relative_to(pack).as_posix();safe_path(pack,rel)
            if directory=="mods" and path.name in replacements: continue
            target=safe_path(out,rel);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    added=[]
    for pid,version in chosen.items():
        if pid in installed and installed[pid]["version"]["id"]==version["id"]: continue
        files=[f for f in version["files"] if f["filename"].lower().endswith(".jar") and f.get("file_type") in (None,"unknown")]
        if not files: raise ValueError("Не знайдено основного JAR для "+version["id"])
        f=next((f for f in files if f.get("primary")),files[0])
        if "/" in f["filename"] or "\\" in f["filename"]: raise ValueError("Небезпечна назва файлу.")
        target=safe_path(out,"mods/"+f["filename"])
        if target.exists(): raise ValueError("Конфлікт імен файлів: "+f["filename"])
        target.parent.mkdir(parents=True,exist_ok=True)
        download(checked_url(f["url"]),target,f["hashes"]["sha512"],algorithm="sha512",size=f["size"])
        added.append({"projectId":pid,"versionId":version["id"],"file":f["filename"]})
    report=audit(out,java,out/".admin-cache")
    atomic_json(out/"candidate-audit.json",report)
    atomic_json(out/"modrinth-lock.json",added)
    if not report["passed"]: raise ValueError("Кандидат потребує виправлень. Дивись candidate-audit.json; початкова збірка збережена.")
    return {"added":added,"removed":sorted(replacements),"auditPassed":True,"candidate":str(out)}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("pack","out","version","java"):p.add_argument("--"+name,required=True)
    a=p.parse_args()
    print(json.dumps(candidate(a.pack,a.out,a.version,a.java),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
