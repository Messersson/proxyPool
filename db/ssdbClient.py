# -*- coding: utf-8 -*-
# !/usr/bin/env python
"""
-------------------------------------------------
   File Name：     ssdbClient.py
   Description :   封装SSDB操作
   Author :        JHao
   date：          2016/12/2
-------------------------------------------------
   Change Activity:
                   2016/12/2:
                   2017/09/22: PY3中 redis-py返回的数据是bytes型
                   2017/09/27: 修改pop()方法 返回{proxy:value}字典
                   2020/07/03: 2.1.0 优化代码结构
                   2021/05/26: 区分http/https代理
                   2026/07/16: HTTPS 二级索引，加速 get/count
-------------------------------------------------
"""
__author__ = 'JHao'
from redis.exceptions import TimeoutError, ConnectionError, ResponseError
from redis.connection import BlockingConnectionPool
from handler.logHandler import LogHandler
from random import choice
from redis import Redis
import json


class SsdbClient(object):
    """
    SSDB client

    SSDB中代理存放的结构为hash：
    key为代理的ip:por, value为代理属性的字典;

    HTTPS 代理额外维护 set: {table}:https，用于快速随机取与计数。
    """

    def __init__(self, **kwargs):
        """
        init
        :param host: host
        :param port: port
        :param password: password
        :return:
        """
        self.name = ""
        kwargs.pop("username")
        self.__conn = Redis(connection_pool=BlockingConnectionPool(decode_responses=True,
                                                                   timeout=5,
                                                                   socket_timeout=5,
                                                                   protocol=2,
                                                                   **kwargs))

    @property
    def _https_index(self):
        return "%s:https" % self.name

    def _sync_https_index(self, proxy_str, https):
        if not proxy_str:
            return
        if https:
            self.__conn.sadd(self._https_index, proxy_str)
        else:
            self.__conn.srem(self._https_index, proxy_str)

    def _rebuild_https_index(self):
        pipe = self.__conn.pipeline()
        pipe.delete(self._https_index)
        items = self.__conn.hgetall(self.name) or {}
        for proxy_str, raw in items.items():
            try:
                if json.loads(raw).get("https"):
                    pipe.sadd(self._https_index, proxy_str)
            except Exception:
                continue
        pipe.execute()

    def _https_keys(self):
        keys = list(self.__conn.smembers(self._https_index) or [])
        if keys:
            return keys
        if self.__conn.hlen(self.name):
            self._rebuild_https_index()
            keys = list(self.__conn.smembers(self._https_index) or [])
        return keys

    def get(self, https):
        """
        从hash中随机返回一个代理
        :return:
        """
        if https:
            keys = self._https_keys()
            if not keys:
                return None
            proxy = choice(keys)
            return self.__conn.hget(self.name, proxy)
        proxies = self.__conn.hkeys(self.name)
        proxy = choice(proxies) if proxies else None
        return self.__conn.hget(self.name, proxy) if proxy else None

    def put(self, proxy_obj):
        """
        将代理放入hash
        :param proxy_obj: Proxy obj
        :return:
        """
        result = self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)
        self._sync_https_index(proxy_obj.proxy, bool(proxy_obj.https))
        return result

    def pop(self, https):
        """
        顺序弹出一个代理
        :return: proxy
        """
        proxy = self.get(https)
        if proxy:
            proxy_str = json.loads(proxy).get("proxy", "")
            self.__conn.hdel(self.name, proxy_str)
            self.__conn.srem(self._https_index, proxy_str)
        return proxy if proxy else None

    def delete(self, proxy_str):
        """
        移除指定代理, 使用changeTable指定hash name
        :param proxy_str: proxy str
        :return:
        """
        self.__conn.hdel(self.name, proxy_str)
        self.__conn.srem(self._https_index, proxy_str)

    def getItem(self, proxy_str):
        """
        ? key ?????? JSON
        :param proxy_str: proxy str
        :return: json str or None
        """
        if not proxy_str:
            return None
        return self.__conn.hget(self.name, proxy_str)

    def exists(self, proxy_str):
        """
        判断指定代理是否存在, 使用changeTable指定hash name
        :param proxy_str: proxy str
        :return:
        """
        return self.__conn.hexists(self.name, proxy_str)

    def update(self, proxy_obj):
        """
        更新 proxy 属性
        :param proxy_obj:
        :return:
        """
        self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)
        self._sync_https_index(proxy_obj.proxy, bool(proxy_obj.https))

    def getAll(self, https):
        """
        字典形式返回所有代理, 使用changeTable指定hash name
        :return:
        """
        if https:
            keys = self._https_keys()
            if not keys:
                return []
            values = self.__conn.hmget(self.name, keys)
            return [item for item in values if item]
        return list(self.__conn.hvals(self.name))

    def clear(self):
        """
        清空所有代理, 使用changeTable指定hash name
        :return:
        """
        pipe = self.__conn.pipeline()
        pipe.delete(self.name)
        pipe.delete(self._https_index)
        return pipe.execute()

    def getCount(self):
        """
        返回代理数量
        :return:
        """
        total = self.__conn.hlen(self.name)
        https = self.__conn.scard(self._https_index)
        if total > 0 and https == 0:
            self._rebuild_https_index()
            https = self.__conn.scard(self._https_index)
        elif https > total:
            self._rebuild_https_index()
            https = self.__conn.scard(self._https_index)
        return {'total': total, 'https': https}

    def changeTable(self, name):
        """
        切换操作对象
        :param name:
        :return:
        """
        self.name = name

    def test(self):
        log = LogHandler('ssdb_client')
        try:
            self.getCount()
        except TimeoutError as e:
            log.error('ssdb connection time out: %s' % str(e), exc_info=True)
            return e
        except ConnectionError as e:
            log.error('ssdb connection error: %s' % str(e), exc_info=True)
            return e
        except ResponseError as e:
            log.error('ssdb connection error: %s' % str(e), exc_info=True)
            return e
