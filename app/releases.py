"""Verified, monotonic release metadata for the community update channel."""
from __future__ import annotations
import base64
import hashlib
import json
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .storage import atomic_json, read_json, validate_profile
from .sync import validate_manifest

def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")

def release_profile(manifest, current):
    target = {k: manifest.get(k) for k in ("minecraft", "loader", "loaderVersion")}
    if target["minecraft"] != current["minecraft"] or target["loader"] != current["loader"]:
        raise ValueError("Реліз належить іншій версії Minecraft або іншому завантажувачу.")
    target["javaMajor"] = validate_profile(target["minecraft"], target["loader"], target["loaderVersion"])
    return target

def verify_release(document, public_key, current, instance_root, channel_url):
    if not public_key:
        raise ValueError("Додайте публічний ключ каналу оновлень у налаштуваннях спільноти.")
    if not isinstance(document, dict) or set(document) != {"payload", "signature"}:
        raise ValueError("Канал має повертати підписаний маніфест релізу.")
    payload = document["payload"]
    if not isinstance(payload, dict) or not isinstance(document["signature"], str):
        raise ValueError("Некоректний формат підписаного релізу.")
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key, validate=True))
        key.verify(base64.b64decode(document["signature"], validate=True), canonical_bytes(payload))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ValueError("Підпис оновлення недійсний. Встановлені файли збережено.") from exc
    if payload.get("packId") != "revolution" or type(payload.get("revision")) is not int or payload["revision"] < 1:
        raise ValueError("Неправильний ID модпаку або номер ревізії релізу.")
    profile = release_profile(payload, current)
    validate_manifest(payload, profile, instance_root)
    if not isinstance(payload.get("version"), str) or not 1 <= len(payload["version"]) <= 80:
        raise ValueError("Реліз має містити назву версії.")
    notes = payload.get("notes", [])
    if not isinstance(notes, list) or len(notes) > 100 or any(not isinstance(x, str) or len(x) > 2000 for x in notes):
        raise ValueError("Некоректні нотатки релізу.")
    digest = hashlib.sha256(canonical_bytes(payload)).hexdigest()
    identity = hashlib.sha256((channel_url + "\n" + public_key).encode()).hexdigest()
    ledger_path = Path(instance_root) / ".revolution" / ("channel-" + identity + ".json")
    ledger = read_json(ledger_path, {})
    if payload["revision"] < ledger.get("revision", 0) or (payload["revision"] == ledger.get("revision") and digest != ledger.get("sha256")):
        raise ValueError("Канал повернув стару або змінену ревізію. Оновлення відхилено.")
    atomic_json(ledger_path, {"revision": payload["revision"], "sha256": digest})
    return payload, profile

def describe_changes(plan, root):
    added, changed = [], []
    for item in plan["changes"]:
        target = Path(root) / item["path"]
        (changed if target.exists() else added).append(item.get("name", item["path"]))
    return {"added": added, "changed": changed, "removed": [f.get("name", f["path"]) for f in plan["removed"]]}
