from pathlib import Path
path = Path('api/proxyApi.py')
text = path.read_text(encoding='utf-8')
old = '''    if result.get("code") == 404:
        return result, 404
    result["endpoint"] = {
        "slug": ep.get("slug"),
        "name": ep.get("name"),
        "path": ep.get("path"),
        "rules": {
            "strategy": override.get("strategy"),
            "pool": override.get("pool"),
            "lease_seconds": override.get("lease_seconds"),
            "prefer_https": override.get("prefer_https"),
            "default_node_type": override.get("default_node_type"),
        },
    }
    return result
'''
new = '''    result["endpoint"] = {
        "slug": ep.get("slug"),
        "name": ep.get("name"),
        "path": ep.get("path"),
        "rules": {
            "strategy": override.get("strategy"),
            "pool": override.get("pool"),
            "lease_seconds": override.get("lease_seconds"),
            "prefer_https": override.get("prefer_https"),
            "default_node_type": override.get("default_node_type"),
            "response_format": override.get("response_format") or override.get("format") or "json",
        },
    }
    return _dispatch_response(result, payload=payload, rules=override)
'''
if old not in text:
    raise SystemExit('open tail not found')
text = text.replace(old, new)
path.write_text(text, encoding='utf-8')
print('open_endpoint patched')
# sanity
assert '_dispatch_response' in text
assert 'format=json|legacy|simple|text|url' in text
print('ok')
