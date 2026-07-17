# -*- coding: utf-8 -*-
"""FlClash / Clash / 通用节点订阅导入。

支持:
- FlClash 订阅 URL（常见 base64 分享链 或 Clash YAML）
- Clash YAML / JSON
- 分享链: ss/ssr/vmess/vless/trojan/hysteria2/hy2/tuic 等
- 纯文本 HTTP 代理 ip:port

设计:
- 协议节点写入 data/nodes.json（节点池）
- HTTP/HTTPS 代理同时写入原有 Redis 代理池，供 /get 使用
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import uuid
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import requests

from handler.configStore import get_data_dir
from handler.logHandler import LogHandler
from handler.proxyHandler import ProxyHandler
from helper.proxy import Proxy

logger = LogHandler("subscription")
requests.packages.urllib3.disable_warnings()

HTTP_TYPES = {"http", "https"}
SOCKS_TYPES = {"socks5", "socks", "socks5h"}
PROTOCOL_SCHEMES = {
    "ss", "ssr", "shadowsocks", "vmess", "vless", "trojan",
    "hysteria", "hysteria2", "hy2", "tuic", "wireguard", "snell",
    "ssh", "anytls", "mieru",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_subscription_id() -> str:
    return uuid.uuid4().hex[:12]


def get_nodes_file() -> str:
    return os.environ.get("PROXY_POOL_NODES_FILE") or os.path.join(get_data_dir(), "nodes.json")


def _ensure_data_dir():
    d = get_data_dir()
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)


def _safe_b64_decode(text: str) -> Optional[str]:
    raw = (text or "").strip()
    if not raw:
        return None
    compact = re.sub(r"\s+", "", raw)
    # 有些订阅混入前缀
    if "://" in compact and not compact.startswith(("ss://", "ssr://", "vmess://", "vless://", "trojan://")):
        return None
    pad = (-len(compact)) % 4
    if pad:
        compact += "=" * pad
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            data = decoder(compact.encode("utf-8"))
            for enc in ("utf-8", "gbk", "latin-1"):
                try:
                    out = data.decode(enc)
                    if out.strip():
                        return out
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _b64_json(text: str) -> Optional[dict]:
    raw = _safe_b64_decode(text)
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _looks_like_yaml(text: str) -> bool:
    sample = (text or "")[:5000]
    return bool(re.search(r"(?m)^(proxies|proxy-groups|port|mixed-port|mode|dns)\s*:", sample))


def _load_yaml(text: str) -> Optional[Any]:
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except Exception:
        return _parse_clash_proxies_fallback(text)


def _parse_scalar(val: str) -> Any:
    text = (val or "").strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    low = text.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "~", "none"):
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return text
    return text


def _parse_flow_map(text: str) -> Dict[str, Any]:
    body = text.strip()
    if body.startswith("{") and body.endswith("}"):
        body = body[1:-1]
    result: Dict[str, Any] = {}
    parts, buf, in_s = [], [], None
    for ch in body:
        if in_s:
            buf.append(ch)
            if ch == in_s:
                in_s = None
            continue
        if ch in ("'", '"'):
            in_s = ch
            buf.append(ch)
            continue
        if ch == ",":
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        parts.append("".join(buf))
    for part in parts:
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        result[k.strip().strip("'\"")] = _parse_scalar(v)
    return result


def _parse_clash_proxies_fallback(text: str) -> Optional[Dict[str, Any]]:
    if not text or "proxies" not in text:
        return None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    start = -1
    for i, line in enumerate(lines):
        if re.match(r"^proxies\s*:\s*$", line):
            start = i + 1
            break
    if start < 0:
        items = []
        for m in re.finditer(r"\{([^{}]+)\}", text):
            item = _parse_flow_map("{" + m.group(1) + "}")
            if item.get("server") or item.get("type"):
                items.append(item)
        return {"proxies": items} if items else None

    items: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    base_indent = None
    for line in lines[start:]:
        if not line.strip():
            continue
        if re.match(r"^[A-Za-z0-9_-]+\s*:", line) and not line[:1].isspace():
            break
        m_item = re.match(r"^(\s*)-\s*(.*)$", line)
        if m_item:
            if current:
                items.append(current)
            indent, rest = m_item.group(1), m_item.group(2).strip()
            base_indent = len(indent)
            if rest.startswith("{") and "}" in rest:
                current = _parse_flow_map(rest)
            elif rest and ":" in rest:
                k, v = rest.split(":", 1)
                current = {k.strip(): _parse_scalar(v)}
            else:
                current = {}
            continue
        m_field = re.match(r"^(\s*)([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if m_field and current is not None:
            ind = len(m_field.group(1))
            if base_indent is not None and ind <= base_indent:
                items.append(current)
                current = None
                continue
            current[m_field.group(2)] = _parse_scalar(m_field.group(3))
    if current:
        items.append(current)
    return {"proxies": items} if items else None


def _normalize_host_port(server: str, port: Any, username: str = "", password: str = "") -> Optional[str]:
    server = (server or "").strip()
    if not server:
        return None
    try:
        port_i = int(str(port).strip())
    except Exception:
        return None
    if not (1 <= port_i <= 65535):
        return None
    host = ("[%s]" % server) if (":" in server and not server.startswith("[")) else server
    if username:
        return "%s:%s@%s:%s" % (username, password or "", host, port_i)
    return "%s:%s" % (host, port_i)


def _node_id(node: Dict[str, Any]) -> str:
    key = "|".join([
        str(node.get("type") or ""),
        str(node.get("server") or ""),
        str(node.get("port") or ""),
        str(node.get("name") or ""),
        str(node.get("share") or "")[:80],
    ])
    return uuid.uuid5(uuid.NAMESPACE_URL, key).hex[:16]


def _node_from_clash_item(item: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item, dict):
        return None
    ptype = str(item.get("type") or "").strip().lower()
    name = str(item.get("name") or item.get("remarks") or "").strip()
    server = str(item.get("server") or item.get("hostname") or item.get("ip") or "").strip()
    port = item.get("port")
    if not ptype and server and port:
        ptype = "http"
    if not ptype:
        return None
    node = {
        "id": "",
        "name": name or ("%s-%s" % (ptype, server)),
        "type": ptype,
        "server": server,
        "port": port,
        "udp": item.get("udp"),
        "cipher": item.get("cipher") or item.get("method"),
        "password": item.get("password"),
        "uuid": item.get("uuid"),
        "alterId": item.get("alterId"),
        "network": item.get("network"),
        "tls": item.get("tls"),
        "sni": item.get("sni") or item.get("servername"),
        "username": item.get("username") or item.get("user"),
        "source": source,
        "raw": {k: item.get(k) for k in item.keys() if k not in ("password",)},
        "share": "",
        "http_proxy": None,
        "updated_at": _now(),
    }
    if ptype in HTTP_TYPES:
        node["http_proxy"] = _normalize_host_port(
            server, port, str(item.get("username") or ""), str(item.get("password") or "")
        )
    elif ptype in SOCKS_TYPES:
        node["http_proxy"] = None
    node["id"] = _node_id(node)
    return node


def _parse_share_line(line: str, source: str) -> Optional[Dict[str, Any]]:
    s = (line or "").strip()
    if not s or "://" not in s:
        return None
    scheme = s.split("://", 1)[0].lower()
    if scheme not in PROTOCOL_SCHEMES and scheme not in HTTP_TYPES and scheme not in SOCKS_TYPES:
        return None

    name = ""
    if "#" in s:
        s, frag = s.split("#", 1)
        name = unquote(frag)

    try:
        if scheme == "vmess":
            body = s.split("://", 1)[1]
            obj = _b64_json(body) or {}
            node = {
                "name": name or obj.get("ps") or obj.get("name") or "vmess",
                "type": "vmess",
                "server": obj.get("add") or obj.get("server") or "",
                "port": obj.get("port"),
                "uuid": obj.get("id"),
                "alterId": obj.get("aid") or obj.get("alterId"),
                "cipher": obj.get("scy") or obj.get("security") or "auto",
                "network": obj.get("net"),
                "tls": obj.get("tls"),
                "sni": obj.get("sni") or obj.get("host"),
                "source": source,
                "share": line.strip(),
                "raw": obj,
                "http_proxy": None,
                "updated_at": _now(),
            }
            node["id"] = _node_id(node)
            return node

        if scheme in ("ss", "shadowsocks"):
            body = s.split("://", 1)[1]
            # ss://base64(method:pass@host:port) 或 ss://method:pass@host:port
            userinfo = body
            hostport = ""
            method = password = host = ""
            port = None
            if "@" in body:
                left, right = body.rsplit("@", 1)
                hostport = right
                decoded = _safe_b64_decode(left) or left
                if ":" in decoded:
                    method, password = decoded.split(":", 1)
                else:
                    method, password = decoded, ""
            else:
                decoded = _safe_b64_decode(body) or body
                if "@" in decoded:
                    left, right = decoded.rsplit("@", 1)
                    if ":" in left:
                        method, password = left.split(":", 1)
                    hostport = right
            if hostport:
                if hostport.startswith("["):
                    host, port = hostport.rsplit("]:", 1)
                    host = host[1:]
                elif ":" in hostport:
                    host, port = hostport.rsplit(":", 1)
            node = {
                "name": name or ("ss-%s" % host),
                "type": "ss",
                "server": host,
                "port": port,
                "cipher": method,
                "password": password,
                "source": source,
                "share": line.strip(),
                "raw": {},
                "http_proxy": None,
                "updated_at": _now(),
            }
            node["id"] = _node_id(node)
            return node

        # trojan/vless/hysteria2/hy2/tuic/http/socks
        u = urlparse(s)
        host = u.hostname or ""
        port = u.port
        username = unquote(u.username or "")
        password = unquote(u.password or "")
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        ptype = "hysteria2" if scheme == "hy2" else scheme
        node = {
            "name": name or ("%s-%s" % (ptype, host)),
            "type": ptype,
            "server": host,
            "port": port,
            "uuid": username if ptype in ("vless", "tuic") else None,
            "password": password or (username if ptype in ("trojan", "hysteria2") else None),
            "username": username if ptype in HTTP_TYPES.union(SOCKS_TYPES) else None,
            "sni": q.get("sni") or q.get("servername") or q.get("peer"),
            "network": q.get("type") or q.get("network"),
            "tls": q.get("security") or q.get("tls"),
            "source": source,
            "share": line.strip(),
            "raw": q,
            "http_proxy": None,
            "updated_at": _now(),
        }
        if ptype in HTTP_TYPES:
            node["http_proxy"] = _normalize_host_port(host, port, username, password)
        node["id"] = _node_id(node)
        return node
    except Exception as e:
        logger.error("parse share failed: %s (%s)" % (line[:80], e))
        return None


def parse_subscription_text(content: str, source_name: str = "subscription") -> Dict[str, Any]:
    original = content or ""
    text = original.strip()
    result = {
        "source": source_name,
        "format": "unknown",
        "nodes": [],
        "proxies": [],  # http proxies host:port
        "stats": {
            "total_nodes": 0,
            "protocol_nodes": 0,
            "http_nodes": 0,
            "skipped_nodes": 0,
            "invalid_nodes": 0,
            "by_type": {},
        },
        "warnings": [],
    }
    if not text:
        result["warnings"].append("empty content")
        return result

    # base64 whole subscription (FlClash/v2ray common)
    plain_first = text.splitlines()[0].strip() if text.splitlines() else ""
    looks_plain_list = bool(re.search(r"(?m)^(?:\w+://|.+:\d{2,5}\s*$)", text))
    if not _looks_like_yaml(text) and not text.lstrip().startswith(("{", "[", "proxies")) and not looks_plain_list:
        decoded = _safe_b64_decode(text)
        if decoded and decoded.strip() and decoded.strip() != text:
            text = decoded.strip()
            result["format"] = "base64"

    nodes: List[Dict[str, Any]] = []
    http_proxies: List[str] = []

    # Clash YAML / JSON
    data = None
    if _looks_like_yaml(text) or text.lstrip().startswith("proxies"):
        data = _load_yaml(text)
        if data is not None:
            result["format"] = "clash-yaml" if result["format"] == "unknown" else result["format"] + "+clash-yaml"
    if data is None:
        try:
            data = json.loads(text)
            result["format"] = "json" if result["format"] == "unknown" else result["format"] + "+json"
        except Exception:
            data = None

    if isinstance(data, dict) and isinstance(data.get("proxies"), list):
        for item in data.get("proxies") or []:
            node = _node_from_clash_item(item if isinstance(item, dict) else {}, source_name)
            if not node:
                result["stats"]["invalid_nodes"] += 1
                continue
            nodes.append(node)
            if node.get("http_proxy"):
                http_proxies.append(node["http_proxy"])
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                node = _node_from_clash_item(item, source_name)
                if node:
                    nodes.append(node)
                    if node.get("http_proxy"):
                        http_proxies.append(node["http_proxy"])
            elif isinstance(item, str):
                node = _parse_share_line(item, source_name)
                if node:
                    nodes.append(node)
                    if node.get("http_proxy"):
                        http_proxies.append(node["http_proxy"])

    # share links line by line
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "://" in s:
            node = _parse_share_line(s, source_name)
            if node:
                nodes.append(node)
                if node.get("http_proxy"):
                    http_proxies.append(node["http_proxy"])
                if result["format"] == "unknown":
                    result["format"] = "share-links"
                elif "share" not in result["format"]:
                    result["format"] += "+share-links"

    # plain ip:port (avoid matching inside scheme://user:pass@host:port)
    for m in re.finditer(r"(?m)(?<!://)(?<![\w.-])((?:(?:[^:@\s/]+):(?:[^:@\s/]*)@)?(?:\[[0-9a-fA-F:]+\]|\d{1,3}(?:\.\d{1,3}){3}):\d{2,5})\b", text):
        proxy = m.group(1)
        prefix = text[max(0, m.start(1)-12):m.start(1)]
        if "://" in prefix or prefix.endswith("//"):
            continue
        # skip auth@host extracted from share links already handled
        if any(proxy in (n.get("share") or "") for n in nodes):
            continue
        http_proxies.append(proxy)
        host, port = proxy.rsplit(":", 1) if "@" not in proxy else proxy.rsplit("@", 1)[-1].rsplit(":", 1)
        nodes.append({
            "id": _node_id({"type": "http", "server": host, "port": port, "name": proxy, "share": ""}),
            "name": proxy,
            "type": "http",
            "server": host,
            "port": port,
            "source": source_name,
            "share": "",
            "http_proxy": proxy,
            "raw": {},
            "updated_at": _now(),
        })
        if result["format"] == "unknown":
            result["format"] = "text"

    # unique nodes by id
    uniq_nodes = []
    seen = set()
    for n in nodes:
        nid = n.get("id") or _node_id(n)
        n["id"] = nid
        if nid in seen:
            continue
        seen.add(nid)
        uniq_nodes.append(n)
        t = (n.get("type") or "unknown").lower()
        result["stats"]["by_type"][t] = result["stats"]["by_type"].get(t, 0) + 1
        if t in HTTP_TYPES:
            result["stats"]["http_nodes"] += 1
        else:
            result["stats"]["protocol_nodes"] += 1

    uniq_http = []
    seen_h = set()
    for p in http_proxies:
        if p and p not in seen_h:
            seen_h.add(p)
            uniq_http.append(p)

    result["nodes"] = uniq_nodes
    result["proxies"] = uniq_http
    result["stats"]["total_nodes"] = len(uniq_nodes)
    if not uniq_nodes:
        result["warnings"].append("未解析到节点，请确认订阅内容是否为 FlClash/Clash/分享链格式")
    return result


def fetch_subscription_url(url: str, timeout: int = 20) -> Tuple[str, Optional[str]]:
    url = (url or "").strip()
    if not url:
        return "", "empty url"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "", "url scheme must be http/https"

    headers_list = [
        {"User-Agent": "clash.meta/v1.18.0", "Accept": "*/*"},
        {"User-Agent": "ClashforWindows/0.20.39", "Accept": "*/*"},
        {"User-Agent": "FlClash/0.8.0", "Accept": "*/*"},
        {"User-Agent": "clash-verge/v2.0.0", "Accept": "*/*"},
        {"User-Agent": "v2rayN/6.23", "Accept": "*/*"},
        {"User-Agent": "ClashX/1.118.0", "Accept": "*/*"},
        {"User-Agent": "Mozilla/5.0", "Accept": "*/*"},
    ]
    last_err = "download failed"
    session = requests.Session()
    session.trust_env = False  # 忽略坏掉的 HTTP_PROXY=127.0.0.1:9
    # 也清理会话级代理，防止环境污染
    session.proxies = {"http": None, "https": None}
    for headers in headers_list:
        try:
            resp = session.get(url, headers=headers, timeout=timeout, verify=False, allow_redirects=True)
            if resp.status_code >= 400:
                last_err = "http status %s" % resp.status_code
                continue
            content = resp.text or ""
            if not content.strip():
                # 有些服务把内容放在 content-disposition 附件，已在 text；再尝试 content bytes
                try:
                    content = resp.content.decode("utf-8", "ignore")
                except Exception:
                    content = ""
            if not content.strip():
                last_err = "empty response"
                continue
            low = content[:500].lower()
            if "<html" in low and ("522" in content or "cloudflare" in low or "just a moment" in low):
                last_err = "upstream html error/cloudflare"
                continue
            return content, None
        except Exception as e:
            last_err = str(e)
            continue
    return "", last_err


def _is_valid_proxy_endpoint(proxy: str) -> bool:
    if not proxy or not isinstance(proxy, str):
        return False
    text = proxy.strip()
    if "@" in text:
        auth, hostport = text.rsplit("@", 1)
        if ":" not in auth:
            return False
    else:
        hostport = text
    if hostport.startswith("["):
        if "]:" not in hostport:
            return False
        host, port = hostport.rsplit("]:", 1)
        host = host[1:]
    else:
        if hostport.count(":") != 1:
            return False
        host, port = hostport.split(":", 1)
    if not host.strip():
        return False
    try:
        port_i = int(port)
    except Exception:
        return False
    return 1 <= port_i <= 65535


def import_proxies_to_pool(proxies: Iterable[str], source: str = "subscription") -> Dict[str, int]:
    handler = ProxyHandler()
    added = updated = invalid = 0
    for item in proxies:
        proxy_str = (item or "").strip()
        if not proxy_str or not _is_valid_proxy_endpoint(proxy_str):
            invalid += 1
            continue
        obj = Proxy(proxy_str, source=source, last_status=True, last_time=_now(), protocol="http")
        if handler.exists(obj):
            handler.put(obj)
            updated += 1
        else:
            handler.put(obj)
            added += 1
    return {"added": added, "updated": updated, "invalid": invalid, "total": added + updated}


def import_nodes_to_pool(nodes: Iterable[Dict[str, Any]], source: str = "subscription") -> Dict[str, int]:
    """把订阅解析出的节点写入 Redis 代理池。

    - http/https 节点: 以 host:port 作为 key
    - vmess/ss/trojan/... 协议节点: 以 node:<id> 作为 key，并保存协议元数据
    """
    handler = ProxyHandler()
    added = updated = invalid = 0
    for n in nodes or []:
        if not isinstance(n, dict):
            invalid += 1
            continue
        ptype = str(n.get("type") or n.get("protocol") or "").lower().strip()
        name = str(n.get("name") or "")
        server = str(n.get("server") or "")
        port = n.get("port")
        share = str(n.get("share") or "")
        node_id = str(n.get("id") or "")
        source_name = str(n.get("source") or source or "subscription")

        if ptype in ("http", "https") or n.get("http_proxy"):
            proxy_key = str(n.get("http_proxy") or _normalize_host_port(server, port, str(n.get("username") or ""), str(n.get("password") or "")) or "")
            if not proxy_key or not _is_valid_proxy_endpoint(proxy_key):
                invalid += 1
                continue
            obj = Proxy(
                proxy_key,
                source=source_name,
                last_status=True,
                last_time=_now(),
                https=(ptype == "https"),
                protocol=ptype or "http",
                name=name,
                share=share,
                server=server,
                port=port,
                node_id=node_id,
                cipher=str(n.get("cipher") or ""),
                password=str(n.get("password") or ""),
                uuid=str(n.get("uuid") or ""),
                network=str(n.get("network") or ""),
                tls=str(n.get("tls") or ""),
                sni=str(n.get("sni") or ""),
                username=str(n.get("username") or ""),
            )
        else:
            if not node_id:
                node_id = _node_id(n)
            # 协议节点必须能定位 server:port，否则跳过
            if not server or port in (None, ""):
                # 尝试从 share 解析
                if share and "://" in share:
                    try:
                        parsed = _parse_share_line(share, source_name)
                        if parsed:
                            server = str(parsed.get("server") or server)
                            port = parsed.get("port", port)
                            ptype = str(parsed.get("type") or ptype)
                            name = str(parsed.get("name") or name)
                            node_id = str(parsed.get("id") or node_id)
                    except Exception:
                        pass
            if not server or port in (None, ""):
                invalid += 1
                continue
            proxy_key = "node:%s" % node_id
            obj = Proxy(
                proxy_key,
                source=source_name,
                last_status=True,
                last_time=_now(),
                https=True,
                protocol=ptype or "unknown",
                name=name,
                share=share,
                server=server,
                port=port,
                node_id=node_id,
                cipher=str(n.get("cipher") or ""),
                password=str(n.get("password") or ""),
                uuid=str(n.get("uuid") or ""),
                network=str(n.get("network") or ""),
                tls=str(n.get("tls") or ""),
                sni=str(n.get("sni") or ""),
                username=str(n.get("username") or ""),
            )

        if handler.exists(obj):
            handler.put(obj)
            updated += 1
        else:
            handler.put(obj)
            added += 1
    return {"added": added, "updated": updated, "invalid": invalid, "total": added + updated}


def save_nodes(nodes: List[Dict[str, Any]], merge: bool = True) -> Dict[str, int]:
    _ensure_data_dir()
    path = get_nodes_file()
    existing: List[Dict[str, Any]] = []
    if merge and os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                existing = raw["items"]
            elif isinstance(raw, list):
                existing = raw
        except Exception:
            existing = []
    by_id = {str(x.get("id")): x for x in existing if isinstance(x, dict) and x.get("id")}
    added = updated = 0
    for n in nodes:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id") or _node_id(n))
        n["id"] = nid
        n["updated_at"] = _now()
        if nid in by_id:
            old = dict(by_id[nid])
            old.update(n)
            by_id[nid] = old
            updated += 1
        else:
            by_id[nid] = n
            added += 1
    items = list(by_id.values())
    payload = {"updated_at": _now(), "count": len(items), "items": items}
    fd, tmp = tempfile.mkstemp(prefix="nodes_", suffix=".json", dir=get_data_dir())
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
    return {"added": added, "updated": updated, "total": len(items), "file": path}


def list_nodes(limit: int = 500, node_type: str = "") -> Dict[str, Any]:
    path = get_nodes_file()
    items: List[Dict[str, Any]] = []
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and isinstance(raw.get("items"), list):
                items = raw["items"]
            elif isinstance(raw, list):
                items = raw
        except Exception:
            items = []
    if node_type:
        nt = node_type.lower().strip()
        items = [x for x in items if str(x.get("type") or "").lower() == nt]
    # hide secrets in list
    safe = []
    for x in items[: max(1, min(int(limit or 500), 5000))]:
        y = dict(x)
        if y.get("password"):
            y["password"] = "********"
        if y.get("uuid"):
            y["uuid"] = str(y["uuid"])[:8] + "********"
        safe.append(y)
    by_type: Dict[str, int] = {}
    for x in items:
        t = str(x.get("type") or "unknown").lower()
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "file": path,
        "count": len(items),
        "by_type": by_type,
        "items": safe,
    }


def import_from_text(
    content: str,
    source_name: str = "subscription",
    write_pool: bool = True,
    save_nodes_flag: bool = True,
) -> Dict[str, Any]:
    parsed = parse_subscription_text(content, source_name=source_name)
    pool_stats = {"added": 0, "updated": 0, "invalid": 0, "total": 0}
    node_stats = {"added": 0, "updated": 0, "total": 0, "file": get_nodes_file()}
    if save_nodes_flag and parsed["nodes"]:
        node_stats = save_nodes(parsed["nodes"], merge=True)
    # 订阅节点写入代理池：协议节点 + HTTP 节点
    if write_pool:
        if parsed.get("nodes"):
            pool_stats = import_nodes_to_pool(parsed["nodes"], source=source_name)
        elif parsed.get("proxies"):
            pool_stats = import_proxies_to_pool(parsed["proxies"], source=source_name)
    parsed["pool"] = pool_stats
    parsed["node_store"] = node_stats
    parsed["fetched_at"] = _now()
    return parsed


def import_from_url(
    url: str,
    source_name: str = "",
    write_pool: bool = True,
    save_nodes_flag: bool = True,
) -> Dict[str, Any]:
    name = source_name.strip() if source_name else ""
    if not name:
        host = urlparse(url).hostname or "subscription"
        name = "sub-%s" % host
    content, err = fetch_subscription_url(url)
    if err:
        return {
            "source": name,
            "url": url,
            "error": err,
            "nodes": [],
            "proxies": [],
            "stats": {},
            "pool": {"added": 0, "updated": 0, "invalid": 0, "total": 0},
            "node_store": {"added": 0, "updated": 0, "total": 0},
            "fetched_at": _now(),
            "warnings": [err],
        }
    result = import_from_text(
        content,
        source_name=name,
        write_pool=write_pool,
        save_nodes_flag=save_nodes_flag,
    )
    result["url"] = url
    return result


def _load_all_nodes() -> List[Dict[str, Any]]:
    path = get_nodes_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict) and isinstance(raw.get("items"), list):
            return [x for x in raw["items"] if isinstance(x, dict)]
        if isinstance(raw, list):
            return [x for x in raw if isinstance(x, dict)]
    except Exception:
        return []
    return []


def _public_node(node: Dict[str, Any], mask_secrets: bool = False) -> Dict[str, Any]:
    y = dict(node or {})
    if mask_secrets:
        if y.get("password"):
            y["password"] = "********"
        if y.get("uuid"):
            y["uuid"] = str(y["uuid"])[:8] + "********"
    # 统一输出字段，方便外部调用
    return {
        "id": y.get("id"),
        "name": y.get("name"),
        "type": y.get("type"),
        "server": y.get("server"),
        "port": y.get("port"),
        "share": y.get("share") or "",
        "http_proxy": y.get("http_proxy"),
        "source": y.get("source"),
        "updated_at": y.get("updated_at"),
        "cipher": y.get("cipher"),
        "network": y.get("network"),
        "tls": y.get("tls"),
        "sni": y.get("sni"),
        "uuid": y.get("uuid"),
        "password": y.get("password"),
        "username": y.get("username"),
        "raw": y.get("raw") or {},
    }


def get_node(node_type: str = "", mask_secrets: bool = False) -> Optional[Dict[str, Any]]:
    """随机返回一个协议节点（可按 type 过滤：vmess/ss/trojan/...）"""
    import random
    items = _load_all_nodes()
    if node_type:
        nt = node_type.lower().strip()
        items = [x for x in items if str(x.get("type") or "").lower() == nt]
    if not items:
        return None
    return _public_node(random.choice(items), mask_secrets=mask_secrets)


def pop_node(node_type: str = "", mask_secrets: bool = False) -> Optional[Dict[str, Any]]:
    """返回并删除一个节点"""
    import random
    items = _load_all_nodes()
    if node_type:
        nt = node_type.lower().strip()
        candidates = [x for x in items if str(x.get("type") or "").lower() == nt]
    else:
        candidates = items
    if not candidates:
        return None
    chosen = random.choice(candidates)
    cid = str(chosen.get("id") or "")
    remain = [x for x in items if str(x.get("id") or "") != cid]
    _write_nodes(remain)
    return _public_node(chosen, mask_secrets=mask_secrets)


def delete_node(node_id: str = "", share: str = "") -> bool:
    items = _load_all_nodes()
    if not items:
        return False
    remain = []
    deleted = False
    for x in items:
        hit = False
        if node_id and str(x.get("id") or "") == str(node_id):
            hit = True
        if share and str(x.get("share") or "") == str(share):
            hit = True
        if hit:
            deleted = True
            continue
        remain.append(x)
    if deleted:
        _write_nodes(remain)
    return deleted


def count_nodes() -> Dict[str, Any]:
    items = _load_all_nodes()
    by_type: Dict[str, int] = {}
    for x in items:
        t = str(x.get("type") or "unknown").lower()
        by_type[t] = by_type.get(t, 0) + 1
    return {
        "count": len(items),
        "by_type": by_type,
        "file": get_nodes_file(),
    }


def _write_nodes(items: List[Dict[str, Any]]) -> None:
    _ensure_data_dir()
    path = get_nodes_file()
    payload = {"updated_at": _now(), "count": len(items), "items": items}
    fd, tmp = tempfile.mkstemp(prefix="nodes_", suffix=".json", dir=get_data_dir())
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

