from __future__ import annotations
import hashlib
import ipaddress
import json
import socket
import struct
import time
from urllib.parse import urlparse
import requests
import truststore
truststore.inject_into_ssl()

USER_AGENT = "RevolutionLauncher/1.1.0 (+https://github.com/idenoff-cmyk/revolution-launcher-updates)"
class Cancelled(Exception):
    pass

def checked_url(url, local=False):
    if not isinstance(url, str) or len(url) > 4096:
        raise ValueError("Некоректна адреса.")
    p = urlparse(url)
    if p.username or p.password or not p.hostname:
        raise ValueError("URL не може містити облікові дані.")
    loopback = p.hostname in ("localhost", "127.0.0.1", "::1")
    if p.scheme != "https" and not (local and loopback and p.scheme == "http"):
        raise ValueError("Використовуйте захищену адресу https://.")
    return url

def response(url, *, headers=None, local=False):
    # Check every redirect, including HTTPS -> HTTP downgrades.
    for _ in range(6):
        checked_url(url, local)
        r = requests.get(url, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=(10, 30), stream=True, allow_redirects=False)
        if r.is_redirect:
            from urllib.parse import urljoin
            nxt = urljoin(url, r.headers["Location"])
            if urlparse(nxt).netloc != urlparse(url).netloc:
                headers = None
            r.close()
            url = nxt
            continue
        r.raise_for_status()
        return r
    raise ValueError("Забагато перенаправлень.")

def get_bytes(url, limit=2_000_000, **kwargs):
    chunks, size = [], 0
    with response(url, **kwargs) as r:
        for chunk in r.iter_content(65536):
            size += len(chunk)
            if size > limit:
                raise ValueError("Відповідь сервера перевищує допустимий розмір.")
            chunks.append(chunk)
    return b"".join(chunks)

def get_json(url, **kwargs):
    return json.loads(get_bytes(url, **kwargs))

def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def download(url, path, checksum, *, size=None, cancel=None, progress=None, local=False, algorithm="sha256"):
    import re
    if algorithm not in ("sha256", "sha1") or not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{" + str(64 if algorithm == "sha256" else 40) + "}", checksum):
        raise ValueError("Відсутня або некоректна контрольна сума.")
    cap = size if size is not None else 2 * 1024**3
    for attempt in range(3):
        try:
            digest, count = hashlib.new(algorithm), 0
            with response(url, local=local) as r, open(path, "wb") as f:
                total = int(r.headers.get("Content-Length", 0))
                if total > cap:
                    raise ValueError("Файл перевищує розмір у маніфесті.")
                for chunk in r.iter_content(256 * 1024):
                    if cancel and cancel.is_set():
                        raise Cancelled("Операцію скасовано.")
                    count += len(chunk)
                    if count > cap:
                        raise ValueError("Файл перевищує дозволений розмір.")
                    digest.update(chunk)
                    f.write(chunk)
                    if progress:
                        progress(count, total)
            if digest.hexdigest().lower() != checksum.lower():
                raise ValueError(algorithm.upper() + " не збігається. Файл не встановлено.")
            if size is not None and count != size:
                raise ValueError("Розмір файлу не збігається з маніфестом.")
            return count
        except (requests.RequestException, OSError):
            if attempt == 2:
                raise
            if cancel and cancel.wait(0.5 * (attempt + 1)):
                raise Cancelled("Операцію скасовано.")

def varint(n):
    n &= 0xffffffff
    out = bytearray()
    while True:
        b = n & 0x7f
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)

def read_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Сервер закрив з’єднання.")
        data += chunk
    return data

def read_varint(sock):
    value = 0
    for i in range(5):
        b = read_exact(sock, 1)[0]
        value |= (b & 127) << (7 * i)
        if not b & 128:
            return value
    raise ValueError("Некоректний пакет сервера.")

def ping_server(host, port=25565):
    if not host:
        return {"state": "unconfigured", "online": None, "max": None, "ping": None}
    if len(host) > 253 or any(c in host for c in "/\\\x00\r\n"):
        raise ValueError("Вкажіть домен або IP сервера без https://.")
    connect_host, connect_port = resolve_server(host, port)
    with socket.create_connection((connect_host, connect_port), timeout=5) as s:
        s.settimeout(5)
        encoded = host.encode()
        packet = b"\x00" + varint(-1) + varint(len(encoded)) + encoded + struct.pack(">H", int(port)) + b"\x01"
        s.sendall(varint(len(packet)) + packet + b"\x01\x00")
        length = read_varint(s)
        if not 2 <= length <= 2_000_000:
            raise ValueError("Завеликий пакет статусу.")
        import io
        class Reader:
            def __init__(self, payload): self.buf = io.BytesIO(payload)
            def recv(self, n): return self.buf.read(n)
        data = Reader(read_exact(s, length))
        if read_varint(data) != 0:
            raise ValueError("Некоректний статус сервера.")
        status = json.loads(read_exact(data, read_varint(data)))
        nonce = struct.pack(">q", time.time_ns() // 1_000_000)
        ping_start = time.monotonic()
        s.sendall(b"\x09\x01" + nonce)
        if read_varint(s) != 9 or read_exact(s, 9) != b"\x01" + nonce:
            raise ValueError("Некоректна відповідь ping.")
        ping = round((time.monotonic() - ping_start) * 1000)
    return {"state": "online", "online": status.get("players", {}).get("online", 0), "max": status.get("players", {}).get("max", 0), "version": status.get("version", {}).get("name", ""), "ping": ping, "checkedAt": time.time()}

def resolve_server(host, port=25565):
    if int(port) == 25565:
        import os
        import dns.resolver
        import random
        if os.name == "nt":
            records = windows_srv("_minecraft._tcp." + host)
            if records:
                records = [r for r in records if r[0] == min(x[0] for x in records)]
                chosen = random.choices(records, weights=[max(1, r[1]) for r in records])[0]
                return chosen[2], chosen[3]
        try:
            records = list(dns.resolver.resolve("_minecraft._tcp." + host, "SRV", lifetime=3))
            records = [r for r in records if r.priority == min(x.priority for x in records)]
            picked = random.choices(records, weights=[max(1, r.weight) for r in records])[0]
            return str(picked.target).rstrip("."), picked.port
        except dns.exception.DNSException:
            pass
    return host, int(port)

def windows_srv(name):
    """Use Windows DNS (including cached/VPN/DoH answers) before raw UDP DNS."""
    import ctypes as c
    from ctypes import wintypes as w
    class SRV(c.Structure):
        _fields_ = [("target", w.LPWSTR), ("priority", w.WORD), ("weight", w.WORD), ("port", w.WORD), ("pad", w.WORD)]
    class Record(c.Structure): pass
    Record._fields_ = [("next", c.POINTER(Record)), ("name", w.LPWSTR), ("type", w.WORD), ("length", w.WORD), ("flags", w.DWORD), ("ttl", w.DWORD), ("reserved", w.DWORD), ("srv", SRV)]
    dll = c.WinDLL("dnsapi")
    dll.DnsQuery_W.argtypes = [w.LPCWSTR, w.WORD, w.DWORD, c.c_void_p, c.POINTER(c.POINTER(Record)), c.c_void_p]
    dll.DnsQuery_W.restype = w.DWORD
    dll.DnsRecordListFree.argtypes = [c.c_void_p, c.c_int]
    result = c.POINTER(Record)()
    records = []
    code = dll.DnsQuery_W(name, 33, 0, None, c.byref(result), None)
    if result:
        try:
            ptr = result
            while ptr:
                data = ptr.contents
                if code == 0 and data.type == 33 and data.srv.target:
                    records.append((data.srv.priority, data.srv.weight, data.srv.target.rstrip("."), data.srv.port))
                ptr = data.next
        finally:
            dll.DnsRecordListFree(result, 1)
    return records
