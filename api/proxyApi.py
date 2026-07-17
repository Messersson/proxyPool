# -*- coding: utf-8 -*-
# !/usr/bin/env python
"""
-------------------------------------------------
   File Name：     ProxyApi.py
   Description :   WebApi + unified admin panel
   Author :       JHao
   date：          2016/12/4
-------------------------------------------------
   Change Activity:
                   2016/12/04: WebApi
                   2019/08/14: 集成Gunicorn启动方式
                   2020/06/23: 新增pop接口
                   2022/07/21: 更新count接口
                   2026/07/16: 可选 API Token 鉴权，delete 支持 POST，新增 /health
                   2026/07/16: 管理页配置保存 /admin/config
                   2026/07/17: 统一前端面板入口
                   2026/07/17: FlClash/Clash 订阅导入 /admin/subscriptions
-------------------------------------------------
"""
__author__ = 'JHao'

import os
import platform
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import wraps
from werkzeug.wrappers import Response
from flask import Flask, jsonify, request, send_from_directory

from util.six import iteritems
from helper.proxy import Proxy
from handler.proxyHandler import ProxyHandler
from handler.configHandler import ConfigHandler
from handler import configStore
from util.singleton import Singleton

app = Flask(__name__)
conf = ConfigHandler()
proxy_handler = ProxyHandler()

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class JsonResponse(Response):
    @classmethod
    def force_type(cls, response, environ=None):
        if isinstance(response, (dict, list)):
            response = jsonify(response)

        return super(JsonResponse, cls).force_type(response, environ)


app.response_class = JsonResponse

api_list = [
    {"url": "/get", "params": "type: ''https'|''", "desc": "get a proxy"},
    {"url": "/pop", "params": "", "desc": "get and delete a proxy"},
    {"url": "/delete", "params": "proxy: 'e.g. 127.0.0.1:8080'", "desc": "delete an unable proxy"},
    {"url": "/all", "params": "type: ''https'|''", "desc": "get all proxy from proxy pool"},
    {"url": "/count", "params": "", "desc": "return proxy count"},
    {"url": "/health", "params": "", "desc": "health check (no auth)"},
    {"url": "/admin/fetchers", "params": "", "desc": "list active fetchers"},
    {"url": "/admin/proxy/test", "params": "POST proxy", "desc": "test one proxy/node and update latency"},
    {"url": "/admin/proxy/test_all", "params": "POST limit?", "desc": "test all proxies/nodes and update latency"},
    {"url": "/admin/subscriptions", "params": "GET/POST/DELETE", "desc": "manage Clash/node subscriptions"},
    {"url": "/admin/subscriptions/import", "params": "POST", "desc": "import FlClash/Clash subscription url/content now"},
    {"url": "/admin/nodes", "params": "type?,limit?", "desc": "list imported protocol/http nodes"},
    {"url": "/node/get", "params": "type: vmess|ss|trojan|...", "desc": "get a Clash/FlClash node"},
    {"url": "/node/pop", "params": "type: vmess|ss|trojan|...", "desc": "get and delete a node"},
    {"url": "/node/all", "params": "type?,limit?", "desc": "list all nodes"},
    {"url": "/node/count", "params": "", "desc": "node pool stats"},
    {"url": "/node/delete", "params": "id or share", "desc": "delete a node"},
    {"url": "/v1/proxy", "params": "strategy,pool,lease,type,id,proxy,client_id,rotate", "desc": "unified proxy acquire (round_robin/lease)"},
    {"url": "/v1/proxy/current", "params": "client_id", "desc": "current leased proxy"},
    {"url": "/v1/proxy/release", "params": "client_id", "desc": "release leased proxy"},
    {"url": "/v1/proxy/rules", "params": "GET/POST", "desc": "get/set dispatch rules"},
    {"url": "/v1/proxy/status", "params": "", "desc": "dispatch status"},
    {"url": "/admin/endpoints", "params": "GET/POST/DELETE", "desc": "manage custom public proxy endpoints"},
    {"url": "/open/<slug>", "params": "client_id,rotate,...", "desc": "custom endpoint with independent rules"},
    {"url": "/admin", "params": "", "desc": "unified admin panel"},
    {"url": "/admin/config/api", "params": "GET/POST", "desc": "read/save runtime config"},
]


def _extract_token():
    header_token = request.headers.get("X-API-Token") or request.headers.get("Authorization", "")
    if header_token.lower().startswith("bearer "):
        header_token = header_token[7:].strip()
    query_token = request.args.get("token", "")
    return header_token or query_token


def require_api_token(func):
    """API_TOKEN 非空时校验请求 token"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        expected = ConfigHandler().apiToken
        if expected:
            provided = _extract_token()
            if provided != expected:
                return {"code": 401, "src": "unauthorized"}, 401
        return func(*args, **kwargs)
    return wrapper


def _rebind_proxy_handler():
    """配置变更后重建 ProxyHandler/DbClient 连接"""
    global proxy_handler
    # 清掉 DbClient 单例，确保新 DB_CONN 生效
    try:
        from db.dbClient import DbClient
        Singleton._inst.pop(DbClient, None)
    except Exception:
        pass
    proxy_handler = ProxyHandler()
    return proxy_handler


def _panel_page():
    """统一前端面板"""
    return send_from_directory(STATIC_DIR, "admin.html")


@app.route('/')
@app.route('/admin')
@app.route('/admin/')
@app.route('/admin/config')
@app.route('/admin/config/')
def admin_panel():
    return _panel_page()


@app.route('/api')
@app.route('/api/')
def api_index():
    return {'url': api_list}


@app.route('/health/')
def health():
    """轻量健康检查，默认不鉴权，便于探活/编排"""
    try:
        stats = proxy_handler.db.getCount()
        return {
            "status": "ok",
            "count": stats.get("total", 0),
            "https": stats.get("https", 0),
        }
    except Exception as e:
        return {"status": "error", "src": str(e)}, 503


@app.route('/get/')
@require_api_token
def get():
    https = request.args.get("type", "").lower() == 'https'
    proxy = proxy_handler.get(https)
    return proxy.to_dict if proxy else {"code": 0, "src": "no proxy"}


@app.route('/pop/')
@require_api_token
def pop():
    https = request.args.get("type", "").lower() == 'https'
    proxy = proxy_handler.pop(https)
    return proxy.to_dict if proxy else {"code": 0, "src": "no proxy"}


@app.route('/refresh/')
@require_api_token
def refresh():
    # TODO refresh会有守护程序定时执行，由api直接调用性能较差，暂不使用
    return 'success'


@app.route('/all/')
@require_api_token
def getAll():
    https = request.args.get("type", "").lower() == 'https'
    proxies = proxy_handler.getAll(https)
    return jsonify([_.to_dict for _ in proxies])


@app.route('/delete/', methods=['GET', 'POST'])
@require_api_token
def delete():
    proxy = request.args.get('proxy')
    if not proxy and request.method == 'POST':
        proxy = request.form.get('proxy') or (request.get_json(silent=True) or {}).get('proxy')
    if not proxy:
        return {"code": 400, "src": "missing proxy"}, 400
    status = proxy_handler.delete(Proxy(proxy))
    return {"code": 0, "src": status}




@app.route('/admin/proxy/test', methods=['POST'])
@app.route('/admin/proxy/test/', methods=['POST'])
@require_api_token
def admin_proxy_test():
    """????????/???????????"""
    from helper.check import DoValidator

    payload = request.get_json(silent=True) or {}
    proxy_key = (request.args.get("proxy") or payload.get("proxy") or "").strip()
    if not proxy_key:
        return {"code": 400, "src": "missing proxy"}, 400

    proxy = proxy_handler.getByKey(proxy_key)
    if not proxy:
        return {"code": 404, "src": "proxy not found", "proxy": proxy_key}, 404

    tested = DoValidator.validator(proxy, "use")
    if tested.last_status:
        proxy_handler.put(tested)
        action = "updated"
    else:
        conf_local = ConfigHandler()
        if tested.fail_count > conf_local.maxFailCount:
            proxy_handler.delete(tested)
            action = "deleted"
        else:
            proxy_handler.put(tested)
            action = "updated"

    return {
        "code": 0,
        "src": "ok" if tested.last_status else "timeout",
        "action": action,
        "proxy": tested.to_dict,
    }


@app.route('/admin/proxy/test_all', methods=['POST'])
@app.route('/admin/proxy/test_all/', methods=['POST'])
@require_api_token
def admin_proxy_test_all():
    """??????????/???????????"""
    from helper.check import DoValidator

    payload = request.get_json(silent=True) or {}
    try:
        limit = int(request.args.get("limit") or payload.get("limit") or 0)
    except Exception:
        limit = 0
    try:
        workers = int(request.args.get("workers") or payload.get("workers") or conf.checkThreadCount)
    except Exception:
        workers = conf.checkThreadCount
    workers = max(1, min(workers, 50))

    proxies = proxy_handler.getAll()
    if limit > 0:
        proxies = proxies[:limit]
    if not proxies:
        return {"code": 0, "src": "empty", "total": 0, "ok": 0, "fail": 0, "deleted": 0, "items": []}

    conf_local = ConfigHandler()
    results = []
    ok_count = 0
    fail_count = 0
    deleted_count = 0

    def _run_one(item):
        tested = DoValidator.validator(item, "use")
        action = "updated"
        if tested.last_status:
            proxy_handler.put(tested)
        else:
            if tested.fail_count > conf_local.maxFailCount:
                proxy_handler.delete(tested)
                action = "deleted"
            else:
                proxy_handler.put(tested)
        return tested, action

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(_run_one, proxy): proxy.proxy for proxy in proxies}
        for future in as_completed(future_map):
            try:
                tested, action = future.result()
            except Exception as exc:
                fail_count += 1
                results.append({
                    "proxy": future_map[future],
                    "ok": False,
                    "latency_ms": -1,
                    "last_status": False,
                    "action": "error",
                    "error": str(exc),
                })
                continue

            is_ok = bool(tested.last_status)
            if is_ok:
                ok_count += 1
            else:
                fail_count += 1
            if action == "deleted":
                deleted_count += 1
            results.append({
                "proxy": tested.proxy,
                "name": getattr(tested, "name", "") or "",
                "protocol": getattr(tested, "protocol", "") or "",
                "ok": is_ok,
                "latency_ms": tested.latency_ms,
                "last_status": tested.last_status,
                "fail_count": tested.fail_count,
                "check_count": tested.check_count,
                "last_time": tested.last_time,
                "region": tested.region,
                "action": action,
            })

    results.sort(key=lambda x: (
        0 if (x.get("latency_ms") is not None and int(x.get("latency_ms")) >= 0) else 1,
        int(x.get("latency_ms")) if (x.get("latency_ms") is not None and int(x.get("latency_ms")) >= 0) else 10 ** 9,
        str(x.get("proxy") or ""),
    ))

    return {
        "code": 0,
        "src": "ok",
        "total": len(proxies),
        "ok": ok_count,
        "fail": fail_count,
        "deleted": deleted_count,
        "workers": workers,
        "items": results,
    }


@app.route('/count/')
@require_api_token
def getCount():
    proxies = proxy_handler.getAll()
    http_type_dict = {}
    source_dict = {}
    protocol_dict = {}
    for proxy in proxies:
        proto = (getattr(proxy, "protocol", None) or ("https" if proxy.https else "http")).lower()
        if proto in ("http", "https"):
            http_type = "https" if (proto == "https" or proxy.https) else "http"
            http_type_dict[http_type] = http_type_dict.get(http_type, 0) + 1
        protocol_dict[proto] = protocol_dict.get(proto, 0) + 1
        for source in proxy.source.split('/'):
            if not source:
                continue
            source_dict[source] = source_dict.get(source, 0) + 1
    return {
        "http_type": http_type_dict,
        "protocol": protocol_dict,
        "source": source_dict,
        "count": len(proxies),
    }


@app.route('/admin/fetchers')
@app.route('/admin/fetchers/')
@require_api_token
def admin_fetchers():
    """列出当前启用的代理源"""
    from helper.fetch import _discover_fetchers
    conf_obj = ConfigHandler()
    exclude = conf_obj.fetcherExclude or []
    classes = _discover_fetchers(exclude)
    return {
        "active": [
            {
                "name": getattr(cls, "name", cls.__name__),
                "class": cls.__name__,
            }
            for cls in classes
        ],
        "exclude": list(exclude),
        "count": len(classes),
    }



@app.route('/admin/subscriptions', methods=['GET', 'POST', 'DELETE'])
@app.route('/admin/subscriptions/', methods=['GET', 'POST', 'DELETE'])
@require_api_token
def admin_subscriptions():
    """
    GET    : 列出已保存订阅
    POST   : 新增/更新订阅 {"id?","name","url","enabled"}
    DELETE : 删除订阅 ?id= / JSON {"id":...}
    """
    from handler import subscriptionStore
    from helper.subscription import new_subscription_id

    if request.method == 'GET':
        return subscriptionStore.list_subscriptions()

    if request.method == 'DELETE':
        sid = request.args.get('id')
        if not sid:
            sid = (request.get_json(silent=True) or {}).get('id')
        if not sid:
            return {"code": 400, "src": "missing id"}, 400
        ok = subscriptionStore.delete_subscription(sid)
        if not ok:
            return {"code": 404, "src": "not found"}, 404
        return {"code": 0, "src": "deleted", "id": sid}

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {"code": 400, "src": "invalid payload"}, 400
    url = (payload.get('url') or '').strip()
    if not url:
        return {"code": 400, "src": "missing url"}, 400
    name = (payload.get('name') or '').strip() or url
    enabled = payload.get('enabled', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ('1', 'true', 'yes', 'on')
    item = {
        "id": (payload.get('id') or new_subscription_id()).strip(),
        "name": name,
        "url": url,
        "enabled": bool(enabled),
    }
    saved = subscriptionStore.upsert_subscription(item)
    return {"code": 0, "src": "saved", "item": saved}


@app.route('/admin/subscriptions/import', methods=['POST'])
@app.route('/admin/subscriptions/import/', methods=['POST'])
@require_api_token
def admin_subscriptions_import():
    """
    立即导入订阅。
    JSON:
      - url: 订阅链接（可选）
      - content: 原始订阅文本/YAML/base64（可选）
      - name/source: 来源名
      - save: 是否写入 subscriptions.json（默认 true，仅 url 时）
      - write_pool: 是否写入代理池（默认 true）
      - id: 已有订阅 id（可选）
    """
    from handler import subscriptionStore
    from helper.subscription import import_from_url, import_from_text, new_subscription_id

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return {"code": 400, "src": "invalid payload"}, 400

    url = (payload.get('url') or '').strip()
    content = payload.get('content')
    name = (payload.get('name') or payload.get('source') or '').strip()
    write_pool = payload.get('write_pool', True)
    if isinstance(write_pool, str):
        write_pool = write_pool.strip().lower() in ('1', 'true', 'yes', 'on')
    save = payload.get('save', True)
    if isinstance(save, str):
        save = save.strip().lower() in ('1', 'true', 'yes', 'on')
    sid = (payload.get('id') or '').strip()

    if not url and not content:
        return {"code": 400, "src": "missing url or content"}, 400

    if url:
        result = import_from_url(url, source_name=name, write_pool=bool(write_pool), save_nodes_flag=True)
        if save and not result.get('error'):
            item = {
                "id": sid or new_subscription_id(),
                "name": name or result.get('source') or url,
                "url": url,
                "enabled": True,
                "last_sync_at": result.get('fetched_at'),
                "last_sync_stats": result.get('stats') or {},
                "last_sync_pool": result.get('pool') or {},
                "last_sync_nodes": result.get('node_store') or {},
                "last_error": result.get('error') or "",
            }
            # 保留旧 id
            if sid:
                old = subscriptionStore.get_subscription(sid)
                if old:
                    item['id'] = old.get('id') or item['id']
                    item['created_at'] = old.get('created_at')
            saved = subscriptionStore.upsert_subscription(item)
            result['saved_item'] = saved
        status = 200
        if result.get('error'):
            # 下载失败
            status = 502
        elif not (result.get('nodes') or result.get('proxies')):
            status = 422
        return {"code": 0 if status == 200 else status, "src": result.get('error') or ("no nodes parsed" if status == 422 else "imported"), "result": result}, status

    result = import_from_text(str(content), source_name=name or "paste", write_pool=bool(write_pool), save_nodes_flag=True)
    return {"code": 0, "src": "imported", "result": result}



@app.route('/admin/nodes')
@app.route('/admin/nodes/')
@require_api_token
def admin_nodes():
    """列出已导入的 FlClash/Clash 节点（协议节点 + HTTP 节点）"""
    from helper.subscription import list_nodes
    node_type = request.args.get('type', '')
    try:
        limit = int(request.args.get('limit', 500))
    except Exception:
        limit = 500
    return list_nodes(limit=limit, node_type=node_type)



@app.route('/node/get/')
@app.route('/node/get')
@require_api_token
def node_get():
    """随机获取一个协议节点（vmess/ss/trojan/...）"""
    from helper.subscription import get_node
    node_type = request.args.get('type', '')
    mask = str(request.args.get('mask', '0')).lower() in ('1', 'true', 'yes')
    node = get_node(node_type=node_type, mask_secrets=mask)
    return node if node else {"code": 0, "src": "no node"}


@app.route('/node/pop/')
@app.route('/node/pop')
@require_api_token
def node_pop():
    """获取并删除一个协议节点"""
    from helper.subscription import pop_node
    node_type = request.args.get('type', '')
    mask = str(request.args.get('mask', '0')).lower() in ('1', 'true', 'yes')
    node = pop_node(node_type=node_type, mask_secrets=mask)
    return node if node else {"code": 0, "src": "no node"}


@app.route('/node/all/')
@app.route('/node/all')
@require_api_token
def node_all():
    """列出节点池"""
    from helper.subscription import list_nodes
    node_type = request.args.get('type', '')
    try:
        limit = int(request.args.get('limit', 500))
    except Exception:
        limit = 500
    mask = str(request.args.get('mask', '1')).lower() in ('1', 'true', 'yes')
    data = list_nodes(limit=limit, node_type=node_type)
    if not mask:
        # list_nodes 默认脱敏；需要完整字段时重新读
        from helper.subscription import _load_all_nodes, _public_node
        items = _load_all_nodes()
        if node_type:
            nt = node_type.lower().strip()
            items = [x for x in items if str(x.get("type") or "").lower() == nt]
        data["items"] = [_public_node(x, mask_secrets=False) for x in items[:limit]]
    return data


@app.route('/node/count/')
@app.route('/node/count')
@require_api_token
def node_count():
    from helper.subscription import count_nodes
    return count_nodes()


@app.route('/node/delete/', methods=['GET', 'POST'])
@app.route('/node/delete', methods=['GET', 'POST'])
@require_api_token
def node_delete():
    from helper.subscription import delete_node
    payload = request.get_json(silent=True) or {}
    node_id = request.args.get('id') or payload.get('id') or ''
    share = request.args.get('share') or payload.get('share') or ''
    if not node_id and not share:
        return {"code": 400, "src": "missing id or share"}, 400
    ok = delete_node(node_id=node_id, share=share)
    return {"code": 0, "src": bool(ok)}



@app.route('/v1/proxy/', methods=['GET', 'POST'])
@app.route('/v1/proxy', methods=['GET', 'POST'])
@require_api_token
def v1_proxy_acquire():
    """
    统一对外代理接口。
    支持:
      - strategy=round_robin|random|sticky
      - pool=auto|http|node
      - lease=秒（同一 client 在租约内固定同一代理）
      - type=vmess|ss|trojan|https...
      - proxy=1.2.3.4:8080  指定 HTTP 代理
      - id=节点ID          指定协议节点
      - share=分享链       指定协议节点
      - client_id=调用方标识（强烈建议传）
      - rotate=1           强制换下一个
    """
    from helper.proxyDispatcher import acquire
    payload = request.get_json(silent=True) or {}
    args = request.args

    def _get(key, default=""):
        if key in args and args.get(key) not in (None, ""):
            return args.get(key)
        return payload.get(key, default)

    lease_raw = _get("lease", None)
    lease_seconds = None
    if lease_raw not in (None, ""):
        try:
            lease_seconds = int(lease_raw)
        except Exception:
            return {"code": 400, "src": "lease must be int seconds"}, 400

    rotate = str(_get("rotate", "0")).lower() in ("1", "true", "yes", "on")
    prefer = _get("prefer_https", None)
    prefer_https = None if prefer in (None, "") else str(prefer).lower() in ("1", "true", "yes", "on")

    result = acquire(
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


@app.route('/v1/proxy/current/', methods=['GET'])
@app.route('/v1/proxy/current', methods=['GET'])
@require_api_token
def v1_proxy_current():
    from helper.proxyDispatcher import current
    return current(
        client_id=request.args.get("client_id", ""),
        client_key=request.args.get("client_key", ""),
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )


@app.route('/v1/proxy/release/', methods=['GET', 'POST'])
@app.route('/v1/proxy/release', methods=['GET', 'POST'])
@require_api_token
def v1_proxy_release():
    from helper.proxyDispatcher import release
    payload = request.get_json(silent=True) or {}
    return release(
        client_id=request.args.get("client_id") or payload.get("client_id") or "",
        client_key=request.args.get("client_key") or payload.get("client_key") or "",
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
    )


@app.route('/v1/proxy/rules/', methods=['GET', 'POST'])
@app.route('/v1/proxy/rules', methods=['GET', 'POST'])
@require_api_token
def v1_proxy_rules():
    from helper.proxyDispatcher import load_rules, save_rules
    if request.method == "GET":
        return {"code": 0, "rules": load_rules()}
    payload = request.get_json(silent=True) or {}
    try:
        rules = save_rules(payload)
        return {"code": 0, "src": "saved", "rules": rules}
    except ValueError as e:
        return {"code": 400, "src": str(e)}, 400


@app.route('/v1/proxy/status/', methods=['GET'])
@app.route('/v1/proxy/status', methods=['GET'])
@require_api_token
def v1_proxy_status():
    from helper.proxyDispatcher import status
    return status()



@app.route('/admin/endpoints', methods=['GET', 'POST', 'DELETE'])
@app.route('/admin/endpoints/', methods=['GET', 'POST', 'DELETE'])
@require_api_token
def admin_endpoints():
    """自定义对外代理接口管理：每个接口独立调用规则"""
    from handler import endpointStore
    if request.method == 'GET':
        return endpointStore.list_endpoints()

    if request.method == 'DELETE':
        payload = request.get_json(silent=True) or {}
        eid = request.args.get('id') or payload.get('id') or ''
        slug = request.args.get('slug') or payload.get('slug') or ''
        if not eid and not slug:
            return {"code": 400, "src": "missing id or slug"}, 400
        ok = endpointStore.delete_endpoint(eid=eid, slug=slug)
        if not ok:
            return {"code": 404, "src": "not found"}, 404
        return {"code": 0, "src": "deleted"}

    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict) or not payload:
        return {"code": 400, "src": "empty payload"}, 400
    try:
        # 允许 rules 平铺提交
        if "rules" not in payload:
            rules = {}
            for k in (
                "strategy", "pool", "lease_seconds", "prefer_https", "default_node_type",
                "fixed_proxy", "fixed_node_id", "fixed_share", "token",
                "skip_timeout", "max_latency_ms", "prefer_low_latency",
            ):
                if k in payload:
                    rules[k] = payload.get(k)
            if rules:
                payload = dict(payload)
                payload["rules"] = rules
        item = endpointStore.upsert_endpoint(payload)
        return {"code": 0, "src": "saved", "item": item}
    except ValueError as e:
        return {"code": 400, "src": str(e)}, 400


@app.route('/open/<slug>', methods=['GET', 'POST'])
@app.route('/open/<slug>/', methods=['GET', 'POST'])
def open_endpoint(slug):
    """
    自定义对外代理接口。
    每个 slug 对应独立规则：轮询/随机/粘性、租约秒数、http/node 池、固定代理等。
    """
    from handler import endpointStore
    from helper.proxyDispatcher import acquire
    from handler.configHandler import ConfigHandler

    ep = endpointStore.get_endpoint_by_slug(slug)
    if not ep or not ep.get("enabled", True):
        return {"code": 404, "src": "endpoint not found"}, 404

    rules = ep.get("rules") or {}
    # 鉴权：端点 token 优先，否则全局 API_TOKEN
    endpoint_token = str(rules.get("token") or "")
    global_token = ConfigHandler().apiToken or ""
    expected = endpoint_token or global_token
    if expected:
        provided = _extract_token()
        if provided != expected:
            return {"code": 401, "src": "unauthorized"}, 401

    payload = request.get_json(silent=True) or {}
    args = request.args

    def _get(key, default=""):
        if key in args and args.get(key) not in (None, ""):
            return args.get(key)
        return payload.get(key, default)

    # 请求参数可临时覆盖端点规则（不改持久配置）
    override = dict(rules)
    for k in ("strategy", "pool", "default_node_type", "fixed_proxy", "fixed_node_id", "fixed_share"):
        v = _get(k, None)
        if v not in (None, ""):
            override[k] = v
    lease_raw = _get("lease", None)
    lease_seconds = None
    if lease_raw not in (None, ""):
        try:
            lease_seconds = int(lease_raw)
        except Exception:
            return {"code": 400, "src": "lease must be int seconds"}, 400
    if _get("prefer_https", None) not in (None, ""):
        override["prefer_https"] = str(_get("prefer_https")).lower() in ("1", "true", "yes", "on")

    rotate = str(_get("rotate", "0")).lower() in ("1", "true", "yes", "on")
    result = acquire(
        pool=str(_get("pool", "") or ""),
        strategy=str(_get("strategy", "") or ""),
        lease_seconds=lease_seconds,
        node_type=str(_get("type", "") or override.get("default_node_type") or ""),
        prefer_https=None,
        proxy=str(_get("proxy", "") or ""),
        node_id=str(_get("id", "") or ""),
        share=str(_get("share", "") or ""),
        client_id=str(_get("client_id", "") or ""),
        force_rotate=rotate,
        request_ip=request.headers.get("X-Forwarded-For", request.remote_addr or ""),
        request_token=_extract_token() or "",
        rules_override=override,
        endpoint_slug=str(ep.get("slug") or slug),
    )
    if result.get("code") == 404:
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


@app.route('/admin/config/api', methods=['GET', 'POST'])
@require_api_token
def admin_config_api():
    """
    GET  : 读取当前生效配置（含来源）
    POST : 保存配置到 data/runtime_config.json 并热加载
    """
    if request.method == 'GET':
        view = conf.get_view(mask_secrets=True)
        return view

    payload = request.get_json(silent=True)
    if payload is None:
        # 兼容 form 提交
        payload = request.form.to_dict(flat=True)
    if not isinstance(payload, dict) or not payload:
        return {"code": 400, "src": "empty payload"}, 400

    # 密码字段如果前端传来掩码，则忽略
    if payload.get("API_TOKEN") in ("********", "***"):
        payload = dict(payload)
        payload.pop("API_TOKEN", None)

    try:
        before_db = conf.dbConn
        before_table = conf.tableName
        saved = conf.save(payload, merge=True)
        # DB 相关变更时重建连接
        if conf.dbConn != before_db or conf.tableName != before_table:
            _rebind_proxy_handler()

        restart_required = []
        for meta in configStore.CONFIG_SCHEMA:
            key = meta["key"]
            if key in payload and meta.get("restart_required"):
                restart_required.append(key)

        return {
            "code": 0,
            "src": "saved",
            "saved_keys": sorted(list(saved.keys())),
            "restart_required": restart_required,
            "file": str(configStore.get_config_file()),
            "config": conf.get_view(mask_secrets=True),
        }
    except ValueError as e:
        return {"code": 400, "src": str(e)}, 400
    except Exception as e:
        return {"code": 500, "src": str(e)}, 500


def runFlask():
    if platform.system() == "Windows":
        app.run(host=conf.serverHost, port=conf.serverPort)
    else:
        import gunicorn.app.base

        class StandaloneApplication(gunicorn.app.base.BaseApplication):

            def __init__(self, app, options=None):
                self.options = options or {}
                self.application = app
                super(StandaloneApplication, self).__init__()

            def load_config(self):
                _config = dict([(key, value) for key, value in iteritems(self.options)
                                if key in self.cfg.settings and value is not None])
                for key, value in iteritems(_config):
                    self.cfg.set(key.lower(), value)

            def load(self):
                return self.application

        _options = {
            'bind': '%s:%s' % (conf.serverHost, conf.serverPort),
            'workers': 4,
            'accesslog': '-',  # log to stdout
            'access_log_format': '%(h)s %(l)s %(t)s "%(r)s" %(s)s "%(a)s"'
        }
        StandaloneApplication(app, _options).run()


if __name__ == '__main__':
    runFlask()
