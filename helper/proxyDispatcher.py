# -*- coding: utf-8 -*-
"""统一对外代理调度：轮询 / 指定 / 租约切换 / 跳过超时节点。"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from handler.configStore import get_data_dir
from handler.proxyHandler import ProxyHandler
from helper.subscription import _load_all_nodes, _public_node, count_nodes

_lock = threading.RLock()

DEFAULT_RULES = {
    "strategy": "round_robin",
    "pool": "auto",
    "lease_seconds": 300,
    "prefer_https": False,
    "default_node_type": "",
    "skip_timeout": True,
    "max_latency_ms": 0,
    "prefer_low_latency": True,  # 优先调用低延迟节点
}


def _now_ts() -> float:
    return time.time()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_rules_file() -> str:
    return os.environ.get("PROXY_POOL_DISPATCH_FILE") or os.path.join(get_data_dir(), "dispatch_rules.json")


def get_state_file() -> str:
    return os.environ.get("PROXY_POOL_DISPATCH_STATE") or os.path.join(get_data_dir(), "dispatch_state.json")


def _ensure_dir():
    d = get_data_dir()
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def load_rules() -> Dict[str, Any]:
    path = get_rules_file()
    rules = dict(DEFAULT_RULES)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                rules.update(raw)
        except Exception:
            pass
    rules["strategy"] = str(rules.get("strategy") or "round_robin").lower()
    if rules["strategy"] not in ("round_robin", "random", "sticky", "lowest_latency"):
        rules["strategy"] = "round_robin"
    rules["pool"] = str(rules.get("pool") or "auto").lower()
    if rules["pool"] not in ("auto", "http", "node"):
        rules["pool"] = "auto"
    try:
        rules["lease_seconds"] = max(1, int(rules.get("lease_seconds") or 300))
    except Exception:
        rules["lease_seconds"] = 300
    rules["prefer_https"] = bool(rules.get("prefer_https", False))
    rules["default_node_type"] = str(rules.get("default_node_type") or "")
    rules["skip_timeout"] = bool(rules.get("skip_timeout", True))
    try:
        rules["max_latency_ms"] = max(0, int(rules.get("max_latency_ms") or 0))
    except Exception:
        rules["max_latency_ms"] = 0
    rules["prefer_low_latency"] = bool(rules.get("prefer_low_latency", True))
    return rules


def save_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = load_rules()
    if not isinstance(payload, dict):
        raise ValueError("payload must be object")
    for key in DEFAULT_RULES:
        if key in payload:
            current[key] = payload[key]
    current["strategy"] = str(current.get("strategy") or "round_robin").lower()
    if current["strategy"] not in ("round_robin", "random", "sticky", "lowest_latency"):
        raise ValueError("strategy must be round_robin|random|sticky|lowest_latency")
    current["pool"] = str(current.get("pool") or "auto").lower()
    if current["pool"] not in ("auto", "http", "node"):
        raise ValueError("pool must be auto|http|node")
    current["lease_seconds"] = max(1, int(current.get("lease_seconds") or 300))
    current["prefer_https"] = bool(current.get("prefer_https", False))
    current["default_node_type"] = str(current.get("default_node_type") or "")
    current["skip_timeout"] = bool(current.get("skip_timeout", True))
    current["max_latency_ms"] = max(0, int(current.get("max_latency_ms") or 0))
    current["prefer_low_latency"] = bool(current.get("prefer_low_latency", True))
    _ensure_dir()
    with open(get_rules_file(), "w", encoding="utf-8") as f:
        json.dump(current, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return current


def _load_state() -> Dict[str, Any]:
    path = get_state_file()
    if not os.path.isfile(path):
        return {"rr_index": {"http": 0, "node": 0}, "leases": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            raw.setdefault("rr_index", {"http": 0, "node": 0})
            raw.setdefault("leases", {})
            return raw
    except Exception:
        pass
    return {"rr_index": {"http": 0, "node": 0}, "leases": {}}


def _save_state(state: Dict[str, Any]) -> None:
    _ensure_dir()
    with open(get_state_file(), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _http_candidates(prefer_https: bool = False) -> List[Dict[str, Any]]:
    handler = ProxyHandler()
    items = []
    for p in handler.getAll(https=False):
        d = p.to_dict
        proxy_url = d.get("proxy_url") or (("http://%s" % d.get("proxy")) if d.get("proxy") else "")
        items.append({
            "pool": "http",
            "id": d.get("proxy"),
            "type": d.get("protocol") or ("https" if d.get("https") else "http"),
            "proxy": d.get("proxy"),
            "proxy_url": proxy_url,
            "http": proxy_url,
            "https_proxy": proxy_url,
            "proxies": d.get("proxies") or ({"http": proxy_url, "https": proxy_url} if proxy_url else {}),
            "http_proxy": d.get("proxy"),
            "https": bool(d.get("https")),
            "source": d.get("source"),
            "region": d.get("region"),
            "name": d.get("name") or d.get("proxy"),
            "share": d.get("share") or "",
            "latency_ms": d.get("latency_ms", -1),
            "last_status": d.get("last_status", ""),
            "raw": d,
        })
    if prefer_https:
        items.sort(key=lambda x: (0 if x.get("https") else 1))
    return items


def _node_candidates(node_type: str = "") -> List[Dict[str, Any]]:
    items = []
    for n in _load_all_nodes():
        t = str(n.get("type") or "").lower()
        if node_type and t != node_type.lower().strip():
            continue
        pub = _public_node(n, mask_secrets=False)
        http_proxy = pub.get("http_proxy") or ""
        ptype = str(pub.get("type") or "").lower()
        if http_proxy:
            if "://" in str(http_proxy):
                proxy_url = http_proxy
            elif ptype in ("socks", "socks5", "socks5h"):
                proxy_url = "socks5://%s" % http_proxy
            else:
                proxy_url = "http://%s" % http_proxy
        else:
            proxy_url = ""
        items.append({
            "pool": "node",
            "id": pub.get("id"),
            "type": pub.get("type"),
            "proxy": http_proxy or ("node:%s" % pub.get("id")),
            "proxy_url": proxy_url,
            "http": proxy_url,
            "https_proxy": proxy_url,
            "proxies": {"http": proxy_url, "https": proxy_url} if proxy_url else {},
            "http_proxy": http_proxy,
            "share": pub.get("share") or "",
            "server": pub.get("server"),
            "port": pub.get("port"),
            "name": pub.get("name"),
            "source": pub.get("source"),
            "latency_ms": pub.get("latency_ms", -1),
            "last_status": pub.get("last_status", ""),
            "raw": pub,
        })
    return items


def _is_available(item: Dict[str, Any], skip_timeout: bool = True, max_latency_ms: int = 0) -> bool:
    if not item:
        return False
    if not skip_timeout:
        return True
    status = item.get("last_status")
    try:
        latency = int(item.get("latency_ms", -1))
    except Exception:
        latency = -1
    if status is False or str(status).lower() in ("false", "0", "fail", "timeout"):
        return False
    if latency < 0:
        # 未探测且不是明确失败：放行；明确超时/失败已过滤
        if status is True or str(status).lower() in ("true", "1", "ok", ""):
            # 空状态视为未知，放行；latency=-1 + true 也放行
            return True if str(status).lower() in ("true", "1", "ok", "") else False
        return False
    if max_latency_ms and latency > max_latency_ms:
        return False
    return True


def _filter_available(cands: List[Dict[str, Any]], skip_timeout: bool = True, max_latency_ms: int = 0) -> List[Dict[str, Any]]:
    if not cands:
        return []
    try:
        handler = ProxyHandler()
        by_key = {}
        for p in handler.getAll(https=False):
            d = p.to_dict
            by_key[str(d.get("proxy"))] = d
            if d.get("node_id"):
                by_key["node:%s" % d.get("node_id")] = d
        for c in cands:
            d = by_key.get(str(c.get("proxy") or ""))
            if d:
                c["latency_ms"] = d.get("latency_ms", c.get("latency_ms", -1))
                c["last_status"] = d.get("last_status", c.get("last_status", ""))
    except Exception:
        pass
    filtered = [c for c in cands if _is_available(c, skip_timeout=skip_timeout, max_latency_ms=max_latency_ms)]
    filtered.sort(
        key=lambda x: (
            0 if int(x.get("latency_ms", -1) or -1) >= 0 else 1,
            int(x.get("latency_ms")) if int(x.get("latency_ms", -1) or -1) >= 0 else 10 ** 9,
        )
    )
    return filtered


def _pick_round_robin(cands: List[Dict[str, Any]], state: Dict[str, Any], key: str) -> Optional[Dict[str, Any]]:
    if not cands:
        return None
    idx_map = state.setdefault("rr_index", {})
    i = int(idx_map.get(key, 0) or 0) % len(cands)
    item = cands[i]
    idx_map[key] = (i + 1) % len(cands)
    return item


def _pick_random(cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not cands:
        return None
    import random
    return random.choice(cands)


def _find_specified(cands: List[Dict[str, Any]], proxy: str = "", node_id: str = "", share: str = "") -> Optional[Dict[str, Any]]:
    for c in cands:
        if proxy and (c.get("proxy") == proxy or c.get("http_proxy") == proxy or c.get("id") == proxy):
            return c
        if node_id and str(c.get("id") or "") == str(node_id):
            return c
        if share and str(c.get("share") or "") == str(share):
            return c
    return None


def _client_key(client_id: str = "", token: str = "", ip: str = "", endpoint_slug: str = "") -> str:
    prefix = ("ep:%s|" % endpoint_slug.strip()) if endpoint_slug else ""
    if client_id:
        return prefix + "cid:%s" % client_id.strip()
    if token:
        return prefix + "tok:%s" % token.strip()
    if ip:
        return prefix + "ip:%s" % ip.strip()
    return prefix + "anon:%s" % uuid.uuid4().hex[:8]


def acquire(
    pool: str = "",
    strategy: str = "",
    lease_seconds: Optional[int] = None,
    node_type: str = "",
    prefer_https: Optional[bool] = None,
    proxy: str = "",
    node_id: str = "",
    share: str = "",
    client_id: str = "",
    force_rotate: bool = False,
    request_ip: str = "",
    request_token: str = "",
    rules_override: Optional[Dict[str, Any]] = None,
    endpoint_slug: str = "",
) -> Dict[str, Any]:
    with _lock:
        rules = load_rules()
        if isinstance(rules_override, dict) and rules_override:
            rules = dict(rules)
            rules.update(rules_override)

        use_pool = (pool or rules.get("pool") or "auto").lower()
        use_strategy = (strategy or rules.get("strategy") or "round_robin").lower()
        use_lease = max(1, int(lease_seconds if lease_seconds is not None else rules.get("lease_seconds") or 300))
        use_https = rules.get("prefer_https", False) if prefer_https is None else bool(prefer_https)
        use_node_type = node_type or rules.get("default_node_type") or ""
        if not proxy:
            proxy = str(rules.get("fixed_proxy") or "")
        if not node_id:
            node_id = str(rules.get("fixed_node_id") or "")
        if not share:
            share = str(rules.get("fixed_share") or "")

        state = _load_state()
        leases = state.setdefault("leases", {})
        key = _client_key(client_id=client_id, token=request_token, ip=request_ip, endpoint_slug=endpoint_slug)
        now = _now_ts()

        expired = [k for k, v in list(leases.items()) if float(v.get("expire_at", 0) or 0) <= now]
        for k in expired:
            leases.pop(k, None)

        specified = bool(proxy or node_id or share)
        if (not force_rotate) and (not specified) and key in leases:
            lease = leases[key]
            if float(lease.get("expire_at", 0) or 0) > now:
                item = lease.get("item") or {}
                remain = max(0, int(float(lease.get("expire_at") - now)))
                return {
                    "code": 0,
                    "mode": "lease_reuse",
                    "endpoint": endpoint_slug or "",
                    "client_key": key,
                    "strategy": use_strategy,
                    "pool": item.get("pool") or use_pool,
                    "lease_seconds": use_lease,
                    "lease_remain_seconds": remain,
                    "expire_at": lease.get("expire_at_str"),
                    "item": item,
                }

        http_cands = _http_candidates(prefer_https=use_https) if use_pool in ("auto", "http") else []
        node_cands = _node_candidates(node_type=use_node_type) if use_pool in ("auto", "node") else []
        if use_pool == "http":
            cands, rr_key = http_cands, "http"
        elif use_pool == "node":
            cands, rr_key = node_cands, "node"
        else:
            if use_node_type:
                cands = node_cands or http_cands
                rr_key = "node" if node_cands else "http"
            else:
                cands = http_cands or node_cands
                rr_key = "http" if http_cands else "node"

        skip_timeout = bool(rules.get("skip_timeout", True))
        max_latency_ms = max(0, int(rules.get("max_latency_ms") or 0))
        if not specified:
            cands = _filter_available(cands, skip_timeout=skip_timeout, max_latency_ms=max_latency_ms)

        prefer_low_latency = bool(rules.get("prefer_low_latency", True))
        # 优先低延迟：候选已按延迟排序；lowest_latency 策略始终取最低
        if prefer_low_latency or use_strategy == "lowest_latency":
            # 确保按延迟排序（_filter_available 已排序；未过滤时再排一次）
            try:
                cands = sorted(
                    cands,
                    key=lambda x: (
                        0 if int(x.get("latency_ms", -1) or -1) >= 0 else 1,
                        int(x.get("latency_ms")) if int(x.get("latency_ms", -1) or -1) >= 0 else 10 ** 9,
                    ),
                )
            except Exception:
                pass

        chosen = None
        if specified:
            all_cands = http_cands + node_cands
            chosen = _find_specified(all_cands, proxy=proxy, node_id=node_id, share=share)
            if not chosen:
                return {"code": 404, "src": "specified proxy/node not found"}
        else:
            if use_strategy == "random" and not prefer_low_latency:
                chosen = _pick_random(cands)
            elif use_strategy == "lowest_latency" or (prefer_low_latency and use_strategy in ("sticky", "lowest_latency")):
                # 始终最低延迟；rotate 时用轮询在低延迟序列上切换
                if force_rotate:
                    chosen = _pick_round_robin(cands, state, rr_key + ":lat")
                else:
                    chosen = cands[0] if cands else None
            elif prefer_low_latency and use_strategy == "round_robin":
                # 轮询，但在低延迟优先序列上轮询（序列已按延迟排序）
                chosen = _pick_round_robin(cands, state, rr_key + ":lat")
            elif prefer_low_latency and use_strategy == "random":
                # 随机，但只在延迟最低的前 N 个里随机（至少 1 个，最多 5 个或 30%）
                if not cands:
                    chosen = None
                else:
                    import random
                    n = max(1, min(5, max(1, int(len(cands) * 0.3))))
                    chosen = random.choice(cands[:n])
            else:
                if use_strategy == "random":
                    chosen = _pick_random(cands)
                else:
                    chosen = _pick_round_robin(cands, state, rr_key)

        if not chosen:
            return {"code": 0, "src": "no proxy", "item": None}

        expire_at = now + use_lease
        lease = {
            "client_key": key,
            "item": chosen,
            "strategy": use_strategy,
            "pool": chosen.get("pool"),
            "created_at": now,
            "created_at_str": _now_str(),
            "expire_at": expire_at,
            "expire_at_str": datetime.fromtimestamp(expire_at).strftime("%Y-%m-%d %H:%M:%S"),
            "lease_seconds": use_lease,
        }
        leases[key] = lease
        _save_state(state)
        return {
            "code": 0,
            "mode": "new" if not specified else "specified",
            "endpoint": endpoint_slug or "",
            "client_key": key,
            "strategy": use_strategy,
            "pool": chosen.get("pool"),
            "lease_seconds": use_lease,
            "lease_remain_seconds": use_lease,
            "expire_at": lease["expire_at_str"],
            "item": chosen,
        }


def release(client_id: str = "", request_ip: str = "", request_token: str = "", client_key: str = "", endpoint_slug: str = "") -> Dict[str, Any]:
    with _lock:
        state = _load_state()
        leases = state.setdefault("leases", {})
        key = client_key or _client_key(client_id=client_id, token=request_token, ip=request_ip, endpoint_slug=endpoint_slug)
        existed = key in leases
        leases.pop(key, None)
        _save_state(state)
        return {"code": 0, "src": "released" if existed else "not_found", "client_key": key}


def current(client_id: str = "", request_ip: str = "", request_token: str = "", client_key: str = "", endpoint_slug: str = "") -> Dict[str, Any]:
    with _lock:
        state = _load_state()
        leases = state.get("leases") or {}
        key = client_key or _client_key(client_id=client_id, token=request_token, ip=request_ip, endpoint_slug=endpoint_slug)
        lease = leases.get(key)
        if not lease:
            return {"code": 0, "src": "no lease", "client_key": key, "item": None}
        now = _now_ts()
        remain = int(float(lease.get("expire_at", 0) or 0) - now)
        if remain <= 0:
            leases.pop(key, None)
            _save_state(state)
            return {"code": 0, "src": "expired", "client_key": key, "item": None}
        return {
            "code": 0,
            "client_key": key,
            "lease_remain_seconds": remain,
            "expire_at": lease.get("expire_at_str"),
            "item": lease.get("item"),
        }


def status() -> Dict[str, Any]:
    with _lock:
        rules = load_rules()
        state = _load_state()
        now = _now_ts()
        active = []
        for k, v in (state.get("leases") or {}).items():
            remain = int(float(v.get("expire_at", 0) or 0) - now)
            if remain > 0:
                active.append({
                    "client_key": k,
                    "pool": (v.get("item") or {}).get("pool"),
                    "id": (v.get("item") or {}).get("id"),
                    "type": (v.get("item") or {}).get("type"),
                    "latency_ms": (v.get("item") or {}).get("latency_ms", -1),
                    "lease_remain_seconds": remain,
                    "expire_at": v.get("expire_at_str"),
                })
        http_count = 0
        try:
            http_count = int((ProxyHandler().db.getCount() or {}).get("total", 0))
        except Exception:
            try:
                http_count = len(ProxyHandler().getAll())
            except Exception:
                http_count = 0
        node_stats = count_nodes()
        return {
            "rules": rules,
            "http_count": http_count,
            "node_count": node_stats.get("count", 0),
            "node_by_type": node_stats.get("by_type", {}),
            "active_leases": active,
            "active_lease_count": len(active),
        }
