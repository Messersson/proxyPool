# -*- coding: utf-8 -*-
"""
-------------------------------------------------
   File Name：     conftest.py
   Description :   测试共享fixtures
   Author :        JHao
   date：          2026/5/28
-------------------------------------------------
   Change Activity:
                   2026/05/28:
-------------------------------------------------
"""
__author__ = 'JHao'

import sys
import os
from unittest.mock import MagicMock, patch

import pytest
import fakeredis

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from util.singleton import Singleton
from helper.proxy import Proxy



@pytest.fixture(autouse=True)
def isolate_runtime_config(tmp_path_factory, monkeypatch):
    """避免测试读写真实 data/runtime_config.json"""
    base = tmp_path_factory.mktemp("runtime_cfg")
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(base))
    monkeypatch.setenv("PROXY_POOL_CONFIG_FILE", str(base / "runtime_config.json"))
    try:
        from handler import configStore
        configStore.clear_runtime_cache()
    except Exception:
        pass
    yield
    try:
        from handler import configStore
        configStore.clear_runtime_cache()
    except Exception:
        pass


# --------------- Singleton 重置 ---------------

@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前清空 Singleton 缓存，防止测试间状态泄漏"""
    saved = Singleton._inst.copy()
    Singleton._inst.clear()
    yield
    Singleton._inst.clear()
    Singleton._inst.update(saved)


# --------------- Proxy 工厂 ---------------

@pytest.fixture
def proxy_obj():
    """标准测试用 Proxy 对象"""
    return Proxy("1.2.3.4:8080", source="test", https=False)


@pytest.fixture
def https_proxy_obj():
    """HTTPS 测试用 Proxy 对象"""
    return Proxy("5.6.7.8:443", source="test", https=True)


# --------------- Redis / DB ---------------

@pytest.fixture
def fake_redis():
    """fakeredis 实例，用于 RedisClient/SsdbClient 测试"""
    return fakeredis.FakeRedis(decode_responses=True, protocol=2)


@pytest.fixture
def mock_db_client(fake_redis):
    """mock DbClient，返回 fakeredis 支持的 RedisClient 行为"""
    with patch("db.dbClient.DbClient") as mock_cls:
        yield mock_cls, fake_redis


# --------------- Flask API ---------------

@pytest.fixture
def app():
    """Flask app，proxy_handler 被 mock"""
    # mock 掉 DbClient，防止 ProxyHandler 连接真实 Redis
    # 必须 patch handler.proxyHandler.DbClient（已 import 到本地命名空间）
    with patch("handler.proxyHandler.DbClient") as mock_db_cls:
        mock_db_instance = MagicMock()
        mock_db_cls.return_value = mock_db_instance

        from api.proxyApi import app as flask_app, proxy_handler
        from handler.configHandler import ConfigHandler
        from handler import configStore
        configStore.clear_runtime_cache()
        ConfigHandler().reload()
        flask_app.config["TESTING"] = True

        # 替换 proxy_handler 的方法为 MagicMock，方便测试中配置返回值
        with patch.object(proxy_handler, "get") as mock_get, \
             patch.object(proxy_handler, "pop") as mock_pop, \
             patch.object(proxy_handler, "getAll") as mock_getAll, \
             patch.object(proxy_handler, "delete") as mock_delete:
            flask_app._test_mocks = {
                "get": mock_get,
                "pop": mock_pop,
                "getAll": mock_getAll,
                "delete": mock_delete,
            }
            yield flask_app


@pytest.fixture
def client(app):
    """Flask test client"""
    return app.test_client()