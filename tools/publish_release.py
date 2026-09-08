"""Publish an already reviewed release using the user's authenticated GitHub CLI."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from app.network import file_hash
from app.releases import verify_release
from app.storage import PROFILES, read_json

def gh(*args, body=None, optional=False):
    cmd=["gh",*args]
    if body is not None:cmd+=["--input","-"]
    result=subprocess.run(cmd,input=json.dumps(body,ensure_ascii=False) if body is not None else None,
        capture_output=True,text=True,encoding="utf-8",timeout=300)
    if result.returncode:
        if optional and ("HTTP 404" in result.stderr or "Not Found" in result.stderr):return None
        raise RuntimeError(result.stderr[:1000])
    return json.loads(result.stdout) if result.stdout.strip() else None

def verify_folder(folder):
    folder=Path(folder).resolve()
    checksums=read_json(folder/"checksums.json")
    for rel,digest in checksums.items():
        target=(folder/rel).resolve()
        if not target.is_relative_to(folder) or not target.is_file() or file_hash(target)!=digest:
            raise ValueError("Реліз пошкоджений: "+rel)
    document=read_json(folder/"manifest.json")
    config=read_json(folder/"community.json")
    with tempfile.TemporaryDirectory() as tmp:
        manifest,_=verify_release(document,config["manifestPublicKey"],PROFILES["modern"],Path(tmp),config["manifestUrl"])
    for item in manifest["files"]:
        asset=folder/"assets"/item["url"].rsplit("/",1)[-1]
        if not asset.is_file() or file_hash(asset)!=item["sha256"]:raise ValueError("Відсутній перевірений asset.")
    return manifest,config

def find_release(repo,tag):
    release=gh("api",f"repos/{repo}/releases/tags/{tag}",optional=True)
    if release is not None:return release
    # GitHub's by-tag endpoint can omit drafts. Search owner-visible releases
    # before creating a new draft after an interrupted upload.
    for page in range(1,101):
        items=gh("api",f"repos/{repo}/releases?per_page=100&page={page}")
        matches=[item for item in items if item.get("tag_name")==tag]
        if len(matches)>1:raise ValueError("Знайдено кілька релізів із цим тегом; оберіть потрібну чернетку в GitHub.")
        if matches:return matches[0]
        if len(items)<100:return None
    raise ValueError("Не вдалося завершити пошук наявного релізу.")

def publish(folder,repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):raise ValueError("Очікується owner/repo.")
    folder=Path(folder).resolve()
    manifest,config=verify_folder(folder)
    revision=manifest["revision"];tag=f"pack-r{revision}"
    prefix=f"https://github.com/{repo}/releases/download/{tag}/"
    if any(not f["url"].startswith(prefix) for f in manifest["files"]):raise ValueError("Маніфест належить іншому репозиторію.")
    endpoint=f"repos/{repo}/contents/channel/stable.json"
    channel=gh("api",endpoint,optional=True)
    if channel:
        old=json.loads(base64.b64decode(channel["content"]))
        if old["payload"]["revision"]>=revision:raise ValueError("Канал уже має таку або новішу ревізію.")
    release=find_release(repo,tag)
    if release is None:
        release=gh("api",f"repos/{repo}/releases",body={"tag_name":tag,"target_commitish":"main","name":"Revolution Modded "+manifest["version"],
            "body":(folder/"release-notes.md").read_text(encoding="utf-8"),"draft":True,"make_latest":"false"})
    files=[*sorted((folder/"assets").glob("*")),folder/"manifest.json",folder/"audit.json",folder/"changes.json",folder/"community.json",folder/"checksums.json"]
    # A published, byte-identical release can finish an interrupted channel update.
    # Published assets are never overwritten.
    if release["draft"]:
        for i in range(0,len(files),12):
            result=subprocess.run(["gh","release","upload",tag,*[str(p) for p in files[i:i+12]],"--repo",repo,"--clobber"],
                capture_output=True,text=True,timeout=600)
            if result.returncode:raise RuntimeError("Завантаження не завершено. Реліз залишено чернеткою. "+result.stderr[:500])
    uploaded=[]
    for page in range(1,12):
        items=gh("api",f"repos/{repo}/releases/{release['id']}/assets?per_page=100&page={page}")
        uploaded+=items
        if len(items)<100:break
    indexed={a["name"]:a for a in uploaded}
    for path in files:
        remote=indexed.get(path.name,{})
        if remote.get("size")!=path.stat().st_size or remote.get("digest")!="sha256:"+file_hash(path):
            raise ValueError("GitHub не підтвердив SHA-256: "+path.name+". Канал не змінено.")
    if release["draft"]:
        gh("api","--method","PATCH",f"repos/{repo}/releases/{release['id']}",body={"draft":False,"make_latest":"false"})
    # The previous blob SHA prevents concurrent publishers from overwriting each other.
    change={"message":f"Publish Revolution pack revision {revision}","content":base64.b64encode((folder/"manifest.json").read_bytes()).decode(),"branch":"main"}
    if channel:change["sha"]=channel["sha"]
    gh("api","--method","PUT",endpoint,body=change)
    return config["manifestUrl"]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release",required=True);p.add_argument("--repo",required=True)
    a=p.parse_args();print(publish(a.release,a.repo))
if __name__=="__main__":main()
