"""Verified NeoForge installer with bounded execution, cancellation and a persistent log."""
import os
import re
import subprocess
import time
import hashlib
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .network import get_bytes, download, Cancelled
from .runtime import NO_WINDOW

def install_neoforge(root, profile, java, callback, progress, cancel):
    from minecraft_launcher_lib.install import install_minecraft_version
    from minecraft_launcher_lib.vanilla_launcher import create_empty_vanilla_launcher_profiles_file, do_vanilla_launcher_profiles_exists
    install_minecraft_version(profile["minecraft"], str(root), callback=callback)
    if not do_vanilla_launcher_profiles_exists(str(root)):
        create_empty_vanilla_launcher_profiles_file(str(root))
    version = profile["loaderVersion"]
    if not re.fullmatch(r"21\.1\.\d+", version): raise ValueError("Некоректна версія NeoForge.")
    cache = root / ".revolution" / "installer"
    cache.mkdir(parents=True, exist_ok=True)
    url = f"https://maven.neoforged.net/releases/net/neoforged/neoforge/{version}/neoforge-{version}-installer.jar"
    checksum = get_bytes(url + ".sha256", limit=2048).decode().strip().split()[0]
    installer = cache / f"neoforge-{version}.jar"
    progress(message="Завантаження перевіреного інсталятора NeoForge", phase="install", current=0, total=0)
    download(url, installer, checksum, cancel=cancel)
    metadata, client, mappings = prefetch_libraries(root, profile, installer, progress, cancel)
    from minecraft_launcher_lib._helper import get_library_path, get_jar_mainclass
    from .storage import atomic_json
    variables = {"MINECRAFT_JAR": str(root / "versions" / profile["minecraft"] / (profile["minecraft"] + ".jar")),
                 "INSTALLER": str(installer), "ROOT": str(root), "SIDE": "client"}
    with zipfile.ZipFile(installer) as z:
        for key, values in metadata.get("data", {}).items():
            value = values["client"]
            if value.startswith("[") and value.endswith("]"):
                variables[key] = get_library_path(value[1:-1], str(root))
            elif value.startswith("/"):
                payload = cache / ("payload-" + key.lower())
                payload.write_bytes(z.read(value.lstrip("/")))
                variables[key] = str(payload)
            else:
                variables[key] = value.strip("'")
        # Some versions include Maven artifacts directly in the signed-off installer.
        for entry in z.infolist():
            if entry.filename.startswith("maven/") and not entry.is_dir():
                target = (root / "libraries" / entry.filename[6:]).resolve()
                if not target.is_relative_to((root / "libraries").resolve()):
                    raise ValueError("Некоректний вбудований шлях NeoForge.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(entry))
    def expand(value):
        if value.startswith("[") and value.endswith("]"):
            return get_library_path(value[1:-1], str(root))
        for key, replacement in variables.items():
            value = value.replace("{" + key + "}", replacement)
        return value
    processors = [p for p in metadata["processors"] if "client" in p.get("sides", ["client"])]
    progress(message="NeoForge: підготовка клієнта", phase="install", current=0, total=len(processors))
    with (cache / "installer.log").open("w", encoding="utf-8") as logfile:
        for index, processor in enumerate(processors):
            if cancel.is_set(): raise Cancelled()
            args = processor["args"]
            # Mojang mappings were already downloaded and verified through our TLS stack.
            # Run every other unmodified official processor in the declared order.
            if "--task" in args and args[args.index("--task") + 1] == "DOWNLOAD_MOJMAPS":
                target = Path(variables["MOJMAPS"])
                if not target.is_file() or hashlib.sha1(target.read_bytes()).hexdigest() != mappings["sha1"]:
                    raise ValueError("Контрольна сума Mojang mappings не збігається.")
                logfile.write("Mojang mappings verified by Revolution downloader.\n")
            else:
                jar = get_library_path(processor["jar"], str(root))
                classpath = os.pathsep.join(get_library_path(x, str(root)) for x in processor.get("classpath", []) + [processor["jar"]])
                command = [java, "-cp", classpath, get_jar_mainclass(jar)] + [expand(value) for value in args]
                logfile.write("Processor: " + processor["jar"] + "\n")
                logfile.flush()
                run_processor(command, cache, logfile, cancel)
                for output, expected in processor.get("outputs", {}).items():
                    output_path, expected = Path(expand(output)), expand(expected)
                    if not output_path.is_file() or hashlib.sha1(output_path.read_bytes()).hexdigest() != expected:
                        raise ValueError("Контрольна сума результату NeoForge не збігається.")
            progress(message=f"NeoForge: підготовка клієнта ({index + 1}/{len(processors)})", phase="install", current=index + 1, total=len(processors))
    identifier = "neoforge-" + version
    client["id"] = identifier
    atomic_json(root / "versions" / identifier / (identifier + ".json"), client)
    return identifier

def run_processor(command, cwd, logfile, cancel):
    started = time.monotonic()
    process = subprocess.Popen(command, cwd=cwd, stdout=logfile, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
    while process.poll() is None:
        if cancel.wait(0.5) or time.monotonic() - started > 1200:
            process.terminate()
            try: process.wait(5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
            if cancel.is_set(): raise Cancelled()
            raise ValueError("NeoForge перевищив час встановлення. Повторіть операцію.")
    if process.returncode:
        raise ValueError("NeoForge не встановлено. Подробиці: .revolution/installer/installer.log у папці збірки.")

def prefetch_libraries(root, profile, installer, progress, cancel):
    """Use the launcher's TLS/proxy stack; upstream Maven metadata pins SHA-1."""
    with zipfile.ZipFile(installer) as z:
        metadata = json.loads(z.read("install_profile.json"))
        client = json.loads(z.read(metadata.get("json", "/version.json").lstrip("/")))
    artifacts = {}
    for library in metadata["libraries"] + client["libraries"]:
        artifact = library.get("downloads", {}).get("artifact", {})
        if artifact.get("url"):
            artifacts[artifact["path"]] = artifact
    vanilla = json.loads((root / "versions" / profile["minecraft"] / (profile["minecraft"] + ".json")).read_text(encoding="utf-8"))
    mapping = vanilla["downloads"]["client_mappings"]
    coordinate = metadata["data"]["MOJMAPS"]["client"].strip("[]")
    name, extension = coordinate.split("@")
    group, artifact, version, classifier = name.split(":")
    mapping_path = f"{group.replace('.', '/')}/{artifact}/{version}/{artifact}-{version}-{classifier}.{extension}"
    artifacts[mapping_path] = {**mapping, "path": mapping_path}
    def fetch(artifact):
        if cancel.is_set(): raise Cancelled()
        rel = artifact["path"]
        if "\\" in rel or ":" in rel or any(p in ("", ".", "..") for p in rel.split("/")):
            raise ValueError("Некоректний шлях бібліотеки NeoForge.")
        base = (root / "libraries").resolve()
        target = (base / rel).resolve()
        if not target.is_relative_to(base): raise ValueError("Шлях бібліотеки виходить за межі інстансу.")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and hashlib.sha1(target.read_bytes()).hexdigest() == artifact["sha1"]:
            return
        staged = target.with_name(target.name + ".part")
        download(artifact["url"], staged, artifact["sha1"], algorithm="sha1", size=artifact.get("size"), cancel=cancel)
        os.replace(staged, target)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, artifact) for artifact in artifacts.values()]
        for count, future in enumerate(as_completed(futures), 1):
            future.result()
            progress(message="Завантаження бібліотек NeoForge", phase="install", current=count, total=len(futures))
    return metadata, client, mapping
