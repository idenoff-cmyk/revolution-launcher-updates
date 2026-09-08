from __future__ import annotations
import hmac
import json
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import keyring
from minecraft_launcher_lib import microsoft_account
from .storage import validate_name, offline_uuid

SERVICE = "RevolutionLauncher"
REDIRECT = "http://localhost:59174/callback"

def secret_get(name):
    return keyring.get_password(SERVICE, name) or ""

def secret_set(name, value):
    if value:
        keyring.set_password(SERVICE, name, value)
    else:
        try:
            keyring.delete_password(SERVICE, name)
        except keyring.errors.PasswordDeleteError:
            pass

def microsoft_login(client_id, cancel):
    if not client_id:
        raise ValueError("Для Microsoft-входу додайте Client ID зареєстрованого застосунку Revolution у налаштуваннях.")
    url, state, verifier = microsoft_account.get_secure_login_data(client_id, REDIRECT)
    received = {}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/callback" or not hmac.compare_digest(query.get("state", [""])[0], state):
                self.send_error(400)
                return
            received.update(query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<html lang='uk'><title>Revolution</title><body style='background:#141518;color:#eee;font:20px system-ui;padding:80px'><h1>Revolution</h1>Поверніться до лаунчера. Вхід обробляється.</body></html>".encode())
    with HTTPServer(("127.0.0.1", 59174), Handler) as server:
        server.timeout = 0.5
        webbrowser.open(url)
        deadline = time.monotonic() + 180
        while not received and not cancel.is_set() and time.monotonic() < deadline:
            server.handle_request()
    if not received.get("code"):
        raise ValueError("Вхід скасовано або час очікування вичерпано.")
    result = microsoft_account.complete_login(client_id, None, REDIRECT, received["code"][0], verifier)
    secret_set("microsoft-refresh", result["refresh_token"])
    return {"type": "microsoft", "name": result["name"], "uuid": result["id"]}

def game_account(settings):
    account = settings["account"]
    if account["type"] == "offline":
        name = validate_name(account["name"])
        return {"username": name, "uuid": offline_uuid(name), "token": "0", "userType": "legacy"}
    refresh = secret_get("microsoft-refresh")
    if not refresh:
        raise ValueError("Увійдіть у Microsoft повторно.")
    data = microsoft_account.complete_refresh(settings["microsoftClientId"], None, REDIRECT, refresh)
    secret_set("microsoft-refresh", data["refresh_token"])
    return {"username": data["name"], "uuid": data["id"], "token": data["access_token"], "userType": "msa"}
