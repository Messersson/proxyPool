# -*- coding: utf-8 -*-
# !/usr/bin/env python
"""
-------------------------------------------------
   File Name：     ProxyApi.py
   Description :   WebApi
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
-------------------------------------------------
"""
__author__ = 'JHao'

import os
import platform
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
    {"url": "/admin/config", "params": "", "desc": "config admin page"},
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


@app.route('/')
def index():
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


@app.route('/count/')
@require_api_token
def getCount():
    proxies = proxy_handler.getAll()
    http_type_dict = {}
    source_dict = {}
    for proxy in proxies:
        http_type = 'https' if proxy.https else 'http'
        http_type_dict[http_type] = http_type_dict.get(http_type, 0) + 1
        for source in proxy.source.split('/'):
            if not source:
                continue
            source_dict[source] = source_dict.get(source, 0) + 1
    return {"http_type": http_type_dict, "source": source_dict, "count": len(proxies)}


@app.route('/admin/config/')
@app.route('/admin/config')
def admin_config_page():
    """配置管理页面"""
    return send_from_directory(STATIC_DIR, "admin.html")


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
