# -*- coding: utf-8 -*-
"""
-----------------------------------------------------
   File Name：     redisClient.py
   Description :   封装Redis相关操作
   Author :        JHao
   date：          2019/8/9
------------------------------------------------------
   Change Activity:
                   2019/08/09: 封装Redis相关操作
                   2020/06/23: 优化pop方法, 改用hscan命令
                   2021/05/26: 区别http/https代理
                   2026/07/16: HTTPS 二级索引，加速 get/count
------------------------------------------------------
"""
__author__ = 'JHao'

from redis.exceptions import TimeoutError, ConnectionError, ResponseError
from redis.connection import BlockingConnectionPool
from handler.logHandler import LogHandler
from random import choice
from redis import Redis
import json


class RedisClient(object):
    """
    Redis client

    Redis中代理存放的结构为hash：
    key为ip:port, value为代理属性的字典;

    HTTPS 代理额外维护 set: {table}:https，用于快速随机取与计数。
    """

    def __init__(self, **kwargs):
        """
        init
        :param host: host
        :param port: port
        :param password: password
        :param db: db
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
        """根据 hash 数据重建 HTTPS 索引（兼容旧数据）"""
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
        # 索引为空但主表有数据时，尝试重建一次
        if self.__conn.hlen(self.name):
            self._rebuild_https_index()
            keys = list(self.__conn.smembers(self._https_index) or [])
        return keys

    def get(self, https):
        """
        返回一个代理
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
        将代理放入hash, 使用changeTable指定hash name
        :param proxy_obj: Proxy obj
        :return:
        """
        data = self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)
        self._sync_https_index(proxy_obj.proxy, bool(proxy_obj.https))
        return data

    def pop(self, https):
        """
        弹出一个代理
        :return: dict {proxy: value}
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
        result = self.__conn.hdel(self.name, proxy_str)
        self.__conn.srem(self._https_index, proxy_str)
        return result

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
        data = self.__conn.hset(self.name, proxy_obj.proxy, proxy_obj.to_json)
        self._sync_https_index(proxy_obj.proxy, bool(proxy_obj.https))
        return data

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
        return self.__conn.hvals(self.name)

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
        # 旧数据无索引时自动修复
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
        log = LogHandler('redis_client')
        try:
            self.getCount()
        except TimeoutError as e:
            log.error('redis connection time out: %s' % str(e), exc_info=True)
            return e
        except ConnectionError as e:
            log.error('redis connection error: %s' % str(e), exc_info=True)
            return e
        except ResponseError as e:
            log.error('redis connection error: %s' % str(e), exc_info=True)
            return e
