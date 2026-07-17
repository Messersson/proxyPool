# -*- coding: utf-8 -*-
"""订阅管理 API 测试"""
import json
from unittest.mock import patch


class TestSubscriptionApi:

    def test_list_empty(self, client, temp_config=None):
        # use isolated data dir from autouse fixture
        resp = client.get("/admin/subscriptions/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["items"] == []

    def test_import_content(self, client):
        content = """
proxies:
  - {name: a, type: http, server: 1.2.3.4, port: 8080}
  - {name: b, type: vmess, server: 2.2.2.2, port: 443}
"""
        with patch("helper.subscription.ProxyHandler") as mock_cls:
            handler = mock_cls.return_value
            handler.exists.return_value = False
            resp = client.post("/admin/subscriptions/import/", json={
                "content": content,
                "name": "demo",
                "write_pool": True,
                "save": False,
            })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == 0
        assert "1.2.3.4:8080" in data["result"]["proxies"]
        assert data["result"]["stats"].get("protocol_nodes", 0) >= 1

    def test_save_and_delete_subscription(self, client):
        resp = client.post("/admin/subscriptions/", json={
            "name": "my-sub",
            "url": "https://example.com/clash.yaml",
            "enabled": True,
        })
        assert resp.status_code == 200
        item = resp.get_json()["item"]
        sid = item["id"]
        assert item["url"].startswith("https://")

        listed = client.get("/admin/subscriptions/").get_json()
        assert listed["count"] == 1

        deleted = client.delete(f"/admin/subscriptions/?id={sid}")
        assert deleted.status_code == 200
        assert client.get("/admin/subscriptions/").get_json()["count"] == 0


    def test_list_nodes_after_import(self, client):
        content = """
proxies:
  - {name: a, type: http, server: 1.2.3.4, port: 8080}
  - {name: b, type: vmess, server: 2.2.2.2, port: 443}
"""
        with patch("helper.subscription.ProxyHandler") as mock_cls:
            handler = mock_cls.return_value
            handler.exists.return_value = False
            client.post("/admin/subscriptions/import/", json={
                "content": content,
                "name": "demo",
                "write_pool": True,
                "save": False,
            })
        resp = client.get("/admin/nodes/")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] >= 1


    def test_node_get_after_import(self, client):
        content = """
proxies:
  - {name: a, type: http, server: 1.2.3.4, port: 8080}
  - {name: b, type: vmess, server: 2.2.2.2, port: 443}
"""
        with patch("helper.subscription.ProxyHandler") as mock_cls:
            mock_cls.return_value.exists.return_value = False
            client.post("/admin/subscriptions/import/", json={
                "content": content,
                "name": "demo",
                "write_pool": False,
                "save": False,
            })
        resp = client.get("/node/count/")
        assert resp.status_code == 200
        assert resp.get_json()["count"] >= 1

        got = client.get("/node/get/?type=vmess")
        assert got.status_code == 200
        data = got.get_json()
        assert data.get("type") == "vmess" or data.get("src") == "no node"

        all_resp = client.get("/node/all/?type=vmess")
        assert all_resp.status_code == 200
        assert "items" in all_resp.get_json()
