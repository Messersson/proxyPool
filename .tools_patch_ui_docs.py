from pathlib import Path

# --- admin.html ---
html_path = Path('api/static/admin.html')
html = html_path.read_text(encoding='utf-8')

marker = '<div class="field"><label for="endpointNodeType">'
insert = '''<div class="field"><label for="endpointResponseFormat">返回格式</label>
              <select id="endpointResponseFormat">
                <option value="json" selected>兼容JSON(json)</option>
                <option value="legacy">经典/get风格(legacy)</option>
                <option value="simple">精简JSON(simple)</option>
                <option value="text">纯文本host:port(text)</option>
                <option value="url">纯文本URL(url)</option>
              </select>
              <div class="help">给其他开发者用时建议 json/legacy/text</div>
            </div>
            '''
if 'endpointResponseFormat' not in html:
    if marker not in html:
        raise SystemExit('endpointNodeType field not found')
    html = html.replace(marker, insert + marker, 1)

old_rules = '''          prefer_low_latency: document.getElementById("endpointPreferLowLatency").value === "true",
          skip_timeout: document.getElementById("endpointSkipTimeout").value === "true",
          max_latency_ms: Number(document.getElementById("endpointMaxLatency").value || 0),
        }
'''
new_rules = '''          prefer_low_latency: document.getElementById("endpointPreferLowLatency").value === "true",
          skip_timeout: document.getElementById("endpointSkipTimeout").value === "true",
          max_latency_ms: Number(document.getElementById("endpointMaxLatency").value || 0),
          response_format: document.getElementById("endpointResponseFormat").value || "json",
        }
'''
if old_rules not in html:
    raise SystemExit('saveEndpoint rules block not found')
html = html.replace(old_rules, new_rules, 1)

# show format in table if possible
old_td = '''          <td>${escapeHtml(r.pool || "-")}</td>
          <td>${escapeHtml(r.lease_seconds ?? "-")}</td>
'''
new_td = '''          <td>${escapeHtml(r.pool || "-")}</td>
          <td>${escapeHtml(r.response_format || r.format || "json")}</td>
          <td>${escapeHtml(r.lease_seconds ?? "-")}</td>
'''
if old_td in html and 'r.response_format || r.format' not in html:
    html = html.replace(old_td, new_td, 1)
    html = html.replace(
        '<thead><tr><th>名称</th><th>完整调用地址</th><th>策略</th><th>池</th><th>租约(秒)</th><th>低延迟优先</th><th>操作</th></tr></thead>',
        '<thead><tr><th>名称</th><th>完整调用地址</th><th>策略</th><th>池</th><th>格式</th><th>租约(秒)</th><th>低延迟优先</th><th>操作</th></tr></thead>',
        1,
    )
    # also handle if encoding differs - try a looser replace of thead containing endpointTableBody nearby
    if 'response_format || r.format' in html and '格式' not in html:
        # leave as is if Chinese header replace failed; table still works
        pass

html_path.write_text(html, encoding='utf-8')
print('admin.html updated')

# --- docs ---
docs = Path('docs/api.md')
d = docs.read_text(encoding='utf-8')
section = '''

## 对外接口返回格式（兼容性说明）

默认 `/v1/proxy` 与 `/open/<slug>` 现在会把代理字段**扁平化到顶层**，同时保留 `item`，方便不同开发者接入：

```json
{
  "code": 0,
  "ok": true,
  "proxy": "1.2.3.4:8080",
  "proxy_url": "http://1.2.3.4:8080",
  "proxies": {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"},
  "item": {"proxy": "1.2.3.4:8080", "proxy_url": "http://1.2.3.4:8080", "...": "..."},
  "client_key": "cid:app1",
  "lease_remain_seconds": 280
}
```

如果对方项目只认老式 `/get`，或只想拿纯文本，可用 `format` 参数（`/v1/proxy`、`/v1/proxy/current`、`/open/<slug>` 都支持）：

| format | 返回 | 适合场景 |
|--------|------|----------|
| `json`（默认） | 扁平字段 + `item` | 通用，推荐 |
| `legacy` | 与 `/get` 类似的对象 | 兼容旧爬虫/SDK |
| `simple` | 精简 JSON | 移动端/轻量客户端 |
| `text` | 纯文本 `host:port` | 脚本/命令行 |
| `url` | 纯文本 `http://host:port` | 直接塞环境变量 |

示例：

```bash
# 默认兼容 JSON（顶层直接有 proxy）
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1"

# 兼容经典 /get 风格
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&format=legacy"

# 纯文本，方便 shell
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&format=text"
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&format=url"

# 自定义接口也可固定格式
curl -X POST http://127.0.0.1:5010/admin/endpoints/ \
  -H "Content-Type: application/json" \
  -d '{"slug":"crawler-a","name":"爬虫A","rules":{"strategy":"round_robin","pool":"http","response_format":"legacy"}}'
```

Python 最稳妥写法：

```python
import requests

def get_proxy(base="http://127.0.0.1:5010", client_id="app1"):
    data = requests.get(f"{base}/v1/proxy", params={"client_id": client_id}, timeout=5).json()
    # 兼容：顶层 proxy / item.proxy / 老字段
    proxy = data.get("proxy") or (data.get("item") or {}).get("proxy")
    proxies = data.get("proxies") or (data.get("item") or {}).get("proxies")
    if not proxies and data.get("proxy_url"):
        proxies = {"http": data["proxy_url"], "https": data["proxy_url"]}
    return proxy, proxies
```
'''
if '对外接口返回格式（兼容性说明）' not in d:
    # insert before 代理返回格式 section if present, else append
    key = '## 代理返回格式'
    if key in d:
        d = d.replace(key, section + '\n' + key, 1)
    else:
        d = d.rstrip() + section + '\n'
    docs.write_text(d, encoding='utf-8')
    print('docs updated')
else:
    print('docs already has section')
