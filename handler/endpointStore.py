# -*- coding: utf-8 -*-
"""可自定义对外代理接口（每个接口独立调用规则）"""
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, List, Optional

from handler.configStore import get_data_dir

_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def get_endpoints_file() -> str:
    return os.environ.get("PROXY_POOL_ENDPOINTS_FILE") or os.path.join(get_data_dir(), "proxy_endpoints.json")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_dir():
    d = get_data_dir()
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def default_endpoint_rules() -> Dict[str, Any]:
    return {
        "strategy": "round_robin",   # round_robin | random | sticky | lowest_latency
        "pool": "auto",              # auto | http | node
        "lease_seconds": 300,
        "prefer_https": False,
        "default_node_type": "",
        "fixed_proxy": "",           # 指定固定 HTTP 代理
        "fixed_node_id": "",         # 指定固定节点 id
        "fixed_share": "",           # 指定固定分享链
        "token": "",                 # 接口独立 token，空则走全局 API_TOKEN
        "enabled": True,
        "skip_timeout": True,
        "max_latency_ms": 0,
        "prefer_low_latency": True,
        "response_format": "json",   # json | legacy | simple | text | url | compatible | env | curl
    }


def _normalize_rules(raw: Dict[str, Any]) -> Dict[str, Any]:
    rules = default_endpoint_rules()
    if isinstance(raw, dict):
        rules.update(raw)
    rules["strategy"] = str(rules.get("strategy") or "round_robin").lower()
    if rules["strategy"] not in ("round_robin", "random", "sticky", "lowest_latency"):
        raise ValueError("strategy must be round_robin|random|sticky|lowest_latency")
    rules["pool"] = str(rules.get("pool") or "auto").lower()
    if rules["pool"] not in ("auto", "http", "node"):
        raise ValueError("pool must be auto|http|node")
    rules["lease_seconds"] = max(1, int(rules.get("lease_seconds") or 300))
    rules["prefer_https"] = bool(rules.get("prefer_https", False))
    rules["default_node_type"] = str(rules.get("default_node_type") or "")
    rules["fixed_proxy"] = str(rules.get("fixed_proxy") or "").strip()
    rules["fixed_node_id"] = str(rules.get("fixed_node_id") or "").strip()
    rules["fixed_share"] = str(rules.get("fixed_share") or "").strip()
    rules["token"] = str(rules.get("token") or "")
    rules["enabled"] = bool(rules.get("enabled", True))
    rules["skip_timeout"] = bool(rules.get("skip_timeout", True))
    try:
        rules["max_latency_ms"] = max(0, int(rules.get("max_latency_ms") or 0))
    except Exception:
        rules["max_latency_ms"] = 0
    rules["prefer_low_latency"] = bool(rules.get("prefer_low_latency", True))
    fmt = str(rules.get("response_format") or rules.get("format") or "json").strip().lower()
    aliases = {
        "default": "json", "full": "json", "flat": "json",
        "legacy": "legacy", "get": "legacy", "classic": "legacy", "old": "legacy",
        "simple": "simple", "basic": "simple", "min": "simple", "minimal": "simple",
        "text": "text", "plain": "text", "raw": "text", "hostport": "text",
        "url": "url", "proxy_url": "url", "uri": "url",
        "compatible": "compatible", "compat": "compatible", "all": "compatible", "universal": "compatible", "multi": "compatible",
        "env": "env", "export": "env", "shell": "env",
        "curl": "curl", "curl_flag": "curl", "x": "curl",
    }
    fmt = aliases.get(fmt, fmt)
    if fmt not in ("json", "legacy", "simple", "text", "url", "compatible", "env", "curl"):
        raise ValueError("response_format must be json|legacy|simple|text|url|compatible|env|curl")
    rules["response_format"] = fmt
    rules.pop("format", None)
    return rules


def _normalize_endpoint(item: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("endpoint must be object")
    slug = str(item.get("slug") or item.get("path") or "").strip().strip("/")
    if not slug or not _SLUG_RE.match(slug):
        raise ValueError("slug invalid, use [A-Za-z0-9_-], 1-64 chars")
    reserved = {
        "get", "pop", "all", "count", "delete", "health", "admin", "api",
        "node", "v1", "open", "compatible", "static", "favicon.ico"
    }
    if slug.lower() in reserved:
        raise ValueError("slug reserved: %s" % slug)
    name = str(item.get("name") or slug).strip()
    ep = {
        "id": str(item.get("id") or uuid.uuid4().hex[:12]),
        "slug": slug,
        "name": name,
        "path": "/open/%s" % slug,
        "desc": str(item.get("desc") or ""),
        "enabled": bool(item.get("enabled", True)),
        "rules": _normalize_rules(item.get("rules") or {}),
        "created_at": item.get("created_at") or _now(),
        "updated_at": _now(),
    }
    # endpoint enabled overrides rules.enabled convenience
    ep["rules"]["enabled"] = bool(ep["enabled"])
    return ep


def load_endpoints() -> List[Dict[str, Any]]:
    path = get_endpoints_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            return raw["items"]
        if isinstance(raw, list):
            return raw
    except Exception:
        return []
    return []


def save_endpoints(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    _ensure_dir()
    path = get_endpoints_file()
    payload = {"updated_at": _now(), "items": items}
    fd, tmp = tempfile.mkstemp(prefix="proxy_endpoints_", suffix=".json", dir=get_data_dir())
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


def list_endpoints() -> Dict[str, Any]:
    items = load_endpoints()
    return {
        "file": get_endpoints_file(),
        "count": len(items),
        "items": items,
    }


def get_endpoint_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    slug = (slug or "").strip().strip("/")
    for item in load_endpoints():
        if str(item.get("slug") or "") == slug:
            return deepcopy(item)
    return None


def get_endpoint_by_id(eid: str) -> Optional[Dict[str, Any]]:
    for item in load_endpoints():
        if str(item.get("id") or "") == str(eid):
            return deepcopy(item)
    return None


def upsert_endpoint(payload: Dict[str, Any]) -> Dict[str, Any]:
    items = load_endpoints()
    ep = _normalize_endpoint(payload)
    # unique slug
    for old in items:
        if old.get("slug") == ep["slug"] and old.get("id") != ep["id"]:
            raise ValueError("slug already exists: %s" % ep["slug"])
    found = False
    for i, old in enumerate(items):
        if old.get("id") == ep["id"] or old.get("slug") == ep["slug"]:
            ep["id"] = old.get("id") or ep["id"]
            ep["created_at"] = old.get("created_at") or ep["created_at"]
            items[i] = ep
            found = True
            break
    if not found:
        items.append(ep)
    save_endpoints(items)
    return ep


def delete_endpoint(eid: str = "", slug: str = "") -> bool:
    items = load_endpoints()
    new_items = []
    deleted = False
    for x in items:
        if eid and str(x.get("id")) == str(eid):
            deleted = True
            continue
        if slug and str(x.get("slug")) == str(slug):
            deleted = True
            continue
        new_items.append(x)
    if deleted:
        save_endpoints(new_items)
    return deleted
