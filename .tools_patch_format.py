from pathlib import Path

path = Path('api/proxyApi.py')
text = path.read_text(encoding='utf-8')

helper = '''
def _request_value(payload, key, default=""):
    if key in request.args and request.args.get(key) not in (None, ""):
        return request.args.get(key)
    if isinstance(payload, dict) and key in payload and payload.get(key) not in (None, ""):
        return payload.get(key)
    return default


def _normalize_format(raw):
    fmt = str(raw or "json").strip().lower()
    aliases = {
        "default": "json",
        "full": "json",
        "flat": "json",
        "compatible": "json",
        "legacy": "legacy",
        "get": "legacy",
        "classic": "legacy",
        "old": "legacy",
        "simple": "simple",
        "basic": "simple",
        "min": "simple",
        "minimal": "simple",
        "text": "text",
        "plain": "text",
        "raw": "text",
        "hostport": "text",
        "url": "url",
        "proxy_url": "url",
        "uri": "url",
    }
    return aliases.get(fmt, fmt if fmt in ("json", "legacy", "simple", "text", "url") else "json")


def _resolve_response_format(payload=None, rules=None):
    payload = payload or {}
    rules = rules or {}
    raw = _request_value(payload, "format", None)
    if raw in (None, ""):
        raw = _request_value(payload, "fmt", None)
    if raw in (None, ""):
        raw = rules.get("response_format") or rules.get("format")
    if raw in (None, ""):
        accept = (request.headers.get("Accept") or "").lower()
        if "text/plain" in accept:
            raw = "text"
    return _normalize_format(raw)


def _format_proxy_result(result, fmt="json", include_meta=True):
    """Make dispatcher results easy for third-party clients.

    Formats:
      - json   : flattened fields + nested item (default, strongest compatibility)
      - legacy : classic /get style object
      - simple : minimal ok/proxy/proxy_url/proxies
      - text   : plain host:port
      - url    : plain http(s)/socks URL
    """
    fmt = _normalize_format(fmt)
    if not isinstance(result, dict):
        return result

    item = result.get("item") if isinstance(result.get("item"), dict) else None
    code = result.get("code", 0)
    has_proxy = bool(item and (item.get("proxy") or item.get("proxy_url")))

    if fmt in ("text", "url"):
        if code not in (0, None) or not has_proxy:
            body = ""
            return body, 404 if code == 404 else 200, {"Content-Type": "text/plain; charset=utf-8"}
        body = str(item.get("proxy_url") if fmt == "url" else item.get("proxy") or item.get("proxy_url") or "")
        return body, 200, {"Content-Type": "text/plain; charset=utf-8"}

    if fmt == "legacy":
        if has_proxy:
            data = dict(item)
            if include_meta:
                if result.get("client_key"):
                    data["client_key"] = result.get("client_key")
                if result.get("lease_remain_seconds") is not None:
                    data["lease_remain_seconds"] = result.get("lease_remain_seconds")
            return data
        return {"code": code if code not in (None,) else 0, "src": result.get("src") or "no proxy"}

    if fmt == "simple":
        data = {
            "ok": bool(has_proxy and code in (0, None)),
            "code": code if code not in (None,) else 0,
            "src": result.get("src") or ("ok" if has_proxy else "no proxy"),
            "proxy": (item or {}).get("proxy") if item else None,
            "proxy_url": (item or {}).get("proxy_url") if item else None,
            "proxies": (item or {}).get("proxies") if item else {},
            "https": (item or {}).get("https") if item else None,
            "type": ((item or {}).get("type") or (item or {}).get("protocol")) if item else None,
            "latency_ms": (item or {}).get("latency_ms") if item else None,
        }
        if include_meta:
            data["client_key"] = result.get("client_key")
            data["lease_seconds"] = result.get("lease_seconds")
            data["lease_remain_seconds"] = result.get("lease_remain_seconds")
            data["expire_at"] = result.get("expire_at")
            data["strategy"] = result.get("strategy")
            data["pool"] = result.get("pool")
            data["mode"] = result.get("mode")
        return data

    data = dict(result)
    if item:
        for key in (
            "proxy", "proxy_url", "http", "https_proxy", "proxies", "https",
            "latency_ms", "last_status", "region", "source", "protocol", "type",
            "name", "share", "server", "port", "node_id", "id",
        ):
            if key in item and key not in data:
                data[key] = item.get(key)
        data.setdefault("ok", True)
    else:
        data.setdefault("ok", False)
        data.setdefault("proxy", None)
        data.setdefault("proxy_url", None)
        data.setdefault("proxies", {})
    return data


def _dispatch_response(result, payload=None, rules=None):
    fmt = _resolve_response_format(payload=payload, rules=rules)
    formatted = _format_proxy_result(result, fmt=fmt)
    if isinstance(formatted, tuple):
        return formatted
    code = result.get("code", 0) if isinstance(result, dict) else 0
    if code == 404:
        return formatted, 404
    return formatted


'''

marker = 'def require_api_token(func):'
if '_format_proxy_result' not in text:
    if marker not in text:
        raise SystemExit('marker not found for helper insert')
    text = text.replace(marker, helper + marker, 1)

text = text.replace(
    '{"url": "/v1/proxy", "params": "strategy,pool,lease,type,id,proxy,client_id,rotate", "desc": "unified proxy acquire (round_robin/lease)"},',
    '{"url": "/v1/proxy", "params": "strategy,pool,lease,type,id,proxy,client_id,rotate,format", "desc": "unified proxy acquire; format=json|legacy|simple|text|url"},',
)
text = text.replace(
    '{"url": "/v1/proxy/current", "params": "client_id", "desc": "current leased proxy"},',
    '{"url": "/v1/proxy/current", "params": "client_id,format", "desc": "current leased proxy; format=json|legacy|simple|text|url"},',
)
text = text.replace(
    '{"url": "/open/<slug>", "params": "client_id,rotate,...", "desc": "custom endpoint with independent rules"},',
    '{"url": "/open/<slug>", "params": "client_id,rotate,format,...", "desc": "custom endpoint; format=json|legacy|simple|text|url"},',
)

old_v1 = '''    result = acquire(
        pool=str(_get("pool", "") or ""),
        strategy=str(_get("strategy", "") or ""),
        lease_seconds=lease_seconds,
        node_type=str(_get("type", "") or ""),
        prefer_https=prefer_https,
        proxy=str(_get("proxy", "") or ""),
        node_id=str(_get("id", "") or ""),
        share=str(_get("share", "") or ""),
        client_id=str(_get("client_id", "") or ""),
        force_rotate=rotate,
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )
    code = result.get("code", 0)
    if code == 404:
        return result, 404
    return result
'''
new_v1 = '''    result = acquire(
        pool=str(_get("pool", "") or ""),
        strategy=str(_get("strategy", "") or ""),
        lease_seconds=lease_seconds,
        node_type=str(_get("type", "") or ""),
        prefer_https=prefer_https,
        proxy=str(_get("proxy", "") or ""),
        node_id=str(_get("id", "") or ""),
        share=str(_get("share", "") or ""),
        client_id=str(_get("client_id", "") or ""),
        force_rotate=rotate,
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )
    return _dispatch_response(result, payload=payload)
'''
if old_v1 not in text:
    raise SystemExit('v1 acquire block not found')
text = text.replace(old_v1, new_v1)

old_cur = '''def v1_proxy_current():
    from helper.proxyDispatcher import current
    return current(
        client_id=request.args.get("client_id", ""),
        client_key=request.args.get("client_key", ""),
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )
'''
new_cur = '''def v1_proxy_current():
    from helper.proxyDispatcher import current
    result = current(
        client_id=request.args.get("client_id", ""),
        client_key=request.args.get("client_key", ""),
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )
    return _dispatch_response(result, payload=request.args)
'''
if old_cur not in text:
    raise SystemExit('v1 current block not found')
text = text.replace(old_cur, new_cur)

# Patch open_endpoint: replace trailing result handling
idx = text.find('def open_endpoint(slug):')
if idx < 0:
    raise SystemExit('open_endpoint not found')
marker_start = text.find('if result.get("code") == 404:', idx)
if marker_start < 0:
    raise SystemExit('open return start not found')
# find next function after open_endpoint
next_def = text.find('\n@app.route', marker_start + 1)
next_def2 = text.find('\ndef ', marker_start + 1)
ends = [x for x in (next_def, next_def2) if x > 0]
end = min(ends) if ends else len(text)
old_tail = text[marker_start:end]
print('OLD TAIL START:')
print(old_tail[:500])
print('---')
# Keep endpoint enrichment if present, then format
# Read full tail carefully
print('OLD TAIL FULL LEN', len(old_tail))
print(old_tail)
path.write_text(text, encoding='utf-8')
print('helpers and v1 patched; open_endpoint tail printed for next step')
