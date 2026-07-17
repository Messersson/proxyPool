# -*- coding: utf-8 -*-
from helper.proxyDispatcher import acquire, release, current, save_rules, load_rules, status


def test_round_robin_and_lease(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))
    monkeypatch.setenv("PROXY_POOL_NODES_FILE", str(tmp_path / "nodes.json"))

    # fake http candidates via ProxyHandler.getAll
    from helper.proxy import Proxy
    from unittest.mock import patch

    p1 = Proxy("1.1.1.1:8080", source="t", https=False)
    p2 = Proxy("2.2.2.2:8080", source="t", https=True)

    class H:
        def getAll(self, https=False):
            return [p1, p2]
        def getCount(self):
            return {"count": {"total": 2}}
        @property
        def db(self):
            class D:
                def getCount(self_inner):
                    return {"total": 2}
            return D()

    with patch("helper.proxyDispatcher.ProxyHandler", return_value=H()):
        save_rules({"strategy": "round_robin", "pool": "http", "lease_seconds": 60})
        a = acquire(client_id="c1", request_ip="127.0.0.1")
        assert a["code"] == 0
        first = a["item"]["proxy"]
        b = acquire(client_id="c1", request_ip="127.0.0.1")
        assert b["item"]["proxy"] == first  # lease reuse
        c = acquire(client_id="c1", request_ip="127.0.0.1", force_rotate=True)
        assert c["item"]["proxy"] in ("1.1.1.1:8080", "2.2.2.2:8080")
        # specified
        d = acquire(client_id="c2", proxy="2.2.2.2:8080")
        assert d["item"]["proxy"] == "2.2.2.2:8080"
        cur = current(client_id="c2")
        assert cur["item"]["proxy"] == "2.2.2.2:8080"
        release(client_id="c2")
        cur2 = current(client_id="c2")
        assert cur2.get("item") is None


def test_v1_proxy_api(client, monkeypatch, tmp_path):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))
    from helper.proxy import Proxy
    from unittest.mock import patch

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
        r = client.get("/v1/proxy/?client_id=demo&pool=http&strategy=round_robin&lease=30")
        assert r.status_code == 200
        data = r.get_json()
        assert data["code"] == 0
        assert data["item"]["proxy"] in ("1.1.1.1:8080", "2.2.2.2:8080")

        r2 = client.get("/v1/proxy/current?client_id=demo")
        assert r2.status_code == 200
        assert r2.get_json()["item"]["proxy"] == data["item"]["proxy"]

        r3 = client.post("/v1/proxy/rules", json={"strategy": "random", "lease_seconds": 10, "pool": "http"})
        assert r3.status_code == 200
        assert r3.get_json()["rules"]["strategy"] == "random"

        st = client.get("/v1/proxy/status").get_json()
        assert "rules" in st


def test_skip_timeout_nodes(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))
    from helper.proxy import Proxy
    from helper.proxyDispatcher import acquire, save_rules
    from unittest.mock import patch

    good = Proxy("1.1.1.1:8080", source="t", last_status=True, latency_ms=80)
    bad = Proxy("2.2.2.2:8080", source="t", last_status=False, latency_ms=-1)

    class H:
        def getAll(self, https=False):
            return [bad, good]
        @property
        def db(self):
            class D:
                def getCount(self_inner):
                    return {"total": 2}
            return D()

    with patch("helper.proxyDispatcher.ProxyHandler", return_value=H()):
        save_rules({"strategy": "round_robin", "pool": "http", "lease_seconds": 30, "skip_timeout": True})
        a = acquire(client_id="lat1", force_rotate=True)
        assert a["code"] == 0
        assert a["item"]["proxy"] == "1.1.1.1:8080"
