# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     configHandler
   Description :
   Author :        JHao
   date：          2020/6/22
-------------------------------------------------
   Change Activity:
                   2020/6/22:
                   2026/7/16: 环境变量布尔/整数解析与鉴权配置
                   2026/7/16: 支持 runtime_config.json 持久化与热加载
-------------------------------------------------
"""
__author__ = 'JHao'

import os
import setting
from util.singleton import Singleton
from util.six import reload_six, withMetaclass
from handler import configStore


def _env_get(key, default=None):
    return os.environ.get(key, default)


def _env_bool(key, default):
    """
    解析布尔环境变量。
    支持 true/false/1/0/yes/no/on/off（大小写不敏感）。
    未设置时返回 default；非法值回退 default。
    """
    raw = os.environ.get(key, None)
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    if value in ("1", "true", "yes", "y", "on"):
        return True
    if value in ("0", "false", "no", "n", "off", ""):
        return False
    return bool(default)


def _env_int(key, default):
    raw = os.environ.get(key, None)
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return int(default)


class ConfigHandler(withMetaclass(Singleton)):

    def __init__(self):
        self._cache = {}
        self.reload()

    def reload(self):
        """重新加载 setting + runtime_config（不覆盖环境变量优先级）"""
        configStore.clear_runtime_cache()
        # 先从 setting.py 恢复默认，再叠加 runtime 配置，避免进程内污染
        reload_six(setting)
        configStore.apply_saved_to_setting_module()
        self._cache = {}

    def save(self, payload, merge=True):
        """保存网页提交的配置并立即热加载"""
        saved = configStore.save_runtime_config(payload, merge=merge)
        self.reload()
        return saved

    def _get(self, key):
        if key not in self._cache:
            value, _source = configStore.get_effective_value(key)
            self._cache[key] = value
        return self._cache[key]

    def get_view(self, mask_secrets=True):
        return configStore.build_config_view(mask_secrets=mask_secrets)

    @property
    def serverHost(self):
        return self._get("HOST")

    @property
    def serverPort(self):
        return self._get("PORT")

    @property
    def apiToken(self):
        return self._get("API_TOKEN") or ""

    @property
    def dbConn(self):
        return self._get("DB_CONN")

    @property
    def tableName(self):
        return self._get("TABLE_NAME")

    @property
    def fetcherExclude(self):
        return self._get("PROXY_FETCHER_EXCLUDE") or []

    @property
    def httpUrl(self):
        return self._get("HTTP_URL")

    @property
    def httpsUrl(self):
        return self._get("HTTPS_URL")

    @property
    def verifyTimeout(self):
        return int(self._get("VERIFY_TIMEOUT"))

    @property
    def maxFailCount(self):
        return int(self._get("MAX_FAIL_COUNT"))

    @property
    def poolSizeMin(self):
        return int(self._get("POOL_SIZE_MIN"))

    @property
    def checkThreadCount(self):
        return max(1, int(self._get("CHECK_THREAD_COUNT")))

    @property
    def proxyRegion(self):
        return bool(self._get("PROXY_REGION"))

    @property
    def timezone(self):
        return self._get("TIMEZONE")

    @property
    def fetchIntervalMinutes(self):
        return max(1, int(self._get("FETCH_INTERVAL_MINUTES")))

    @property
    def checkIntervalMinutes(self):
        return max(1, int(self._get("CHECK_INTERVAL_MINUTES")))

    @property
    def schedulerMaxInstances(self):
        return max(1, int(self._get("SCHEDULER_MAX_INSTANCES")))
