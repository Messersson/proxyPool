# API 使用

## 接口列表

启动 ProxyPool 的 `server` 后会提供如下 HTTP 接口：

| 接口 | 方法 | 说明 | 参数 |
|------|------|------|------|
| `/` | GET | 统一控制台前端面板 | 无 |
| `/health` | GET | 健康检查（默认不鉴权） | 无 |
| `/admin` | GET | 统一控制台（与 `/`、`/admin/config` 同页） | 无 |
| `/api` | GET | JSON 接口目录 | 无 |
| `/admin/fetchers` | GET | 启用中的代理源列表 | 无 |
| `/admin/config/api` | GET/POST | 读取/保存运行时配置 | POST JSON 配置字段 |
| `/get` | GET | 随机返回一个代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/pop` | GET | 返回并删除一个代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/all` | GET | 返回所有代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/count` | GET | 返回代理数量统计 | 无 |
| `/delete` | GET/POST | 删除指定代理 | GET: `?proxy=host:port`；POST JSON: `{"proxy":"host:port"}` |
| `/admin/subscriptions` | GET/POST/DELETE | 管理 FlClash/Clash 订阅 | POST: `{"name","url","enabled"}` |
| `/admin/subscriptions/import` | POST | 导入订阅链接或内容 | `url` 或 `content` |
| `/admin/nodes` | GET | 管理端查看节点库 | `type`, `limit` |
| `/node/get` | GET | 随机返回一个协议节点 | 可选 `?type=vmess|ss|trojan` |
| `/node/pop` | GET | 返回并删除一个协议节点 | 可选 `?type=...` |
| `/node/all` | GET | 返回节点列表 | 可选 `type/limit/mask` |
| `/node/count` | GET | 节点池统计 | 无 |
| `/node/delete` | GET/POST | 删除节点 | `id` 或 `share` |

## 统一控制台

打开 http://127.0.0.1:5010/（或 /admin）进入统一前端面板：总览、代理池、代理源、配置、API 一览。

## 网页配置保存

在统一控制台的“配置”页修改表单后点击「保存配置」。

配置会写入 `data/runtime_config.json`，并立即热加载到当前 API 进程。环境变量覆盖的字段会显示为锁定，不可在网页改写。

## 鉴权（可选）

当 `setting.py` 或环境变量 `API_TOKEN` 非空时，业务接口需要携带 Token：

- 请求头 `X-API-Token: <token>`
- 或 `Authorization: Bearer <token>`
- 或 Query `?token=<token>`

`/`、`/admin` 与 `/health` 默认不鉴权；业务接口与配置保存仍受 API_TOKEN 控制。

## 调用示例

### 在爬虫中使用

通过调用 API 接口来使用代理池：

```python
import requests

BASE = "http://127.0.0.1:5010"
HEADERS = {
    # 若启用了 API_TOKEN，取消下一行注释：
    # "X-API-Token": "your-token",
}


def get_proxy():
    return requests.get(BASE + "/get/", headers=HEADERS).json()


def delete_proxy(proxy):
    # 推荐 POST；GET 仍兼容
    return requests.post(
        BASE + "/delete/",
        headers=HEADERS,
        json={"proxy": proxy},
    ).json()


def get_html():
    retry_count = 5
    proxy = get_proxy().get("proxy")
    while retry_count > 0:
        try:
            html = requests.get(
                "http://www.example.com",
                proxies={
                    "http": "http://{}".format(proxy),
                    "https": "https://{}".format(proxy),
                },
            )
            return html
        except Exception:
            retry_count -= 1
            delete_proxy(proxy)
    return None
```

本例中在本地 `127.0.0.1` 启动端口为 `5010` 的 `server`，使用 `/get` 接口获取代理，`/delete` 删除代理。

### 获取 HTTPS 代理

```python
# 只获取支持 HTTPS 的代理
proxy = requests.get("http://127.0.0.1:5010/get/?type=https").json()
```

### 获取代理统计

```python
# 返回代理数量、类型分布、来源分布
stats = requests.get("http://127.0.0.1:5010/count/").json()
# 示例返回: {"http_type": {"http": 10, "https": 5}, "source": {"freeProxy01": 8, "freeProxy02": 7}, "count": 15}
```

### 健康检查

```python
health = requests.get("http://127.0.0.1:5010/health/").json()
# 示例: {"status": "ok", "count": 15, "https": 5}
```

## 直接读取数据库

除了通过 API 接口，也可以直接读取数据库获取代理。目前支持两种数据库：Redis 和 SSDB。

- **Redis**：存储结构为 hash，hash name 为配置项中的 `TABLE_NAME`（默认 `use_proxy`）；HTTPS 额外维护 `{TABLE_NAME}:https` 集合索引
- **SSDB**：存储结构为 hash，hash name 为配置项中的 `TABLE_NAME`

可以在代码中自行读取数据库获取代理列表。


## 协议节点池（Clash / FlClash）

导入 FlClash/Clash 订阅后，`vmess/ss/trojan/vless` 等协议节点会进入节点池（`data/nodes.json`）。

### 获取一个节点

```bash
curl http://127.0.0.1:5010/node/get/
curl "http://127.0.0.1:5010/node/get/?type=vmess"
```

Python:

```python
import requests
node = requests.get("http://127.0.0.1:5010/node/get/", timeout=5).json()
# node["type"], node["server"], node["port"], node["share"]
```

说明：
- `/get` 仍然只返回 HTTP/HTTPS 代理（给爬虫直接用）
- `/node/get` 返回协议节点元数据（给客户端/自建转发用）
- 订阅导入入口：控制台「订阅」页，或 `POST /admin/subscriptions/import`


## 统一对外代理接口（推荐）

`/v1/proxy` 统一获取 HTTP 代理或协议节点，并内置调用规则：

- `strategy=round_robin`：轮询
- `strategy=random`：随机
- `strategy=sticky`：粘性（配合租约）
- `lease=秒`：同一 `client_id` 在租约内固定同一代理；到期自动换
- `rotate=1`：强制切换下一个
- `proxy=` / `id=` / `share=`：指定调用某个代理/节点

### 获取（轮询 + 租约）

```bash
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&strategy=round_robin&lease=300"
```

### 强制换下一个

```bash
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&rotate=1"
```

### 指定代理

```bash
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&proxy=1.2.3.4:8080&lease=600"
curl "http://127.0.0.1:5010/v1/proxy?client_id=app1&id=节点ID&pool=node"
```

### 查看/释放当前租约

```bash
curl "http://127.0.0.1:5010/v1/proxy/current?client_id=app1"
curl -X POST "http://127.0.0.1:5010/v1/proxy/release" -H "Content-Type: application/json" -d "{"client_id":"app1"}"
```

### 设置全局规则

```bash
curl -X POST "http://127.0.0.1:5010/v1/proxy/rules" -H "Content-Type: application/json" -d "{"strategy":"round_robin","pool":"auto","lease_seconds":300}"
```


## 自定义对外代理接口（每个接口独立规则）

你可以创建多个对外接口，例如：

- `/open/crawler-a`
- `/open/crawler-b`
- `/open/mobile-app`

每个接口都能单独设置：

- `strategy`: `round_robin` / `random` / `sticky`
- `pool`: `auto` / `http` / `node`
- `lease_seconds`: 同一 client 使用多久后换下一个
- `prefer_https`
- `default_node_type`: 如 `vmess` / `ss` / `trojan`
- `fixed_proxy` / `fixed_node_id` / `fixed_share`: 指定固定代理
- `token`: 接口独立鉴权（可选）

### 创建接口

```bash
curl -X POST http://127.0.0.1:5010/admin/endpoints/ ^
  -H "Content-Type: application/json" ^
  -d "{"slug":"crawler-a","name":"爬虫A","rules":{"strategy":"round_robin","pool":"http","lease_seconds":180}}"
```

### 调用接口

```bash
curl "http://127.0.0.1:5010/open/crawler-a?client_id=worker-1"
curl "http://127.0.0.1:5010/open/crawler-a?client_id=worker-1&rotate=1"
```

### 管理接口

```bash
# 列表
curl http://127.0.0.1:5010/admin/endpoints/

# 删除
curl -X DELETE "http://127.0.0.1:5010/admin/endpoints/?slug=crawler-a"
```


## 代理返回格式（兼容旧字段）

旧字段继续保留：

```json
{"proxy": "127.0.0.1:7890", "https": false, ...}
```

新增外部项目可直接使用的字段：

```json
{
  "proxy": "127.0.0.1:7890",
  "proxy_url": "http://127.0.0.1:7890",
  "http": "http://127.0.0.1:7890",
  "https_proxy": "http://127.0.0.1:7890",
  "proxies": {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890"
  }
}
```

Python 示例：

```python
import requests
data = requests.get("http://127.0.0.1:5010/get/").json()
proxies = data.get("proxies") or {"http": data["proxy_url"], "https": data["proxy_url"]}
print(requests.get("https://httpbin.org/ip", proxies=proxies, timeout=10).text)
```


## 延迟与超时节点

代理对象新增：

```json
{
  "proxy": "1.2.3.4:8080",
  "latency_ms": 128,
  "last_status": true
}
```

- `latency_ms >= 0`：最近探测延迟（毫秒）
- `latency_ms = -1`：超时/失败
- 调度默认 `skip_timeout=true`，调用 `/v1/proxy`、`/open/<slug>` 时会跳过超时节点
- 可通过规则设置：
  - `skip_timeout`: true/false
  - `max_latency_ms`: 大于 0 时过滤超过该延迟的节点


## 优先低延迟调用

外部调用配置支持：

- `prefer_low_latency=true`：优先调用低延迟节点（默认开启）
- `strategy=lowest_latency`：始终选择当前可用最低延迟节点
- `skip_timeout=true`：跳过超时节点
- `max_latency_ms=800`：只调用延迟不超过 800ms 的节点

```bash
# 全局
curl -X POST http://127.0.0.1:5010/v1/proxy/rules -H "Content-Type: application/json" -d "{"prefer_low_latency":true,"skip_timeout":true,"max_latency_ms":800}"

# 自定义接口
curl -X POST http://127.0.0.1:5010/admin/endpoints/ -H "Content-Type: application/json" -d "{"slug":"fast","name":"低延迟","rules":{"strategy":"lowest_latency","prefer_low_latency":true,"skip_timeout":true,"lease_seconds":120}}"
```
