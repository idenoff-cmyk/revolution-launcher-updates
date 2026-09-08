from __future__ import annotations
import copy
import json
import os
import re
import uuid
from pathlib import Path

PROFILES = {
    "modern": {"minecraft": "1.21.1", "loader": "neoforge", "loaderVersion": "21.1.250", "javaMajor": 21},
    "legacy": {"minecraft": "1.12.1", "loader": "forge", "loaderVersion": "14.22.1.2485", "javaMajor": 8},
}
DEFAULTS = {
    "activeInstance": "revolution", "ram": 6, "javaPath": "", "jvmPreset": "balanced",
    "serverHost": "revolution.modpack.gg", "serverPort": 25565, "maintenanceUrl": "", "manifestUrl": "",
    "discordUrl": "https://discord.com/invite/R3bDcSBv52", "mapUrl": "", "websiteUrl": "", "newsUrl": "",
    "microsoftClientId": "6a13d8b7-ae7a-4772-bf45-47051eb16dee", "discordClientId": "", "rpcEnabled": True,
    "manifestPublicKey": "",
    "aiProvider": "off", "aiModel": "",
    "reducedMotion": False, "autoConnect": True,
    "account": {"type": "offline", "name": "Revolution"},
    "instances": [{"id": "revolution", "name": "Revolution Modded", "profile": "modern", "hours": 0}],
}

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)

def read_json(path: Path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))

def offline_uuid(name):
    import hashlib
    return uuid.UUID(bytes=hashlib.md5(("OfflinePlayer:" + name).encode()).digest(), version=3).hex

def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
        raise ValueError("Нікнейм: 3–16 латинських літер, цифр або символів _.")
    return name

def validate_profile(minecraft, loader, version):
    if loader == "neoforge" and minecraft == "1.21.1" and re.fullmatch(r"21\.1\.\d+", version):
        return 21
    if loader == "forge" and minecraft == "1.12.1" and re.fullmatch(r"14\.22\.\d+\.\d+", version):
        return 8
    raise ValueError("Несумісні версії. Підтримуються Minecraft 1.21.1 + NeoForge 21.1.x або Minecraft 1.12.1 + Forge 14.22.x.")

class Store:
    def __init__(self, root, defaults=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "settings.json"
        self.data = copy.deepcopy(DEFAULTS)
        for key, value in (defaults or {}).items():
            if key in {"manifestUrl", "manifestPublicKey", "microsoftClientId", "discordClientId", "serverHost", "discordUrl"} and isinstance(value, str):
                self.data[key] = value
        configured = copy.deepcopy(self.data)
        saved = read_json(self.path, {})
        self.data.update(saved)
        for key in ("manifestUrl", "manifestPublicKey", "microsoftClientId", "discordClientId"):
            if not self.data.get(key): self.data[key] = configured[key]

    def save(self):
        atomic_json(self.path, self.data)

    def active(self):
        return next(x for x in self.data["instances"] if x["id"] == self.data["activeInstance"])

    def instance_dir(self, instance=None):
        instance = instance or self.active()
        if not re.fullmatch(r"[a-z0-9-]{1,64}", instance["id"]):
            raise ValueError("Некоректний ID інстансу.")
        path = self.root / "instances" / instance["id"]
        path.mkdir(parents=True, exist_ok=True)
        return path

    def profile(self):
        profile = PROFILES[self.active()["profile"]].copy()
        version = self.active().get("loaderVersion", profile["loaderVersion"])
        profile["javaMajor"] = validate_profile(profile["minecraft"], profile["loader"], version)
        profile["loaderVersion"] = version
        return profile
