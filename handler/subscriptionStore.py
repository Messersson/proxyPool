# -*- coding: utf-8 -*-
"""订阅源持久化：data/subscriptions.json"""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from handler.configStore import get_data_dir


def get_subscriptions_file() -> str:
    return os.environ.get("PROXY_POOL_SUBSCRIPTIONS_FILE") or os.path.join(get_data_dir(), "subscriptions.json")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dir():
    path = get_data_dir()
    if not os.path.isdir(path):
        os.makedirs(path, exist_ok=True)


def load_subscriptions() -> List[Dict[str, Any]]:
    path = get_subscriptions_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data, list):
            return data
    except Exception:
        return []
    return []


def save_subscriptions(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    _ensure_dir()
    path = get_subscriptions_file()
    payload = {
        "updated_at": _now(),
        "items": items,
    }
    fd, tmp = tempfile.mkstemp(prefix="subscriptions_", suffix=".json", dir=get_data_dir())
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise
    return items


def list_subscriptions() -> Dict[str, Any]:
    items = load_subscriptions()
    return {
        "file": get_subscriptions_file(),
        "count": len(items),
        "items": items,
    }


def upsert_subscription(item: Dict[str, Any]) -> Dict[str, Any]:
    items = load_subscriptions()
    sid = item.get("id")
    found = False
    for i, old in enumerate(items):
        if old.get("id") == sid:
            merged = dict(old)
            merged.update(item)
            merged["updated_at"] = _now()
            items[i] = merged
            found = True
            item = merged
            break
    if not found:
        item = dict(item)
        item.setdefault("created_at", _now())
        item["updated_at"] = _now()
        items.append(item)
    save_subscriptions(items)
    return item


def delete_subscription(sid: str) -> bool:
    items = load_subscriptions()
    new_items = [x for x in items if x.get("id") != sid]
    if len(new_items) == len(items):
        return False
    save_subscriptions(new_items)
    return True


def get_subscription(sid: str) -> Optional[Dict[str, Any]]:
    for item in load_subscriptions():
        if item.get("id") == sid:
            return deepcopy(item)
    return None


def enabled_subscription_urls() -> List[Dict[str, Any]]:
    result = []
    for item in load_subscriptions():
        if item.get("enabled", True) and item.get("url"):
            result.append(item)
    return result
