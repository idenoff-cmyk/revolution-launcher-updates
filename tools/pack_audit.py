"""Read mod metadata without running mod code. Maven itself evaluates version ranges."""
from __future__ import annotations
import collections
import io
import json
import subprocess
import tomllib
import zipfile
from pathlib import Path
from app.network import download, file_hash

DEPENDENCIES = [
    ("org/apache/maven/maven-artifact/3.8.5/maven-artifact-3.8.5.jar", "91172bc294d6eab02fc9f45f4ea01fd0e418962d128cf489abea7b6957d988ee"),
    ("org/apache/commons/commons-lang3/3.8.1/commons-lang3-3.8.1.jar", "dac807f65b07698ff39b1b07bfef3d87ae3fd46d91bbf8a2bc02b2a831616f68"),
]

def scan(blob, filename, depth=0):
    if depth > 5: raise ValueError("Надто багато вкладених JAR: " + filename)
    with zipfile.ZipFile(blob) as jar:
        if sum(x.file_size for x in jar.infolist()) > 1024**3:
            raise ValueError("Завеликий розпакований JAR: " + filename)
        names = set(jar.namelist())
        def read(name, limit=4*1024**2):
            if jar.getinfo(name).file_size > limit: raise ValueError("Завеликі метадані JAR.")
            return jar.read(name)
        raw = read("META-INF/MANIFEST.MF").decode("utf-8", "replace") if "META-INF/MANIFEST.MF" in names else ""
        raw = raw.replace("\r\n ", "").replace("\n ", "")
        attrs = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
        metadata, kind = {}, "library"
        for name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
            if name in names:
                metadata = tomllib.loads(read(name).decode("utf-8-sig"))
                kind = "neoforge" if "neoforge" in name else "forge"
                break
        if not metadata and "fabric.mod.json" in names and depth == 0:
            raise ValueError("Fabric-only мод не належить до цієї NeoForge-збірки: " + filename)
        for mod in metadata.get("mods", []):
            if mod.get("version") == "${file.jarVersion}":
                mod["version"] = attrs.get("Implementation-Version", "")
            if not mod.get("version") or "${" in str(mod["version"]):
                raise ValueError("Не визначено версію моду: " + filename)
        record = {"file": filename, "kind":kind, "metadata":metadata, "nested":[]}
        if "META-INF/jarjar/metadata.json" in names:
            for item in json.loads(read("META-INF/jarjar/metadata.json")).get("jars", []):
                record["nested"].append(scan(io.BytesIO(read(item["path"], 128*1024**2)), filename+"!/"+item["path"], depth+1))
        if depth == 0 and jar.testzip(): raise ValueError("Пошкоджений JAR: " + filename)
        return record

def inspect(pack):
    records = []
    for path in sorted((Path(pack)/"mods").glob("*.jar")):
        if path.is_symlink() or path.is_junction(): raise ValueError("Посилання серед модів.")
        record = scan(path, path.name)
        record.update(sha256=file_hash(path), size=path.stat().st_size)
        records.append(record)
    if not records: raise ValueError("Папка mods не містить модів.")
    return records

def dependency_checks(records, loader_version):
    flat = []
    def visit(record):
        flat.append(record)
        for child in record["nested"]: visit(child)
    for record in records: visit(record)
    versions, top_ids = collections.defaultdict(set), collections.defaultdict(list)
    for record in records:
        for mod in record["metadata"].get("mods", []): top_ids[mod["modId"]].append(record["file"])
    for record in flat:
        for mod in record["metadata"].get("mods", []): versions[mod["modId"]].add(str(mod["version"]))
    # FML 4.0.44 VersionSupportMatrix compatibility aliases for MC 1.21.1.
    versions.update(minecraft={"1.21.1","1.21"}, neoforge={loader_version,"21.0.166"}, java={"21"})
    checks, missing = [], []
    for record in flat:
        metadata = record["metadata"]
        if metadata.get("modLoader") == "javafml":
            checks.append({"file":record["file"], "owner":"javafml", "id":"javafml", "range":metadata.get("loaderVersion","[1,)"), "kind":"required", "versions":["4.0.44"]})
        for owner, deps in metadata.get("dependencies", {}).items():
            for dep in deps:
                if dep.get("side","BOTH").upper()=="SERVER": continue
                kind = dep.get("type", "required" if dep.get("mandatory",True) else "optional").lower()
                candidates = sorted(versions.get(dep["modId"], []))
                if not candidates:
                    if kind=="required": missing.append({"file":record["file"],"owner":owner,"dependency":dep})
                    continue
                checks.append({"file":record["file"],"owner":owner,"id":dep["modId"],"kind":kind,"range":dep.get("versionRange","[0,)"),"versions":candidates})
    return checks, missing, {key:value for key,value in top_ids.items() if len(value)>1}

def audit(pack, java, cache, loader_version="21.1.250"):
    if loader_version != "21.1.250":
        raise ValueError("Аудит FML перевірено для NeoForge 21.1.250. Онови матрицю аудиту перед зміною завантажувача.")
    records = inspect(pack)
    checks, missing, duplicates = dependency_checks(records, loader_version)
    cache = Path(cache);cache.mkdir(parents=True, exist_ok=True)
    jars = []
    for rel, digest in DEPENDENCIES:
        target = cache / Path(rel).name
        if not target.exists() or file_hash(target)!=digest:
            download("https://repo.maven.apache.org/maven2/"+rel, target, digest)
        jars.append(str(target.resolve()))
    lines = []
    for i,check in enumerate(checks):
        parts = [str(i),check["range"],*check["versions"]]
        if any("\n" in p or "\t" in p or "\r" in p for p in parts): raise ValueError("Некоректний діапазон залежності.")
        lines.append("\t".join(parts))
    result = subprocess.run([str(java), str(Path(__file__).with_name("RangeAudit.java")), *jars],
        input="\n".join(lines)+"\n", capture_output=True, text=True, timeout=90,
        creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    outcomes = dict(line.split("\t",1) for line in result.stdout.splitlines() if "\t" in line)
    issues = []
    for i,check in enumerate(checks):
        match = outcomes.get(str(i),"untested")
        if (check["kind"] in ("required","optional") and match!="true") or (check["kind"] in ("incompatible","discouraged") and match!="false"):
            issues.append({**check,"result":match})
    report = {"files":len(records),"checks":len(checks),"completed":len(outcomes),
              "missing":missing,"duplicates":duplicates,"issues":issues,"exitCode":result.returncode,
              "records":[{"file":r["file"],"sha256":r["sha256"],"size":r["size"],"mods":r["metadata"].get("mods",[]),"license":r["metadata"].get("license","unspecified")} for r in records]}
    report["passed"] = not (missing or duplicates or issues or result.returncode or len(outcomes)!=len(checks))
    return report
