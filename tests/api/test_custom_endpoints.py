# -*- coding: utf-8 -*-
from helper.proxy import Proxy
from unittest.mock import patch


def test_custom_endpoint_independent_rules(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_ENDPOINTS_FILE", str(tmp_path / "proxy_endpoints.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))

    # create endpoint
    resp = client.post("/admin/endpoints/", json={
        "slug": "crawler-a",
        "name": "爬虫A",
        "rules": {"strategy": "round_robin", "pool": "http", "lease_seconds": 120}
    })
    assert resp.status_code == 200
    item = resp.get_json()["item"]
    assert item["path"] == "/open/crawler-a"
    assert item["rules"]["lease_seconds"] == 120

    p1 = Proxy("1.1.1.1:8080", source="t")
    p2 = Proxy("2.2.2.2:8080", source="t")

    class H:
        def getAll(self, https=False):
            return [p1, p2]
        @property
        def db(self):
            class D:
                def getCount(self_inner):
                    return {"total": 2}
            return D()

    with patch("helper.proxyDispatcher.ProxyHandler", return_value=H()):
        r1 = client.get("/open/crawler-a/?client_id=w1")
        assert r1.status_code == 200
        d1 = r1.get_json()
        assert d1["code"] == 0
        assert d1["item"]["proxy"] in ("1.1.1.1:8080", "2.2.2.2:8080")
        # lease reuse
        r2 = client.get("/open/crawler-a/?client_id=w1")
        assert r2.get_json()["item"]["proxy"] == d1["item"]["proxy"]
        # rotate
        r3 = client.get("/open/crawler-a/?client_id=w1&rotate=1")
        assert r3.get_json()["item"]["proxy"] in ("1.1.1.1:8080", "2.2.2.2:8080")

    listed = client.get("/admin/endpoints/").get_json()
    assert listed["count"] == 1
    deleted = client.delete("/admin/endpoints/?slug=crawler-a")
    assert deleted.status_code == 200
    assert client.get("/admin/endpoints/").get_json()["count"] == 0
