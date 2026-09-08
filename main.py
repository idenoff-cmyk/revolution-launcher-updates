"""Native Qt desktop host. Local UI assets and a narrow JSON bridge."""
import argparse
import json
import os
import sys
from pathlib import Path
import truststore
truststore.inject_into_ssl()
from app.api import LauncherAPI
from app.storage import atomic_json, read_json

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", help="Override the launcher data directory")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    # Reliable rendering on Windows machines with unavailable or unstable GPU drivers.
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
    if args.debug:
        os.environ["QTWEBENGINE_REMOTE_DEBUGGING"] = "127.0.0.1:9224"
    # WebEngine reads its process flags on import in frozen Windows builds.
    from PySide6.QtCore import QObject, Slot, QUrl, Qt, QTimer
    from PySide6.QtGui import QColor, QIcon
    from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QMessageBox
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebChannel import QWebChannel
    root = (Path(args.data_dir) if args.data_dir else Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local/share")) / "RevolutionLauncher").resolve()
    root.mkdir(parents=True, exist_ok=True)
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)).resolve()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Revolution Launcher")
    app.setOrganizationName("Revolution")
    app.setWindowIcon(QIcon(str(assets / "ui/assets/mark.svg")))
    lock_file = (root / "launcher.lock").open("a+b")
    if os.name == "nt":
        import msvcrt
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            QMessageBox.information(None, "Revolution", "Лаунчер уже запущено з цією папкою даних.")
            return
    bundle_dir = (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent) / "modpack"
    try:
        community_path = bundle_dir.parent / "community.json"
        if community_path.exists() and community_path.stat().st_size > 16384:
            raise ValueError("Завеликий community.json.")
        defaults = read_json(community_path, {})
        if not isinstance(defaults, dict): raise ValueError("Некоректний community.json.")
        api = LauncherAPI(root, bundle_dir=bundle_dir, defaults=defaults)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        QMessageBox.critical(None, "Revolution", "Не вдалося прочитати дані збірки. Перевірте папку modpack та налаштування.\n\n" + str(exc)[:500])
        return
    class Window(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Revolution Launcher")
            self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
            self.resize(1380, 900)
            self.setMinimumSize(1080, 740)
            self.setStyleSheet("background:#121316;")
        def minimize(self): self.showMinimized()
        def toggle_fullscreen(self): self.showNormal() if self.isMaximized() else self.showMaximized()
        def destroy(self): QTimer.singleShot(0, self.close)
        def drag(self): self.windowHandle().startSystemMove()
        def create_file_dialog(self, mode, allow_multiple=False, file_types=None, save_filename=""):
            if mode == "save":
                path, _ = QFileDialog.getSaveFileName(self, "Зберегти маніфест", str(root / save_filename), "JSON (*.json)")
                return [path] if path else []
            if mode == "java":
                path, _ = QFileDialog.getOpenFileName(self, "Вибрати Java", "", "Java (java.exe javaw.exe)")
                return [path] if path else []
            paths, _ = QFileDialog.getOpenFileNames(self, "Додати моди", "", "Minecraft mods (*.jar)")
            return paths
        def closeEvent(self, event):
            if api.job["busy"]:
                event.ignore()
                QMessageBox.information(self, "Revolution", "Скасуйте поточну операцію перед закриттям.")
                return
            api.shutdown.set()
            event.accept()
    class Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, kind, is_main):
            return url.isLocalFile() and Path(url.toLocalFile()).resolve().is_relative_to(assets / "ui")
        def javaScriptConsoleMessage(self, level, message, line, source):
            if args.debug: print(f"JS {line}: {message}", flush=True)
    class Bridge(QObject):
        @Slot(result=str)
        def snapshot(self): return json.dumps(api.snapshot(), ensure_ascii=False)
        @Slot(str, str, result=str)
        def command(self, action, payload):
            try: return json.dumps(api.command(action, json.loads(payload)), ensure_ascii=False)
            except Exception: return json.dumps({"ok":False,"error":"Некоректний запит до лаунчера."})
    window = Window()
    api.window = window
    view = QWebEngineView(window)
    profile = QWebEngineProfile("Revolution", view)
    profile.setPersistentStoragePath(str(root / "webview"))
    profile.setCachePath(str(root / "webview/cache"))
    page = Page(profile, view)
    page.setBackgroundColor(QColor("#121316"))
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
    page.settings().setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, False)
    channel = QWebChannel(page)
    bridge = Bridge(channel)
    channel.registerObject("revolution", bridge)
    page.setWebChannel(channel)
    view.setPage(page)
    window.setCentralWidget(view)
    view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
    def loaded(ok):
        if not ok:
            QMessageBox.critical(window, "Revolution", "Не вдалося завантажити інтерфейс. Перевірте цілісність файлів застосунку.")
            return
        api.start_services()
        if args.smoke_test:
            def check():
                def result(value):
                    atomic_json(root / "smoke-result.json", json.loads(value) if value else {"error":"No JS result"})
                    view.grab().save(str(root / "smoke-window.png"))
                    window.close()
                page.runJavaScript("JSON.stringify({title:document.title,bridge:!!window.pywebview?.api,ui:!!document.querySelector('.hero')})", result)
            QTimer.singleShot(4000, check)
    view.loadFinished.connect(loaded)
    view.setUrl(QUrl.fromLocalFile(str(assets / "ui/index.html")))
    window.show()
    app.exec()

if __name__ == "__main__": main()
