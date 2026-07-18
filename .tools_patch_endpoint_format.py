from pathlib import Path

# endpointStore
p = Path('handler/endpointStore.py')
t = p.read_text(encoding='utf-8')
old = '''        "prefer_low_latency": True,
    }
'''
new = '''        "prefer_low_latency": True,
        "response_format": "json",   # json | legacy | simple | text | url
    }
'''
if old not in t:
    raise SystemExit('default rules block missing')
t = t.replace(old, new, 1)
old2 = '''    rules["prefer_low_latency"] = bool(rules.get("prefer_low_latency", True))
    return rules
'''
new2 = '''    rules["prefer_low_latency"] = bool(rules.get("prefer_low_latency", True))
    fmt = str(rules.get("response_format") or rules.get("format") or "json").strip().lower()
    aliases = {
        "default": "json", "full": "json", "flat": "json", "compatible": "json",
        "legacy": "legacy", "get": "legacy", "classic": "legacy", "old": "legacy",
        "simple": "simple", "basic": "simple", "min": "simple", "minimal": "simple",
        "text": "text", "plain": "text", "raw": "text", "hostport": "text",
        "url": "url", "proxy_url": "url", "uri": "url",
    }
    fmt = aliases.get(fmt, fmt)
    if fmt not in ("json", "legacy", "simple", "text", "url"):
        raise ValueError("response_format must be json|legacy|simple|text|url")
    rules["response_format"] = fmt
    rules.pop("format", None)
    return rules
'''
if old2 not in t:
    raise SystemExit('normalize tail missing')
t = t.replace(old2, new2, 1)
p.write_text(t, encoding='utf-8')
print('endpointStore updated')

# allow response_format in admin_endpoints flat rules and open override
api = Path('api/proxyApi.py')
at = api.read_text(encoding='utf-8')
at = at.replace(
'''            for k in (
                "strategy", "pool", "lease_seconds", "prefer_https", "default_node_type",
                "fixed_proxy", "fixed_node_id", "fixed_share", "token",
                "skip_timeout", "max_latency_ms", "prefer_low_latency",
            ):''',
'''            for k in (
                "strategy", "pool", "lease_seconds", "prefer_https", "default_node_type",
                "fixed_proxy", "fixed_node_id", "fixed_share", "token",
                "skip_timeout", "max_latency_ms", "prefer_low_latency",
                "response_format", "format",
            ):'''
)
at = at.replace(
    'for k in ("strategy", "pool", "default_node_type", "fixed_proxy", "fixed_node_id", "fixed_share"):',
    'for k in ("strategy", "pool", "default_node_type", "fixed_proxy", "fixed_node_id", "fixed_share", "response_format", "format"):'
)
api.write_text(at, encoding='utf-8')
print('proxyApi keys updated')
