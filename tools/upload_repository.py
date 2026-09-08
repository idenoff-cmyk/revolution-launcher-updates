"""Commit reviewed launcher source through GitHub API; does not publish a modpack."""
from __future__ import annotations
import argparse
import base64
import json
import re
from pathlib import Path
from .publish_release import gh

EXCLUDED={".git",".venv","__pycache__",".pytest_cache","modpack","dist","build","secrets","cache","instances","logs","webview"}
TOP_LEVEL={"app","docs","licenses","tests","tools","ui",".github"}
ROOT_FILES={"README.md","LICENSE","CONTRIBUTING.md","SECURITY.md","requirements.txt","Revolution.spec","main.py","pytest.ini",".gitignore","community.json"}

def inventory(source):
    source=Path(source).resolve()
    files=[]
    for path in sorted(source.rglob("*")):
        rel=path.relative_to(source)
        if any(p in EXCLUDED for p in rel.parts) or not path.is_file():continue
        if rel.parts[0] not in TOP_LEVEL and str(rel) not in ROOT_FILES:continue
        if path.suffix.lower() in (".pem",".key",".pyc",".pyo"):raise ValueError("Приватний або зайвий файл у source: "+str(rel))
        if path.is_symlink() or not path.resolve().is_relative_to(source):raise ValueError("Посилання у source.")
        content=path.read_bytes()
        if re.search(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s*$",content):
            raise ValueError("Приватний ключ не можна завантажити.")
        files.append((rel.as_posix(),content))
    if not any(name=="main.py" for name,_ in files):raise ValueError("Не знайдено вихідний код лаунчера.")
    return files

def upload(source,repo):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo):raise ValueError("Очікується owner/repo.")
    files=inventory(source)
    ref=gh("api",f"repos/{repo}/git/ref/heads/main")
    previous=ref["object"]["sha"]
    commit=gh("api",f"repos/{repo}/git/commits/{previous}")
    entries=[]
    for name,data in files:
        entry={"path":name,"mode":"100644","type":"blob"}
        try:entry["content"]=data.decode("utf-8")
        except UnicodeDecodeError:
            blob=gh("api",f"repos/{repo}/git/blobs",body={"encoding":"base64","content":base64.b64encode(data).decode()})
            entry["sha"]=blob["sha"]
        entries.append(entry)
    tree=gh("api",f"repos/{repo}/git/trees",body={"base_tree":commit["tree"]["sha"],"tree":entries})
    new=gh("api",f"repos/{repo}/git/commits",body={"message":"Add Revolution Launcher 1.1.0 with signed pack updates and crash assistance",
        "tree":tree["sha"],"parents":[previous]})
    # A concurrent main update causes non-fast-forward rejection instead of data loss.
    gh("api","--method","PATCH",f"repos/{repo}/git/refs/heads/main",body={"sha":new["sha"],"force":False})
    return {"commit":new["sha"],"files":len(files),"url":f"https://github.com/{repo}/commit/{new['sha']}"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source",default=".");p.add_argument("--repo",required=True)
    p.add_argument("--preview",action="store_true")
    a=p.parse_args()
    if a.preview:
        files=inventory(a.source)
        print(json.dumps({"files":[n for n,_ in files],"bytes":sum(len(d) for _,d in files)},indent=2))
    else:print(json.dumps(upload(a.source,a.repo),indent=2))
if __name__=="__main__":main()
