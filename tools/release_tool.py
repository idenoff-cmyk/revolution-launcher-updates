"""Run from source root: python -m tools.release_tool --help."""
from __future__ import annotations
import argparse
import base64
import json
import re
import shutil
import tempfile
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.network import file_hash
from app.storage import atomic_json, read_json, PROFILES
from app.sync import ALLOWED, safe_path, validate_manifest
from app.releases import canonical_bytes
from .pack_audit import audit

def init_key(destination):
    path = Path(destination).resolve()
    source = Path(__file__).resolve().parents[1]
    if path.is_relative_to(source): raise ValueError("Приватний ключ зберігай за межами вихідного коду/репозиторію.")
    path.parent.mkdir(parents=True,exist_ok=True)
    key = Ed25519PrivateKey.generate()
    with path.open("xb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    return base64.b64encode(key.public_key().public_bytes_raw()).decode()

def build(pack, destination, key_path, revision, version, repo, java, notes=(), previous=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",repo): raise ValueError("Очікується owner/repo.")
    if type(revision) is not int or revision<1 or not 1<=len(version)<=80: raise ValueError("Некоректна версія.")
    if len(notes)>100 or any(not isinstance(n,str) or len(n)>2000 for n in notes): raise ValueError("Завеликі нотатки релізу.")
    pack, dest = Path(pack).resolve(), Path(destination).resolve()
    if dest.exists() and any(dest.iterdir()): raise ValueError("Вибери нову порожню папку релізу.")
    if dest.is_relative_to(pack): raise ValueError("Реліз повинен бути за межами папки модпаку.")
    key = serialization.load_pem_private_key(Path(key_path).read_bytes(),password=None)
    if not isinstance(key,Ed25519PrivateKey): raise ValueError("Потрібен приватний ключ Ed25519.")
    old = read_json(Path(previous),{}) if previous else {}
    old = old.get("payload",old)
    if old.get("revision",0)>=revision: raise ValueError("Ревізія має зростати; для відкату теж потрібен новий номер.")
    with tempfile.TemporaryDirectory(prefix="revolution-audit-") as temp:
        report = audit(pack,java,Path(temp)/"maven")
    if not report["passed"]:
        dest.mkdir(parents=True,exist_ok=True)
        atomic_json(dest/"audit-failed.json",report)
        raise ValueError("Аудит залежностей не пройдено. Дивись audit-failed.json. Реліз не підписано.")
    dest.mkdir(parents=True,exist_ok=True)
    assets = dest/"assets";assets.mkdir()
    indexed = {record["file"]:record for record in report["records"]}
    files = []
    for directory in sorted(ALLOWED):
        for path in sorted((pack/directory).rglob("*")):
            if not path.is_file(): continue
            rel = path.relative_to(pack).as_posix()
            safe_path(pack,rel)
            if path.stat().st_size>2*1024**3: raise ValueError("Файл перевищує 2 ГіБ.")
            sha = file_hash(path)
            asset = sha + (".jar" if path.suffix.lower()==".jar" else ".bin")
            copied = assets/asset
            if not copied.exists(): shutil.copyfile(path,copied)
            if file_hash(copied)!=sha: raise ValueError("Вхідні файли змінилися під час підготовки.")
            record = indexed.get(path.name,{}) if directory=="mods" else {}
            if record and record["sha256"]!=sha: raise ValueError("Мод змінився після аудиту.")
            mods = record.get("mods",[])
            name = mods[0].get("displayName",path.stem) if mods else path.stem
            files.append({"path":rel,"name":name,"sha256":sha,"size":path.stat().st_size,
                          "url":f"https://github.com/{repo}/releases/download/pack-r{revision}/{asset}"})
    payload = {"schemaVersion":1,"packId":"revolution","name":"Revolution Modded","revision":revision,"version":version,
               **{k:v for k,v in PROFILES["modern"].items() if k!="javaMajor"},"notes":list(notes),"files":files}
    validate_manifest(payload,PROFILES["modern"],pack)
    envelope = {"payload":payload,"signature":base64.b64encode(key.sign(canonical_bytes(payload))).decode()}
    atomic_json(dest/"manifest.json",envelope)
    pub = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    atomic_json(dest/"community.json",{"manifestUrl":f"https://raw.githubusercontent.com/{repo}/main/channel/stable.json",
        "manifestPublicKey":pub,"microsoftClientId":"6a13d8b7-ae7a-4772-bf45-47051eb16dee"})
    atomic_json(dest/"audit.json",report)
    before = {f["path"]:f["sha256"] for f in old.get("files",[])}
    after = {f["path"]:f["sha256"] for f in files}
    changes = {"added":sorted(after.keys()-before.keys()),"removed":sorted(before.keys()-after.keys()),
               "changed":sorted(p for p in before.keys() & after.keys() if before[p]!=after[p])}
    atomic_json(dest/"changes.json",changes)
    text = [f"Revolution Modded {version}", "", f"Minecraft 1.21.1 / NeoForge 21.1.250 / revision {revision}",
            f"Files: {len(files)}. Dependency rules: {report['checks']}.", "", *notes, ""]
    for label, paths in changes.items():
        text += [f"{label} ({len(paths)})", *["- "+p for p in paths], ""]
    (dest/"release-notes.md").write_text("\n".join(text),encoding="utf-8")
    hashes = {p.relative_to(dest).as_posix():file_hash(p) for p in dest.rglob("*") if p.is_file()}
    atomic_json(dest/"checksums.json",hashes)
    return {"revision":revision,"files":len(files),"auditRules":report["checks"],"publicKey":pub,"destination":str(dest)}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest="command",required=True)
    key=commands.add_parser("init-key");key.add_argument("--private",required=True)
    pack=commands.add_parser("build")
    for name in ["pack","out","private","version","repo","java"]: pack.add_argument("--"+name,required=True)
    pack.add_argument("--revision",type=int,required=True)
    pack.add_argument("--notes",help="UTF-8 file, one release note per line")
    pack.add_argument("--previous",help="Previous signed manifest; checks increasing revision and reports changes")
    args=parser.parse_args()
    if args.command=="init-key": print(init_key(args.private))
    else:
        notes=Path(args.notes).read_text(encoding="utf-8").splitlines() if args.notes else []
        print(json.dumps(build(args.pack,args.out,args.private,args.revision,args.version,args.repo,args.java,notes,args.previous),ensure_ascii=False,indent=2))
if __name__=="__main__": main()
