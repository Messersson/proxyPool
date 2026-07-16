# -*- coding: utf-8 -*-
"""configStore / 配置保存单元测试"""
import json
import os
from pathlib import Path

import pytest

from handler import configStore
from handler.configHandler import ConfigHandler
from util.singleton import Singleton


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "runtime_config.json"
    monkeypatch.setenv("PROXY_POOL_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    # 清理相关环境变量，避免干扰
    for k in [
        "DB_CONN", "PORT", "HOST", "TABLE_NAME", "HTTP_URL", "HTTPS_URL",
        "VERIFY_TIMEOUT", "MAX_FAIL_COUNT", "POOL_SIZE_MIN", "PROXY_REGION",
        "TIMEZONE", "API_TOKEN", "CHECK_THREAD_COUNT", "FETCH_INTERVAL_MINUTES",
        "CHECK_INTERVAL_MINUTES", "SCHEDULER_MAX_INSTANCES",
    ]:
        monkeypatch.delenv(k, raising=False)
    configStore.clear_runtime_cache()
    Singleton._inst.clear()
    yield cfg
    configStore.clear_runtime_cache()
    Singleton._inst.clear()


class TestConfigStore:

    def test_save_and_load(self, temp_config):
        saved = configStore.save_runtime_config({
            "PORT": 5020,
            "MAX_FAIL_COUNT": 3,
            "PROXY_REGION": False,
            "PROXY_FETCHER_EXCLUDE": "a,b",
        })
        assert temp_config.exists()
        assert saved["PORT"] == 5020
        assert saved["MAX_FAIL_COUNT"] == 3
        assert saved["PROXY_REGION"] is False
        assert saved["PROXY_FETCHER_EXCLUDE"] == ["a", "b"]

        loaded = configStore.load_runtime_config(force=True)
        assert loaded["PORT"] == 5020

    def test_merge_keeps_old_keys(self, temp_config):
        configStore.save_runtime_config({"PORT": 5011, "API_TOKEN": "old"})
        configStore.save_runtime_config({"PORT": 5012}, merge=True)
        data = configStore.load_runtime_config(force=True)
        assert data["PORT"] == 5012
        assert data["API_TOKEN"] == "old"

    def test_invalid_port(self, temp_config):
        with pytest.raises(ValueError):
            configStore.save_runtime_config({"PORT": 70000})

    def test_env_overrides_runtime(self, temp_config, monkeypatch):
        configStore.save_runtime_config({"PORT": 5015})
        monkeypatch.setenv("PORT", "5099")
        value, source = configStore.get_effective_value("PORT")
        assert value == 5099
        assert source == "env"

    def test_config_handler_reload(self, temp_config):
        conf = ConfigHandler()
        conf.save({"MAX_FAIL_COUNT": 9, "HTTP_URL": "http://example.com"})
        assert conf.maxFailCount == 9
        assert conf.httpUrl == "http://example.com"
        # 再次实例应是单例且值一致
        conf2 = ConfigHandler()
        assert conf2 is conf
        assert conf2.maxFailCount == 9
