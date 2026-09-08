from __future__ import annotations
import os
import platform
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from .network import get_json, download

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

def java_info(path):
    p = Path(path)
    if p.is_dir():
        p = p / "bin" / ("java.exe" if os.name == "nt" else "java")
    if p.name.lower() == "javaw.exe":
        p = p.with_name("java.exe")
    result = subprocess.run([str(p), "-version"], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
    text = result.stderr + result.stdout
    match = re.search(r'version "(\d+)(?:\.(\d+))?', text)
    if not match or result.returncode:
        raise ValueError("Не вдалося визначити версію Java.")
    major = int(match[2]) if match[1] == "1" else int(match[1])
    return {"path": str(p.resolve()), "major": major, "is64bit": "64-Bit" in text or "aarch64" in text, "version": text.splitlines()[0]}

def find_java(root, major, preferred=""):
    if preferred:
        info = java_info(preferred)
        if info["major"] != major or not info["is64bit"]:
            raise ValueError(f"Для цієї збірки потрібна 64-бітна Java {major}.")
        return info
    candidates = list((Path(root) / "java").glob("**/bin/java.exe"))
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]))
    if shutil.which("java"):
        candidates.append(Path(shutil.which("java")))
    if os.name == "nt":
        for vendor in ("Java", "Eclipse Adoptium", "Microsoft", "Zulu"):
            candidates += list((Path(os.environ.get("ProgramFiles", "C:/Program Files")) / vendor).glob("*/bin/java.exe"))
    for path in candidates:
        try:
            info = java_info(path)
            if info["major"] == major and info["is64bit"]:
                return info
        except (ValueError, OSError, subprocess.SubprocessError):
            continue
    return None

def ensure_java(root, major, preferred, progress, cancel):
    found = find_java(root, major, preferred)
    if found:
        return found
    if os.name != "nt":
        raise ValueError(f"Встановіть Java {major} і вкажіть шлях у налаштуваннях. Автоматична інсталяція доступна на Windows.")
    arch = "aarch64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    progress(message=f"Пошук Eclipse Temurin Java {major}", phase="java", current=0, total=0)
    data = get_json(f"https://api.adoptium.net/v3/assets/latest/{major}/hotspot?architecture={arch}&image_type=jre&os=windows&vendor=eclipse")
    if not data:
        raise ValueError("Adoptium не має потрібної Java для цієї системи.")
    pkg = data[0]["binary"]["package"]
    directory = Path(root) / "java"
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / f"temurin-{major}.zip"
    progress(message=f"Завантаження Java {major}", phase="java", current=0, total=0)
    download(pkg["link"], archive, pkg["checksum"], size=pkg["size"], cancel=cancel,
             progress=lambda current, total: progress(message=f"Завантаження Java {major}", phase="java", current=current, total=total))
    stage = directory / f"extract-{major}"
    stage.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        for item in z.infolist():
            target = (stage / item.filename).resolve()
            if not target.is_relative_to(stage.resolve()) or ":" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Небезпечний шлях у ZIP Java.")
        if sum(x.file_size for x in z.infolist()) > 2 * 1024**3:
            raise ValueError("Завеликий архів Java.")
        z.extractall(stage)
    found = find_java(root, major)
    if not found:
        raise ValueError("Java завантажена, але виконуваний файл не знайдено.")
    archive.unlink(missing_ok=True)
    return found
