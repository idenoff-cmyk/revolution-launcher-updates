from __future__ import annotations
import os
import re
import shutil
from pathlib import Path, PurePosixPath
from .network import get_json, checked_url, download, file_hash, Cancelled
from .storage import atomic_json, read_json, validate_profile

ALLOWED = {"mods", "config", "defaultconfigs", "resourcepacks", "shaderpacks", "scripts", "kubejs"}
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\.|$)", re.I)

def safe_path(root, name):
    if not isinstance(name, str) or "\\" in name or ":" in name or len(name) > 240:
        raise ValueError("Небезпечний шлях у маніфесті.")
    parts = name.split("/")
    if len(parts) < 2 or parts[0] not in ALLOWED or any(p in ("", ".", "..") or p.endswith((" ", ".")) or RESERVED.match(p) or re.search(r'[<>"|?*\x00-\x1f]', p) for p in parts):
        raise ValueError("Маніфест містить заборонений шлях: " + name)
    base = Path(root).resolve()
    current = base
    for part in parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
            raise ValueError("Посилання та junction у папках збірки не підтримуються.")
    if not current.resolve().is_relative_to(base):
        raise ValueError("Шлях виходить за межі інстансу.")
    return current

def validate_manifest(data, profile, root, *, allow_bundle=False):
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        raise ValueError("Потрібен маніфест schemaVersion: 1.")
    validate_profile(data.get("minecraft", ""), data.get("loader", ""), data.get("loaderVersion", ""))
    for key in ("minecraft", "loader", "loaderVersion"):
        if data[key] != profile[key]:
            raise ValueError("Версії маніфесту відрізняються від профілю. Виберіть відповідну збірку.")
    files = data.get("files")
    if not isinstance(files, list) or len(files) > 10000:
        raise ValueError("Некоректний список файлів.")
    seen = set()
    for f in files:
        safe_path(root, f.get("path"))
        name = f["path"].casefold()
        if name in seen or any(name.startswith(x + "/") or x.startswith(name + "/") for x in seen):
            raise ValueError("Конфлікт шляхів у маніфесті.")
        seen.add(name)
        if not re.fullmatch(r"[a-fA-F0-9]{64}", f.get("sha256", "")):
            raise ValueError("Кожен файл має містити SHA-256.")
        if "size" in f and (type(f["size"]) is not int or not 0 <= f["size"] <= 2 * 1024**3):
            raise ValueError("Некоректний розмір файлу.")
        if f.get("preserve", False) and f["path"].split("/")[0] not in {"config", "defaultconfigs"}:
            raise ValueError("preserve дозволено лише для конфігурацій.")
        source = f.get("source", {})
        if source.get("type") == "bundle":
            if not allow_bundle or "url" in f:
                raise ValueError("Локальне джерело дозволено лише для модпаку з комплекту лаунчера.")
        elif "url" in f:
            checked_url(f["url"])
        elif source.get("type") not in ("modrinth", "curseforge") or not source.get("projectId") or not source.get("versionId"):
            raise ValueError("Вкажіть HTTPS URL або зафіксовані projectId/versionId джерела.")
    return data

def resolve_source(f, profile, curse_key=""):
    if f.get("url"):
        return f["url"]
    src = f["source"]
    from urllib.parse import quote
    project, version = quote(str(src["projectId"]), safe=""), quote(str(src["versionId"]), safe="")
    if src["type"] == "modrinth":
        data = get_json("https://api.modrinth.com/v2/version/" + version)
        if str(data["project_id"]) != str(src["projectId"]) or profile["minecraft"] not in data["game_versions"] or profile["loader"] not in data["loaders"]:
            raise ValueError("Файл Modrinth не сумісний із профілем або ID проєкту.")
        candidates = [x for x in data["files"] if x["filename"] == Path(f["path"]).name]
        if not candidates:
            raise ValueError("Файл Modrinth не знайдено у зафіксованій версії.")
        return checked_url(candidates[0]["url"])
    if not curse_key:
        raise ValueError("Додайте API-ключ CurseForge у налаштуваннях інтеграцій.")
    data = get_json(f"https://api.curseforge.com/v1/mods/{project}/files/{version}", headers={"x-api-key": curse_key})["data"]
    expected_loader = "NeoForge" if profile["loader"] == "neoforge" else "Forge"
    if data.get("modId") != int(src["projectId"]) or profile["minecraft"] not in data.get("gameVersions", []) or expected_loader not in data.get("gameVersions", []):
        raise ValueError("Файл CurseForge не сумісний із профілем.")
    if not data.get("downloadUrl"):
        raise ValueError("Автор обмежив завантаження через CurseForge API. Потрібне дозволене джерело від адміністратора.")
    return checked_url(data["downloadUrl"])

class SyncEngine:
    def __init__(self, root, progress=None, cancel=None, *, bundle_root=None, cache_root=None):
        self.root = Path(root)
        self.meta = self.root / ".revolution"
        if self.meta.is_symlink() or (hasattr(self.meta, "is_junction") and self.meta.is_junction()):
            raise ValueError("Службова папка не може бути посиланням.")
        self.meta.mkdir(parents=True, exist_ok=True)
        self.progress = progress or (lambda **kw: None)
        self.cancel = cancel
        self.bundle_root = Path(bundle_root) if bundle_root is not None else None
        from .cache import ObjectCache
        self.cache = ObjectCache(cache_root) if cache_root is not None else None
        self.recover()

    def _copy_bundled(self, entry, dest):
        import hashlib
        if self.bundle_root is None:
            raise ValueError("Модпак із комплекту не знайдено.")
        source = safe_path(self.bundle_root, entry["path"])
        digest, size = hashlib.sha256(), 0
        with source.open("rb") as src, dest.open("wb") as out:
            while chunk := src.read(1024 * 1024):
                if self.cancel and self.cancel.is_set():
                    raise Cancelled("Встановлення модпаку скасовано.")
                size += len(chunk)
                if size > entry.get("size", 2 * 1024**3):
                    raise ValueError("Некоректний розмір файлу з комплекту: " + entry["path"])
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != entry["sha256"].lower() or ("size" in entry and size != entry["size"]):
            raise ValueError("Пошкоджений файл у комплекті: " + entry["path"])

    def recover(self):
        journal = read_json(self.meta / "transaction.json")
        if journal:
            for item in reversed(journal["items"]):
                dest = safe_path(self.root, item["path"])
                backup = safe_path(self.meta / "backup", item["path"])
                if backup.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, dest)
                elif not item["existed"] and dest.is_file():
                    dest.unlink()
            atomic_json(self.meta / "managed.json", journal["old"])
            (self.meta / "transaction.json").unlink()

    def plan(self, manifest):
        old = read_json(self.meta / "managed.json", {"files": []})
        changes, preserved, healthy = [], [], []
        for f in manifest["files"]:
            dest = safe_path(self.root, f["path"])
            if f.get("preserve") and dest.is_file():
                preserved.append(f)
            elif dest.is_file() and file_hash(dest) == f["sha256"].lower():
                healthy.append(f)
            else:
                changes.append(f)
        names = {f["path"].casefold() for f in manifest["files"]}
        removed = [f for f in old["files"] if f["path"].casefold() not in names and not f.get("preserve") and safe_path(self.root, f["path"]).is_file()]
        return {"changes": changes, "removed": removed, "healthy": healthy, "preserved": preserved}

    def sync(self, manifest, profile, curse_key=""):
        validate_manifest(manifest, profile, self.root, allow_bundle=self.bundle_root is not None)
        plan = self.plan(manifest)
        required = sum(f.get("size", 0) for f in plan["changes"]) + 16 * 1024**2
        if shutil.disk_usage(self.root).free < required:
            raise ValueError(f"Недостатньо місця для оновлення. Потрібно щонайменше {required / 1024**3:.2f} ГіБ.")
        stage = self.meta / "stage"
        # These are engine-owned, fixed subdirectories inside the instance.
        for name in ("stage", "backup"):
            p = self.meta / name
            if p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()):
                raise ValueError("Некоректна службова папка.")
            if p.exists():
                shutil.rmtree(p)
        stage.mkdir()
        try:
            for i, f in enumerate(plan["changes"]):
                if self.cancel and self.cancel.is_set():
                    raise Cancelled("Синхронізацію скасовано.")
                dest = safe_path(stage, f["path"])
                dest.parent.mkdir(parents=True, exist_ok=True)
                bundled = f.get("source", {}).get("type") == "bundle"
                self.progress(message=("Копіювання " if bundled else "Завантаження ") + Path(f["path"]).name, current=i, total=len(plan["changes"]), phase="download")
                if self.cache and self.cache.restore(f, dest, self.cancel):
                    self.progress(message="Відновлено з кешу: " + Path(f["path"]).name)
                elif bundled:
                    self._copy_bundled(f, dest)
                else:
                    download(resolve_source(f, profile, curse_key), dest, f["sha256"], size=f.get("size"), cancel=self.cancel)
            if self.cancel and self.cancel.is_set():
                raise Cancelled("Синхронізацію скасовано.")
            old = read_json(self.meta / "managed.json", {"files": []})
            operations = plan["changes"] + plan["removed"]
            journal = {"old": old, "items": [{"path": f["path"], "existed": safe_path(self.root, f["path"]).exists()} for f in operations]}
            atomic_json(self.meta / "transaction.json", journal)
            self.progress(message="Застосування перевірених файлів", phase="commit", current=0, total=0)
            for f in operations:
                dest = safe_path(self.root, f["path"])
                backup = safe_path(self.meta / "backup", f["path"])
                if dest.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(dest, backup)
                staged = safe_path(stage, f["path"])
                if staged.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged, dest)
            atomic_json(self.meta / "managed.json", manifest)
            (self.meta / "transaction.json").unlink()
        except BaseException:
            self.recover()
            raise
        # Populate optional cache only after commit so it cannot consume disk
        # reserved for files that have not yet been downloaded.
        if self.cache:
            for item in plan["changes"] + plan["healthy"]:
                if self.cancel and self.cancel.is_set(): break
                try: self.cache.remember(item, safe_path(self.root, item["path"]))
                except OSError: pass
        return {"updated": len(plan["changes"]), "removed": len(plan["removed"]), "total": len(manifest["files"]), "preserved": len(plan["preserved"])}
