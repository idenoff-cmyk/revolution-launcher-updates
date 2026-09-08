import asyncio
import threading
import time
import xml.etree.ElementTree as ET
from .network import get_bytes, checked_url

def news_feed(url):
    if not url:
        return []
    raw = get_bytes(url)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("RSS містить непідтримувані XML-сутності.")
    root = ET.fromstring(raw)
    entries = root.findall(".//item") or root.findall("{http://www.w3.org/2005/Atom}entry")
    result = []
    for item in entries[:12]:
        def field(name):
            node = item.find(name)
            if node is None: node = item.find("{http://www.w3.org/2005/Atom}" + name)
            return (node.text or "").strip() if node is not None else ""
        link = field("link")
        if not link:
            node = item.find("{http://www.w3.org/2005/Atom}link")
            link = node.get("href", "") if node is not None else ""
        try: checked_url(link)
        except ValueError: link = ""
        result.append({"title": field("title")[:180], "date": (field("pubDate") or field("updated"))[:60], "url": link})
    return result

class DiscordPresence:
    def __init__(self, settings, status, stop):
        self.settings, self.status, self.stop = settings, status, stop
        self.playing = False
        self.started = None

    def run(self):
        from pypresence import Presence
        asyncio.set_event_loop(asyncio.new_event_loop())
        rpc, current_id = None, ""
        while not self.stop.is_set():
            settings = self.settings()
            client = settings.get("discordClientId", "") if settings.get("rpcEnabled") else ""
            try:
                if current_id != client and rpc:
                    rpc.close()
                    rpc = None
                current_id = client
                if not client:
                    self.status("disabled" if not settings.get("rpcEnabled") else "unconfigured")
                else:
                    if not rpc:
                        rpc = Presence(client)
                        rpc.connect()
                    values = {"details": "Грає на Revolution Modded" if self.playing else "У лаунчері Revolution", "state": "Minecraft · Спільнота Revolution"}
                    if self.playing and self.started:
                        values["start"] = self.started
                    rpc.update(**values)
                    self.status("active")
            except Exception:
                rpc = None
                self.status("disconnected")
            self.stop.wait(20)
        if rpc:
            try: rpc.close()
            except Exception: pass
