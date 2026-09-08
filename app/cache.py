"""Content-addressed cache. Instances receive copies, never mutable hard links."""
from __future__ import annotations
import hashlib
import os
import re
import shutil
import uuid
from pathlib import Path
from .network import Cancelled, file_hash

class ObjectCache:
    def __init__(self, root):
        self.root = Path(root)
        for part in (self.root, self.root.parent):
            if part.is_symlink() or part.is_junction():
                raise ValueError("Кеш не може бути посиланням.")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, sha):
        if not re.fullmatch(r"[a-fA-F0-9]{64}", sha):
            raise ValueError("Некоректний ключ кешу.")
        target = self.root / sha.lower()
        if target.is_symlink() or target.is_junction():
            raise ValueError("Файл кешу не може бути посиланням.")
        return target

    def restore(self, entry, destination, cancel=None):
        target = self.path(entry["sha256"])
        if not target.is_file(): return False
        digest, count = hashlib.sha256(), 0
        with target.open("rb") as src, Path(destination).open("wb") as out:
            while chunk := src.read(1024 * 1024):
                if cancel and cancel.is_set(): raise Cancelled()
                count += len(chunk)
                if count > entry.get("size", 2 * 1024**3): break
                digest.update(chunk)
                out.write(chunk)
        if count > entry.get("size", 2 * 1024**3) or digest.hexdigest() != entry["sha256"].lower() or ("size" in entry and count != entry["size"]):
            try: target.unlink()
            except OSError: pass
            return False
        return True

    def remember(self, entry, verified_file):
        target = self.path(entry["sha256"])
        source = Path(verified_file)
        tmp = self.root / (entry["sha256"].lower() + "." + uuid.uuid4().hex + ".tmp")
        try:
            if target.is_file() and file_hash(target) == entry["sha256"].lower(): return
            # Caching is optional; leave room for the update transaction and the OS.
            if shutil.disk_usage(self.root).free < source.stat().st_size + 256 * 1024**2: return
            shutil.copyfile(source, tmp)
            if file_hash(tmp) == entry["sha256"].lower(): os.replace(tmp, target)
        except OSError:
            pass
        finally:
            try: tmp.unlink(missing_ok=True)
            except OSError: pass
