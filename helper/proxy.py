# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     Proxy
   Description :   代理对象类型封装
   Author :        JHao
   date：          2019/7/11
-------------------------------------------------
   Change Activity:
                   2019/7/11: 代理对象类型封装
                   2026/7/17: 支持协议节点(vmess/ss/trojan等)元数据
-------------------------------------------------
"""
__author__ = "JHao"

import json


class Proxy(object):

    def __init__(self, proxy, fail_count=0, region="", anonymous="",
                 source="", check_count=0, last_status="", last_time="", https=False,
                 protocol="", name="", share="", server="", port="", node_id="",
                 cipher="", password="", uuid="", network="", tls="", sni="", username="", latency_ms=-1):
        self._proxy = proxy
        self._fail_count = fail_count
        self._region = region
        self._anonymous = anonymous
        self._source = source.split("/") if source else []
        self._check_count = check_count
        self._last_status = last_status
        self._last_time = last_time
        self._https = https
        # 协议节点扩展字段
        self._protocol = protocol or ""
        self._name = name or ""
        self._share = share or ""
        self._server = server or ""
        self._port = str(port) if port not in (None, "") else ""
        self._node_id = node_id or ""
        self._cipher = cipher or ""
        self._password = password or ""
        self._uuid = uuid or ""
        self._network = network or ""
        self._tls = tls if tls not in (None,) else ""
        self._sni = sni or ""
        self._username = username or ""
        self._latency_ms = int(latency_ms) if latency_ms not in (None, "") else -1

    @classmethod
    def createFromJson(cls, proxy_json):
        _dict = json.loads(proxy_json) if isinstance(proxy_json, str) else (proxy_json or {})
        return cls(
            proxy=_dict.get("proxy", ""),
            fail_count=_dict.get("fail_count", 0),
            region=_dict.get("region", ""),
            anonymous=_dict.get("anonymous", ""),
            source=_dict.get("source", ""),
            check_count=_dict.get("check_count", 0),
            last_status=_dict.get("last_status", ""),
            last_time=_dict.get("last_time", ""),
            https=_dict.get("https", False),
            protocol=_dict.get("protocol", "") or _dict.get("type", ""),
            name=_dict.get("name", ""),
            share=_dict.get("share", ""),
            server=_dict.get("server", ""),
            port=_dict.get("port", ""),
            node_id=_dict.get("node_id", "") or _dict.get("id", ""),
            cipher=_dict.get("cipher", ""),
            password=_dict.get("password", ""),
            uuid=_dict.get("uuid", ""),
            network=_dict.get("network", ""),
            tls=_dict.get("tls", ""),
            sni=_dict.get("sni", ""),
            username=_dict.get("username", ""),
            latency_ms=_dict.get("latency_ms", -1),
        )

    @property
    def proxy(self):
        """ 代理 key：HTTP 为 host:port；协议节点为 node:<id> """
        return self._proxy

    @property
    def fail_count(self):
        return self._fail_count

    @property
    def region(self):
        return self._region

    @property
    def anonymous(self):
        return self._anonymous

    @property
    def source(self):
        return "/".join(self._source)

    @property
    def check_count(self):
        return self._check_count

    @property
    def last_status(self):
        return self._last_status

    @property
    def last_time(self):
        return self._last_time

    @property
    def https(self):
        return self._https

    @property
    def protocol(self):
        return self._protocol

    @property
    def name(self):
        return self._name

    @property
    def share(self):
        return self._share

    @property
    def server(self):
        return self._server

    @property
    def port(self):
        return self._port

    @property
    def node_id(self):
        return self._node_id

    @property
    def is_protocol_node(self):
        p = (self._protocol or "").lower()
        return bool(p) and p not in ("http", "https")

    @property
    def latency_ms(self):
        return self._latency_ms

    @latency_ms.setter
    def latency_ms(self, value):
        try:
            self._latency_ms = int(value)
        except Exception:
            self._latency_ms = -1


    def _auth_prefix(self):
        if self._username:
            pwd = self._password or ""
            return "%s:%s@" % (self._username, pwd)
        return ""

    def _host_port(self):
        # HTTP 代理: proxy 本身通常是 host:port 或 user:pass@host:port
        # 协议节点: 用 server:port
        if self._proxy and not str(self._proxy).startswith("node:"):
            return str(self._proxy)
        if self._server and self._port not in (None, ""):
            return "%s%s:%s" % (self._auth_prefix(), self._server, self._port)
        return ""

    @property
    def proxy_url(self):
        """外部项目可直接使用的代理地址，如 http://127.0.0.1:7890"""
        hostport = self._host_port()
        if not hostport:
            return ""
        # 已是完整 URL
        if "://" in hostport:
            return hostport
        proto = (self._protocol or "").lower()
        if proto in ("socks", "socks5", "socks5h"):
            return "socks5://%s" % hostport
        # 默认按 HTTP 代理导出
        return "http://%s" % hostport

    @property
    def proxies(self):
        """requests 风格代理字典"""
        url = self.proxy_url
        if not url:
            return {}
        return {"http": url, "https": url}

    @property
    def to_dict(self):
        data = {
            "proxy": self.proxy,
            "https": self.https,
            "fail_count": self.fail_count,
            "region": self.region,
            "anonymous": self.anonymous,
            "source": self.source,
            "check_count": self.check_count,
            "last_status": self.last_status,
            "last_time": self.last_time,
            "latency_ms": self.latency_ms,
            # 新增：外部项目可直接使用的代理 URL（兼容保留旧 proxy 字段）
            "proxy_url": self.proxy_url,
            "http": self.proxy_url,
            "https_proxy": self.proxy_url,
            "proxies": self.proxies,
        }
        # 兼容旧调用方：有协议信息时附加
        if self.protocol:
            data.update({
                "protocol": self.protocol,
                "type": self.protocol,
                "name": self.name,
                "share": self.share,
                "server": self.server,
                "port": self.port,
                "node_id": self.node_id,
                "cipher": self._cipher,
                "password": self._password,
                "uuid": self._uuid,
                "network": self._network,
                "tls": self._tls,
                "sni": self._sni,
                "username": self._username,
            })
        return data

    @property
    def to_json(self):
        return json.dumps(self.to_dict, ensure_ascii=False)

    @fail_count.setter
    def fail_count(self, value):
        self._fail_count = value

    @check_count.setter
    def check_count(self, value):
        self._check_count = value

    @last_status.setter
    def last_status(self, value):
        self._last_status = value

    @last_time.setter
    def last_time(self, value):
        self._last_time = value

    @https.setter
    def https(self, value):
        self._https = value

    @region.setter
    def region(self, value):
        self._region = value

    def add_source(self, source_str):
        if source_str:
            self._source.append(source_str)
            self._source = list(set(self._source))
