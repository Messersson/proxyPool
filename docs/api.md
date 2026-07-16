# API 使用

## 接口列表

启动 ProxyPool 的 `server` 后会提供如下 HTTP 接口：

| 接口 | 方法 | 说明 | 参数 |
|------|------|------|------|
| `/` | GET | 返回 API 列表 | 无 |
| `/health` | GET | 健康检查（默认不鉴权） | 无 |
| `/admin/config` | GET | 配置管理页面 | 无 |
| `/admin/config/api` | GET/POST | 读取/保存运行时配置 | POST JSON 配置字段 |
| `/get` | GET | 随机返回一个代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/pop` | GET | 返回并删除一个代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/all` | GET | 返回所有代理 | 可选：`?type=https` 过滤 HTTPS 代理 |
| `/count` | GET | 返回代理数量统计 | 无 |
| `/delete` | GET/POST | 删除指定代理 | GET: `?proxy=host:port`；POST JSON: `{"proxy":"host:port"}` |

## 网页配置保存

打开 `http://127.0.0.1:5010/admin/config`，修改表单后点击「保存配置」。

配置会写入 `data/runtime_config.json`，并立即热加载到当前 API 进程。环境变量覆盖的字段会显示为锁定，不可在网页改写。

## 鉴权（可选）

当 `setting.py` 或环境变量 `API_TOKEN` 非空时，业务接口需要携带 Token：

- 请求头 `X-API-Token: <token>`
- 或 `Authorization: Bearer <token>`
- 或 Query `?token=<token>`

`/` 与 `/health` 默认不鉴权，便于探活。

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
