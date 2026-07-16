# -*- coding: utf-8 -*-
"""管理页配置 API 测试"""
import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def temp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "runtime_config.json"
    monkeypatch.setenv("PROXY_POOL_CONFIG_FILE", str(cfg))
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    for k in [
        "DB_CONN", "PORT", "HOST", "TABLE_NAME", "HTTP_URL", "HTTPS_URL",
        "VERIFY_TIMEOUT", "MAX_FAIL_COUNT", "POOL_SIZE_MIN", "PROXY_REGION",
        "TIMEZONE", "API_TOKEN", "CHECK_THREAD_COUNT", "FETCH_INTERVAL_MINUTES",
        "CHECK_INTERVAL_MINUTES", "SCHEDULER_MAX_INSTANCES",
    ]:
        monkeypatch.delenv(k, raising=False)
    from handler import configStore
    from util.singleton import Singleton
    configStore.clear_runtime_cache()
    Singleton._inst.clear()
    yield cfg
    configStore.clear_runtime_cache()
    Singleton._inst.clear()


@pytest.fixture
def admin_client(temp_config, app):
    # 重新加载 conf，绑定到临时配置文件
    from api import proxyApi as api_mod
    api_mod.conf.reload()
    return app.test_client()


class TestAdminConfigPage:

    def test_page_returns_html(self, admin_client):
        resp = admin_client.get("/admin/config")
        assert resp.status_code == 200
        assert b"ProxyPool" in resp.data
        assert b"configForm" in resp.data


class TestAdminConfigApi:

    def test_get_config(self, admin_client):
        resp = admin_client.get("/admin/config/api")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "fields" in data
        assert "values" in data
        assert any(f["key"] == "PORT" for f in data["fields"])

    def test_save_config_persists(self, admin_client, temp_config):
        resp = admin_client.post(
            "/admin/config/api",
            json={
                "PORT": 5055,
                "MAX_FAIL_COUNT": 4,
                "PROXY_FETCHER_EXCLUDE": "freevpnnode,kuaidaili",
                "PROXY_REGION": False,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == 0
        assert temp_config.exists()
        saved = json.loads(temp_config.read_text(encoding="utf-8"))
        assert saved["PORT"] == 5055
        assert saved["MAX_FAIL_COUNT"] == 4
        assert saved["PROXY_REGION"] is False
        assert saved["PROXY_FETCHER_EXCLUDE"] == ["freevpnnode", "kuaidaili"]

        # 热加载后可读到新值
        from api import proxyApi as api_mod
        assert str(api_mod.conf.serverPort) == "5055"
        assert api_mod.conf.maxFailCount == 4
        assert api_mod.conf.proxyRegion is False

    def test_save_invalid(self, admin_client):
        resp = admin_client.post("/admin/config/api", json={"PORT": 99999})
        assert resp.status_code == 400
        assert resp.get_json()["code"] == 400

    def test_save_requires_token_when_set(self, admin_client, monkeypatch):
        from api import proxyApi as api_mod
        # 先通过内部保存设置 token
        api_mod.conf.save({"API_TOKEN": "secret-xyz"})
        resp = admin_client.post("/admin/config/api", json={"MAX_FAIL_COUNT": 2})
        assert resp.status_code == 401

        resp2 = admin_client.post(
            "/admin/config/api",
            json={"MAX_FAIL_COUNT": 2},
            headers={"X-API-Token": "secret-xyz"},
        )
        assert resp2.status_code == 200
        assert resp2.get_json()["code"] == 0
