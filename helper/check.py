# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     check
   Description :   执行代理校验
   Author :        JHao
   date：          2019/8/6
-------------------------------------------------
   Change Activity:
                   2019/08/06: 执行代理校验
                   2021/05/25: 分别校验http和https
                   2022/08/16: 获取代理Region信息
                   2026/07/16: 可配置线程数，弃用 setDaemon
-------------------------------------------------
"""
__author__ = 'JHao'

from util.six import Empty
from threading import Thread
from datetime import datetime
import time
import socket
import re


def re_ip(host):
    return bool(re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", str(host or "")))

from util.webRequest import WebRequest
from handler.logHandler import LogHandler
from helper.validator import ProxyValidator
from handler.proxyHandler import ProxyHandler
from handler.configHandler import ConfigHandler


class DoValidator(object):
    """ 执行校验 """

    conf = ConfigHandler()

    @classmethod
    def validator(cls, proxy, work_type):
        """
        校验入口
        Args:
            proxy: Proxy Object
            work_type: raw/use
        Returns:
            Proxy Object
        """
        proxy.check_count += 1
        proxy.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 协议节点：TCP 连接延迟探测（不走 HTTP 代理校验）
        if getattr(proxy, "is_protocol_node", False) or str(getattr(proxy, "proxy", "")).startswith("node:"):
            ok, latency = cls.tcpLatency(proxy)
            proxy.latency_ms = latency
            proxy.last_status = bool(ok)
            if ok:
                if proxy.fail_count > 0:
                    proxy.fail_count -= 1
                if work_type == "raw" or not getattr(proxy, "region", ""):
                    proxy.region = cls.regionGetterHost(getattr(proxy, "server", "") or "") if cls.conf.proxyRegion else (proxy.region or "")
            else:
                proxy.fail_count += 1
            return proxy

        # HTTP/HTTPS 代理：探测可用性并记录延迟
        ok, latency, https_r = cls.httpLatency(proxy)
        proxy.latency_ms = latency
        proxy.last_status = bool(ok)
        if ok:
            if proxy.fail_count > 0:
                proxy.fail_count -= 1
            proxy.https = True if https_r else False
            if work_type == "raw":
                proxy.region = cls.regionGetter(proxy) if cls.conf.proxyRegion else ""
        else:
            proxy.fail_count += 1
        return proxy

    @classmethod
    def httpValidator(cls, proxy):
        for func in ProxyValidator.http_validator:
            if not func(proxy.proxy):
                return False
        return True

    @classmethod
    def httpsValidator(cls, proxy):
        for func in ProxyValidator.https_validator:
            if not func(proxy.proxy):
                return False
        return True

    @classmethod
    def preValidator(cls, proxy):
        for func in ProxyValidator.pre_validator:
            if not func(proxy):
                return False
        return True

    @classmethod
    def tcpLatency(cls, proxy):
        """协议节点 TCP 延迟，返回 (ok, latency_ms)；失败 latency=-1"""
        host = getattr(proxy, "server", "") or ""
        port = getattr(proxy, "port", "") or ""
        if not host or port in (None, ""):
            # node:id 但缺 server/port
            return False, -1
        try:
            port_i = int(port)
        except Exception:
            return False, -1
        timeout = max(1, int(getattr(cls.conf, "verifyTimeout", 10) or 10))
        start = time.time()
        try:
            with socket.create_connection((host, port_i), timeout=timeout):
                pass
            latency = int((time.time() - start) * 1000)
            return True, max(0, latency)
        except Exception:
            return False, -1

    @classmethod
    def httpLatency(cls, proxy):
        """HTTP 代理延迟探测，返回 (ok, latency_ms, https_ok)"""
        from requests import head
        timeout = max(1, int(getattr(cls.conf, "verifyTimeout", 10) or 10))
        proxy_str = getattr(proxy, "proxy", "")
        proxies = {
            "http": "http://{proxy}".format(proxy=proxy_str),
            "https": "http://{proxy}".format(proxy=proxy_str),
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }
        start = time.time()
        try:
            r = head(cls.conf.httpUrl, headers=headers, proxies=proxies, timeout=timeout)
            if r.status_code != 200:
                return False, -1, False
            latency = int((time.time() - start) * 1000)
        except Exception:
            return False, -1, False
        # https optional
        https_ok = False
        try:
            r2 = head(cls.conf.httpsUrl, headers=headers, proxies=proxies, timeout=timeout, verify=False)
            https_ok = (r2.status_code == 200)
        except Exception:
            https_ok = False
        return True, max(0, latency), https_ok

    @classmethod
    def regionGetterHost(cls, host):
        """根据 host/ip 解析地区"""
        host = (host or "").strip()
        if not host:
            return ""
        # 域名先解析 IP
        try:
            ip = host
            if not re_ip(host):
                ip = socket.gethostbyname(host)
            url = "https://api.ip.sb/geoip/%s" % ip
            r = WebRequest().get(url=url, retry_time=1, timeout=2).json
            return (r.get("country_code") or r.get("country") or "") if r else ""
        except Exception:
            return ""

    @classmethod
    def regionGetter(cls, proxy):

        try:
            url = 'https://api.ip.sb/geoip/%s' % proxy.proxy.split(':')[0]
            r = WebRequest().get(url=url, retry_time=1, timeout=2).json
            return r.get('country_code') if r else 'error'
        except Exception:
            return 'error'


class _ThreadChecker(Thread):
    """ 多线程检测 """

    def __init__(self, work_type, target_queue, thread_name):
        Thread.__init__(self, name=thread_name)
        self.work_type = work_type
        self.log = LogHandler("checker")
        self.proxy_handler = ProxyHandler()
        self.target_queue = target_queue
        self.conf = ConfigHandler()

    def run(self):
        self.log.info("{}ProxyCheck - {}: start".format(self.work_type.title(), self.name))
        while True:
            try:
                proxy = self.target_queue.get(block=False)
            except Empty:
                self.log.info("{}ProxyCheck - {}: complete".format(self.work_type.title(), self.name))
                break
            proxy = DoValidator.validator(proxy, self.work_type)
            if self.work_type == "raw":
                self.__ifRaw(proxy)
            else:
                self.__ifUse(proxy)
            self.target_queue.task_done()

    def __ifRaw(self, proxy):
        if proxy.last_status:
            if self.proxy_handler.exists(proxy):
                self.log.info('RawProxyCheck - {}: {} exist'.format(self.name, proxy.proxy.ljust(23)))
            else:
                self.log.info('RawProxyCheck - {}: {} pass'.format(self.name, proxy.proxy.ljust(23)))
                self.proxy_handler.put(proxy)
        else:
            self.log.info('RawProxyCheck - {}: {} fail'.format(self.name, proxy.proxy.ljust(23)))

    def __ifUse(self, proxy):
        if proxy.last_status:
            self.log.info('UseProxyCheck - {}: {} pass'.format(self.name, proxy.proxy.ljust(23)))
            self.proxy_handler.put(proxy)
        else:
            if proxy.fail_count > self.conf.maxFailCount:
                self.log.info('UseProxyCheck - {}: {} fail, count {} delete'.format(self.name,
                                                                                    proxy.proxy.ljust(23),
                                                                                    proxy.fail_count))
                self.proxy_handler.delete(proxy)
            else:
                self.log.info('UseProxyCheck - {}: {} fail, count {} keep'.format(self.name,
                                                                                  proxy.proxy.ljust(23),
                                                                                  proxy.fail_count))
                self.proxy_handler.put(proxy)


def Checker(tp, queue):
    """
    run Proxy ThreadChecker
    :param tp: raw/use
    :param queue: Proxy Queue
    :return:
    """
    thread_list = list()
    conf = ConfigHandler()
    thread_count = conf.checkThreadCount
    for index in range(thread_count):
        thread_list.append(_ThreadChecker(tp, queue, "thread_%s" % str(index).zfill(2)))

    for thread in thread_list:
        thread.daemon = True
        thread.start()

    for thread in thread_list:
        thread.join()
