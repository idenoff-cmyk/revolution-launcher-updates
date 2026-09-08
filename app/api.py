from __future__ import annotations
import copy
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from . import __version__
from .storage import Store, PROFILES, atomic_json, read_json, validate_name
from .network import get_json, checked_url, ping_server, file_hash, Cancelled
from .sync import SyncEngine, validate_manifest, safe_path
from .runtime import find_java, ensure_java, NO_WINDOW
from .auth import microsoft_login, game_account, secret_get, secret_set
from .integrations import news_feed, DiscordPresence
from .releases import verify_release, release_profile, describe_changes
from .diagnostics import collect_report, analyze_ai, redact

class LauncherAPI:
    def __init__(self, root, bundle_dir=None, defaults=None):
        self.store = Store(root, defaults)
        self.bundle_dir = Path(bundle_dir) if bundle_dir is not None else None
        self.bundled_manifest = None
        if self.bundle_dir is not None and (self.bundle_dir / "manifest.json").is_file():
            path = self.bundle_dir / "manifest.json"
            if path.stat().st_size > 4 * 1024**2:
                raise ValueError("Завеликий маніфест комплекту.")
            self.bundled_manifest = validate_manifest(read_json(path), PROFILES["modern"], self.bundle_dir, allow_bundle=True)
        self.window = None
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.shutdown = threading.Event()
        self.worker = None
        self.process = None
        self.events = []
        self.event_id = 0
        self.job = {"busy": False, "phase": "idle", "message": "Готові до нової пригоди", "current": 0, "total": 0, "error": ""}
        self.server = {"state": "checking", "online": None, "max": None, "ping": None}
        self.integrity = {"state": "local", "total": 0}
        self.rpc_state = "unconfigured"
        self.java = None
        self.news = []
        self.update_wake = threading.Event()
        self.next_update_check = 0
        self.updates = {"state":"idle", "source":"bundle", "lastChecked":None, "installedVersion":"", "availableVersion":"", "added":[], "changed":[], "removed":[], "notes":[], "signed":False}
        self._services_started = False
        self.presence = DiscordPresence(lambda: self.store.data.copy(), self._rpc_status, self.shutdown)
        self._refresh_local()
        self.diagnostics = read_json(self.store.instance_dir() / ".revolution/diagnostics.json", {})
        saved_updates = read_json(self.store.instance_dir() / ".revolution/update-state.json", {})
        self.updates.update(saved_updates, state="idle")

    def _rpc_status(self, value):
        self.rpc_state = value

    def start_services(self):
        if self._services_started: return
        self._services_started = True
        threading.Thread(target=self._status_loop, daemon=True).start()
        threading.Thread(target=self.presence.run, daemon=True).start()
        threading.Thread(target=self._initial_checks, daemon=True).start()
        self._try_maintenance()
        threading.Thread(target=self._updates_loop, daemon=True).start()

    def _initial_checks(self):
        try:
            self.java = find_java(self.store.root, self.store.profile()["javaMajor"], self.store.data["javaPath"])
        except Exception:
            self.java = None
        try:
            self.news = news_feed(self.store.data["newsUrl"])
        except Exception:
            self.log("warning", "Не вдалося прочитати RSS. Перевірте адресу стрічки.")

    def _status_loop(self):
        while not self.shutdown.is_set():
            self._check_server()
            self.shutdown.wait(30)

    def _check_server(self):
        try:
            self.server = ping_server(self.store.data["serverHost"], self.store.data["serverPort"])
        except Exception:
            self.server = {"state": "offline", "online": None, "max": None, "ping": None, "checkedAt": time.time()}
        if self.store.data["maintenanceUrl"]:
            try:
                if get_json(self.store.data["maintenanceUrl"]).get("maintenance") is True:
                    self.server["state"] = "maintenance"
            except Exception:
                pass

    def log(self, level, message):
        # Game arguments and authentication responses are never logged.
        message = redact(message, [self.store.root])[:1000]
        with self.lock:
            self.event_id += 1
            entry = {"id": self.event_id, "time": time.strftime("%H:%M:%S"), "level": level, "message": message}
            self.events.append(entry)
            self.events = self.events[-250:]
            logs = self.store.root / "logs"
            logs.mkdir(exist_ok=True)
            path = logs / "launcher.log"
            if path.exists() and path.stat().st_size > 2_000_000:
                path.replace(logs / "launcher.previous.log")
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def progress(self, **values):
        with self.lock:
            old = self.job.get("message")
            self.job.update(values)
            if values.get("message") and values["message"] != old:
                self.log("info", values["message"])

    def _refresh_local(self):
        root = self.store.instance_dir()
        SyncEngine(root)
        self.mods = [{"name": p.stem, "file": p.name, "size": p.stat().st_size, "source": "local"} for p in sorted((root / "mods").glob("*.jar")) if p.is_file()]
        managed = read_json(root / ".revolution" / "managed.json", {})
        mapped = {Path(x["path"]).name: x for x in managed.get("files", []) if x["path"].startswith("mods/")}
        for mod in self.mods:
            if mod["file"] in mapped:
                mod["name"] = mapped[mod["file"]].get("name", mod["name"])
                mod["source"] = mapped[mod["file"]].get("source", {}).get("type", "manifest")
        self.integrity = {"state": "unchecked" if managed else "local", "total": len(self.mods)}

    def snapshot(self):
        with self.lock:
            bundle = {"available": self._uses_bundle(), "total": len(self.bundled_manifest["files"]) if self.bundled_manifest else 0}
            return copy.deepcopy({"version": __version__, "settings": self.store.data, "profiles": PROFILES, "profile": self.store.profile(), "instance": self.store.active(), "job": self.job, "server": self.server, "integrity": self.integrity, "mods": self.mods, "bundle": bundle, "updates": self.updates, "diagnostics": self.diagnostics, "java": self.java, "rpc": self.rpc_state, "news": self.news, "events": self.events[-80:], "running": bool(self.process and self.process.poll() is None), "dataDir": str(self.store.root)})

    def _community_instance(self):
        return self.store.active()["id"] == "revolution" and self.store.active()["profile"] == "modern"

    def _remote_url(self):
        return self.store.data["manifestUrl"] if self._community_instance() else ""

    def _uses_bundle(self):
        if not self.bundled_manifest or not self._community_instance() or self._remote_url(): return False
        installed = read_json(self.store.instance_dir() / ".revolution/managed.json", {})
        return not installed.get("revision")

    def _try_maintenance(self):
        with self.lock:
            if not self._community_instance(): return False
            if self.job["busy"] or (self.process and self.process.poll() is None):
                return False
            self.next_update_check = time.monotonic() + 900
            self._begin("maintain")
            return True

    def _updates_loop(self):
        while not self.shutdown.is_set():
            self.update_wake.wait(15)
            self.update_wake.clear()
            if self.shutdown.is_set(): break
            if time.monotonic() >= self.next_update_check:
                self._try_maintenance()

    def _request_update_check(self):
        self.next_update_check = 0
        self.update_wake.set()

    def _job_maintain(self):
        return self._job_sync()

    def _guard(self):
        if self.job["busy"] or (self.process and self.process.poll() is None):
            raise ValueError("Дочекайтеся завершення операції або закрийте Minecraft.")

    def _begin(self, action):
        self._guard()
        self.cancel.clear()
        self.job = {"busy": True, "phase": action, "message": "Підготовка…", "current": 0, "total": 0, "error": ""}
        def run():
            try:
                result = getattr(self, "_job_" + action)()
                self.progress(phase="done", message=result or "Готово", current=1, total=1)
            except Cancelled:
                self.progress(phase="idle", message="Операцію скасовано", error="")
                if action == "ai": self.diagnostics["ai"] = {"state": "idle", "text": ""}
                if action in ("maintain", "sync", "check", "launch"): self.updates["state"] = "cancelled"
            except Exception as exc:
                import requests
                if isinstance(exc, requests.RequestException):
                    message = "Не вдалося завантажити дані. Перевірте інтернет, адресу джерела та сертифікат сервера."
                elif action == "login" and not isinstance(exc, ValueError):
                    message = "Microsoft-вхід не завершено. Перевірте Client ID, redirect URI та дозвіл застосунку на Minecraft API."
                else:
                    message = str(exc)[:500] or type(exc).__name__
                message = redact(message, [self.store.root])
                self.progress(phase="error", message="Операцію не завершено", error=message)
                self.log("error", message)
                if action in ("maintain", "sync", "check"):
                    self.updates["state"] = "error"
                    self.integrity["state"] = "error"
                if action == "ai": self.diagnostics["ai"] = {"state": "error", "text": message}
                if action == "launch":
                    if self.updates["state"] in ("checking", "updating"):
                        self.updates["state"] = "error"
                        self.integrity["state"] = "error"
                    try: self._collect_diagnostics(message)
                    except Exception: self.log("warning", "Не вдалося зібрати звіт діагностики.")
            finally:
                self.job["busy"] = False
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        return {"started": True}

    def _manifest(self):
        url = self._remote_url()
        self.updates.update(state="checking", source="remote" if url else "bundle", lastChecked=time.time(), signed=False)
        if url:
            manifest, _ = verify_release(get_json(url), self.store.data["manifestPublicKey"], self.store.profile(), self.store.instance_dir(), url)
            self.updates["signed"] = True
        else:
            installed = read_json(self.store.instance_dir() / ".revolution/managed.json", {})
            if self._community_instance() and installed.get("revision"):
                manifest = installed
                self.updates.update(source="cached", signed=False)
            elif self._uses_bundle():
                manifest = copy.deepcopy(self.bundled_manifest)
                self.updates["signed"] = False
            else:
                raise ValueError("Підключіть канал оновлень або додайте локальний модпак.")
        profile = release_profile(manifest, self.store.profile())
        validate_manifest(manifest, profile, self.store.instance_dir(), allow_bundle=self._uses_bundle())
        self.updates.update(availableVersion=manifest.get("version", ""), notes=manifest.get("notes", []))
        return manifest

    def _seed_bundle(self):
        root = self.store.instance_dir()
        if self._community_instance() and self.bundled_manifest and not (root / ".revolution/managed.json").exists():
            self.progress(message="Перше встановлення модпаку Revolution", phase="verify", current=0, total=0)
            SyncEngine(root, self.progress, self.cancel, bundle_root=self.bundle_dir, cache_root=self.store.root / "cache/objects").sync(self.bundled_manifest, PROFILES["modern"])
            self._refresh_local()

    def _job_check(self):
        self._refresh_local()
        root = self.store.instance_dir()
        self.progress(message="Перевірка SHA-256", phase="verify", current=0, total=0)
        if not self._community_instance():
            if not self.mods: raise ValueError("Додайте моди у власний інстанс.")
            for mod in self.mods:
                if self.cancel.is_set(): raise Cancelled()
                file_hash(safe_path(root, "mods/" + mod["file"]))
            self.integrity = {"state":"local", "total":len(self.mods)}
            return "Локальні файли прочитано. Централізований канал використовується інстансом Revolution Modded."
        manifest = self._manifest()
        plan = SyncEngine(root).plan(manifest)
        changes = len(plan["changes"]) + len(plan["removed"])
        installed = read_json(root / ".revolution/managed.json", {})
        self.updates.update(**describe_changes(plan, root), installedVersion=installed.get("version", ""), state="available" if changes else "ready")
        self.integrity = {"state":"updates" if changes else "healthy", "total":len(manifest["files"]), "changes":changes}
        return f"Знайдено змін: {changes}" if changes else "Цілісність збірки підтверджено"

    def _job_sync(self):
        self._seed_bundle()
        manifest = self._manifest()
        profile = release_profile(manifest, self.store.profile())
        root = self.store.instance_dir()
        engine = SyncEngine(root, self.progress, self.cancel, bundle_root=self.bundle_dir if self._uses_bundle() else None, cache_root=self.store.root / "cache/objects")
        plan = engine.plan(manifest)
        self.updates.update(**describe_changes(plan, root), state="updating")
        self.progress(message="Синхронізація модпаку Revolution", phase="verify", current=0, total=0)
        needs_key = any(f.get("source", {}).get("type") == "curseforge" and not f.get("url") for f in manifest["files"])
        result = engine.sync(manifest, profile, secret_get("curseforge") if needs_key else "")
        if self.store.profile()["loaderVersion"] != profile["loaderVersion"]:
            self.store.active()["loaderVersion"] = profile["loaderVersion"]
            self.store.save()
        self._refresh_local()
        self.integrity = {"state":"healthy", "total":result["total"]}
        self.updates.update(state="ready", installedVersion=manifest.get("version", ""))
        atomic_json(root / ".revolution/update-state.json", self.updates)
        self.next_update_check = time.monotonic() + 900
        return f"Модпак готовий · оновлено {result['updated']}, прибрано {result['removed']}"

    def _job_java(self):
        self.java = ensure_java(self.store.root, self.store.profile()["javaMajor"], self.store.data["javaPath"], self.progress, self.cancel)
        return f"Java {self.java['major']} готова"

    def _job_login(self):
        account = microsoft_login(self.store.data["microsoftClientId"], self.cancel)
        self.store.data["account"] = account
        self.store.save()
        return "Вітаємо, " + account["name"]

    def _job_launch(self):
        import minecraft_launcher_lib
        root = self.store.instance_dir()
        atomic_json(root / ".revolution/last-run.json", {"startedAt": time.time()})
        if self._community_instance():
            self._job_sync()
        profile = self.store.profile()
        self._job_java()
        if self.cancel.is_set(): raise Cancelled()
        loader = minecraft_launcher_lib.mod_loader.get_mod_loader(profile["loader"])
        loader_version = profile["loaderVersion"]
        if profile["loader"] == "forge": loader_version = profile["minecraft"] + "-" + loader_version
        version = loader.get_installed_version(profile["minecraft"], loader_version)
        installed = read_json(root / ".revolution" / "installation.json", {})
        if installed.get("version") != version or not (root / "versions" / version / (version + ".json")).exists():
            self.progress(message="Встановлення Minecraft і " + profile["loader"], phase="install", current=0, total=0)
            def status(message):
                if self.cancel.is_set(): raise Cancelled()
                self.progress(message=str(message), phase="install")
            def value(current):
                if self.cancel.is_set(): raise Cancelled()
                self.progress(current=current)
            callback = {"setStatus": status, "setProgress": value, "setMax": lambda total: self.progress(total=total)}
            if profile["loader"] == "neoforge":
                from .installer import install_neoforge
                version = install_neoforge(root, profile, self.java["path"], callback, self.progress, self.cancel)
            else:
                version = loader.install(profile["minecraft"], str(root), loader_version=loader_version, java=self.java["path"], callback=callback)
            atomic_json(root / ".revolution" / "installation.json", {"version": version, "installedAt": time.time()})
        if self.cancel.is_set(): raise Cancelled()
        self.progress(message="Підготовка профілю гравця", phase="launch", current=0, total=0)
        account = game_account(self.store.data)
        ram = self.store.data["ram"]
        args = [f"-Xmx{ram}G", "-Xms1G", "-XX:+UseG1GC", "-Dfile.encoding=UTF-8"]
        if self.store.data["jvmPreset"] == "performance":
            args += ["-XX:+ParallelRefProcEnabled", "-XX:MaxGCPauseMillis=100"]
        options = {**account, "gameDirectory": str(root), "executablePath": self.java["path"], "jvmArguments": args, "launcherName": "Revolution", "launcherVersion": __version__}
        if self.store.data["autoConnect"] and self.store.data["serverHost"]:
            if profile["minecraft"] == "1.21.1":
                options["quickPlayMultiplayer"] = self.store.data["serverHost"] + (":" + str(self.store.data["serverPort"]) if self.store.data["serverPort"] != 25565 else "")
            else:
                options.update({"server": self.store.data["serverHost"], "port": str(self.store.data["serverPort"])})
        command = minecraft_launcher_lib.command.get_minecraft_command(version, str(root), options)
        logs = root / "logs"
        logs.mkdir(exist_ok=True)
        with (logs / "revolution-game.log").open("w", encoding="utf-8") as out:
            self.process = subprocess.Popen(command, cwd=root, stdout=out, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
        started = time.time()
        instance = self.store.active()
        self.presence.playing, self.presence.started = True, started
        launched_process, launch_worker = self.process, self.worker
        def watch():
            code = launched_process.wait()
            if launch_worker and launch_worker is not threading.current_thread():
                launch_worker.join()
            self.presence.playing = False
            with self.lock:
                instance["hours"] = round(instance.get("hours", 0) + (time.time() - started) / 3600, 3)
                self.store.save()
            self.log("info" if code == 0 else "error", f"Minecraft завершено з кодом {code}. Журнал: logs/revolution-game.log")
            if code != 0:
                self.progress(phase="error", message="Minecraft завершився з помилкою", error=f"Minecraft: код {code}. Відкрийте logs/revolution-game.log у папці збірки.")
                try: self._collect_diagnostics(f"Minecraft завершився з кодом {code}")
                except Exception: self.log("warning", "Не вдалося зібрати звіт діагностики.")
                self.next_update_check = time.monotonic() + 900
            else:
                self._request_update_check()
        threading.Thread(target=watch, daemon=True).start()
        return "Minecraft запущено"

    def _collect_diagnostics(self, error=""):
        root = self.store.instance_dir()
        run = read_json(root / ".revolution/last-run.json", {})
        self.diagnostics = collect_report(root, self.store.root, self.store.profile(),
                                          self.store.data["ram"], self.mods, error, run.get("startedAt", 0))
        atomic_json(root / ".revolution/diagnostics.json", self.diagnostics)

    def _job_diagnose(self):
        self._collect_diagnostics(self._diagnostic_error)
        return "Локальну діагностику завершено"

    def _job_ai(self):
        self.diagnostics["ai"] = {"state": "working", "text": ""}
        answer = analyze_ai(self._ai_report, self.store.data["aiProvider"], self.store.data["aiModel"],
                            secret_get("gemini") if self.store.data["aiProvider"] == "gemini" else "", self.cancel)
        self.diagnostics["ai"] = {"state": "ready", "text": answer}
        atomic_json(self.store.instance_dir() / ".revolution/diagnostics.json", self.diagnostics)
        return "Пояснення ШІ готове"

    def command(self, action, payload=None):
        payload = payload or {}
        try:
            with self.lock:
                if action in ("launch", "sync", "check", "java", "login"):
                    return {"ok": True, **self._begin(action)}
                if action == "diagnose":
                    self._guard()
                    self._diagnostic_error = self.job.get("error", "")
                    return {"ok": True, **self._begin("diagnose")}
                if action == "ai":
                    self._guard()
                    if payload.get("consent") is not True or not self.diagnostics.get("id") or payload.get("reportId") != self.diagnostics["id"]:
                        raise ValueError("Переглянь актуальний звіт і підтверди його аналіз.")
                    if payload.get("provider") != self.store.data["aiProvider"] or payload.get("model") != self.store.data["aiModel"]:
                        raise ValueError("Налаштування ШІ змінилися. Переглянь звіт ще раз.")
                    self._ai_report = copy.deepcopy(self.diagnostics)
                    return {"ok": True, **self._begin("ai")}
                if action == "export_diagnostics":
                    if not self.diagnostics.get("id"): raise ValueError("Спочатку запусти діагностику.")
                    paths = self.window.create_file_dialog("save", save_filename="revolution-diagnostics.json")
                    if paths: atomic_json(Path(paths[0]), self.diagnostics)
                    return {"ok": True, "saved": bool(paths)}
                if action == "cancel":
                    if self.job["phase"] == "commit": raise ValueError("Завершуємо застосування файлів. Зачекайте кілька секунд.")
                    self.cancel.set()
                elif action == "refresh_server":
                    threading.Thread(target=self._check_server, daemon=True).start()
                elif action == "save_settings":
                    self._guard()
                    allowed = set(self.store.data) - {"instances", "activeInstance", "account"}
                    patch = {k: v for k, v in payload.items() if k in allowed}
                    for k, v in patch.items():
                        if type(v) is not type(self.store.data[k]): raise ValueError("Некоректний формат налаштування: " + k)
                        if k.endswith("Url") and v: checked_url(v)
                    if "microsoftClientId" in patch and patch["microsoftClientId"]:
                        try: uuid.UUID(patch["microsoftClientId"])
                        except ValueError: raise ValueError("Microsoft Client ID має бути UUID із розділу Overview застосунку.")
                    if "manifestPublicKey" in patch and patch["manifestPublicKey"]:
                        import base64
                        try: valid_key = len(base64.b64decode(patch["manifestPublicKey"], validate=True)) == 32
                        except ValueError: valid_key = False
                        if not valid_key: raise ValueError("Публічний ключ Ed25519 має містити 32 байти в Base64.")
                    if "ram" in patch and not 2 <= patch["ram"] <= 32: raise ValueError("RAM має бути від 2 до 32 ГБ.")
                    if "serverPort" in patch and not 1 <= patch["serverPort"] <= 65535: raise ValueError("Порт має бути від 1 до 65535.")
                    if "serverHost" in patch and (len(patch["serverHost"]) > 253 or re.search(r"[/:\\\s]", patch["serverHost"])): raise ValueError("Вкажіть домен сервера без порту та https://.")
                    if "jvmPreset" in patch and patch["jvmPreset"] not in ("balanced", "performance"): raise ValueError("Невідомий пресет JVM.")
                    if "aiProvider" in patch and patch["aiProvider"] not in ("off", "gemini", "ollama"): raise ValueError("Невідомий ШІ-сервіс.")
                    if "aiModel" in patch and patch["aiModel"] and not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", patch["aiModel"]): raise ValueError("Некоректна назва ШІ-моделі.")
                    if payload.get("curseforgeKey"): secret_set("curseforge", payload["curseforgeKey"])
                    if payload.get("geminiKey"): secret_set("gemini", payload["geminiKey"])
                    if payload.get("clearGeminiKey") is True: secret_set("gemini", "")
                    self.store.data.update(patch)
                    self.store.save()
                    if {"manifestUrl", "manifestPublicKey"} & patch.keys(): self._request_update_check()
                    threading.Thread(target=self._initial_checks, daemon=True).start()
                    threading.Thread(target=self._check_server, daemon=True).start()
                elif action == "offline":
                    self._guard()
                    name = validate_name(payload.get("name", ""))
                    self.store.data["account"] = {"type": "offline", "name": name}
                    self.store.save()
                elif action == "switch":
                    self._guard()
                    if payload["id"] not in [x["id"] for x in self.store.data["instances"]]: raise ValueError("Інстанс не знайдено.")
                    self.store.data["activeInstance"] = payload["id"]
                    self.store.save()
                    self._refresh_local()
                    self.java = None
                    self.diagnostics = read_json(self.store.instance_dir() / ".revolution/diagnostics.json", {})
                    self._request_update_check()
                elif action == "create_instance":
                    self._guard()
                    name = str(payload.get("name", "")).strip()[:60]
                    if not name: raise ValueError("Додайте назву збірки.")
                    if payload.get("profile") not in PROFILES: raise ValueError("Виберіть підтримуваний профіль.")
                    item = {"id": uuid.uuid4().hex[:12], "name": name, "profile": payload["profile"], "hours": 0}
                    self.store.data["instances"].append(item)
                    self.store.data["activeInstance"] = item["id"]
                    self.store.save()
                    self._refresh_local()
                    self.java = None
                    self.diagnostics = {}
                elif action == "open_folder":
                    target = self.store.instance_dir() if payload.get("kind") != "logs" else self.store.root / "logs"
                    target.mkdir(exist_ok=True)
                    os.startfile(target)
                elif action == "open_link":
                    url = self.store.data.get(payload.get("key", ""), "")
                    if not url: raise ValueError("Додайте це посилання в налаштуваннях спільноти.")
                    webbrowser.open(checked_url(url))
                elif action == "open_news":
                    entry = next((x for x in self.news if x["url"] == payload.get("url")), None)
                    if not entry: raise ValueError("Новину не знайдено.")
                    webbrowser.open(checked_url(entry["url"]))
                elif action in ("import_mods", "export_manifest", "pick_java"):
                    self._guard()
                    return self._dialog_action(action, payload)
                elif action == "minimize": self.window.minimize()
                elif action == "drag": self.window.drag()
                elif action == "maximize": self.window.toggle_fullscreen()
                elif action == "close":
                    if self.job["busy"]: raise ValueError("Скасуйте поточну операцію перед закриттям.")
                    self.window.destroy()
                else: raise ValueError("Невідома дія.")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)[:500]}

    def _dialog_action(self, action, payload):
        if action == "pick_java":
            paths = self.window.create_file_dialog("java")
            return {"ok": True, "path": paths[0] if paths else ""}
        if action == "import_mods":
            paths = self.window.create_file_dialog("mods", allow_multiple=True)
            if not paths: return {"ok": True, "count": 0}
            root = self.store.instance_dir()
            for source in paths:
                source = Path(source)
                if source.suffix.lower() != ".jar" or not source.is_file(): raise ValueError("Оберіть JAR-файли модів.")
                dest = safe_path(root, "mods/" + source.name)
                if dest.exists(): raise ValueError("Файл вже існує: " + source.name + ". Керуйте ним через папку збірки.")
            for source in paths:
                source = Path(source)
                dest = safe_path(root, "mods/" + source.name)
                dest.parent.mkdir(exist_ok=True)
                shutil.copy2(source, dest)
            self._refresh_local()
            return {"ok": True, "count": len(paths)}
        base = checked_url(payload.get("baseUrl", "")).rstrip("/")
        paths = self.window.create_file_dialog("save", save_filename="manifest.json")
        if not paths: return {"ok": True, "cancelled": True}
        from urllib.parse import quote
        from .sync import ALLOWED
        root, files = self.store.instance_dir(), []
        for directory in sorted(ALLOWED):
            for p in sorted((root / directory).rglob("*")):
                if not p.is_file(): continue
                rel = p.relative_to(root).as_posix()
                safe_path(root, rel)
                files.append({"path": rel, "sha256": file_hash(p), "size": p.stat().st_size, "url": base + "/" + quote(rel), **({"preserve": True} if directory in ("config", "defaultconfigs") else {})})
        if not files: raise ValueError("Спочатку додайте моди або конфігурації у збірку.")
        data = {"schemaVersion": 1, "name": self.store.active()["name"], "version": time.strftime("%Y.%m.%d"), **{k: v for k, v in self.store.profile().items() if k != "javaMajor"}, "files": files}
        validate_manifest(data, self.store.profile(), root)
        atomic_json(Path(paths[0]), data)
        return {"ok": True, "count": len(files), "path": paths[0]}
