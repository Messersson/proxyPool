# -*- coding: utf-8 -*-
from helper.proxy import Proxy
from unittest.mock import patch


def _handler_with(p1, p2):
    class H:
        def getAll(self, https=False):
            return [p1, p2]

        @property
        def db(self):
            class D:
                def getCount(self_inner):
                    return {"total": 2}

            return D()

    return H()


def test_compatible_default_fields(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))

    p1 = Proxy("1.1.1.1:8080", source="t")
    p2 = Proxy("2.2.2.2:8080", source="t")
    with patch("helper.proxyDispatcher.ProxyHandler", return_value=_handler_with(p1, p2)):
        resp = client.get("/compatible/?client_id=app1&pool=http&strategy=round_robin&lease=60")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == 0
        assert data["ok"] is True
        assert data["proxy"] in ("1.1.1.1:8080", "2.2.2.2:8080")
        assert data["hostport"] == data["proxy"]
        assert data["address"] == data["proxy"]
        assert data["proxy_url"].startswith("http://")
        assert data["HTTP_PROXY"] == data["proxy_url"]
        assert data["HTTPS_PROXY"] == data["proxy_url"]
        assert data["proxies"]["http"] == data["proxy_url"]
        assert data["requests"]["https"] == data["proxy_url"]
        assert data["httpx"] == data["proxy_url"]
        assert data["curl_flag"].startswith("-x ")
        assert "export HTTP_PROXY=" in data["export"]
        assert "compatible" in data and "formats" in data
        assert data["formats"]["text"] == data["proxy"]
        assert data["formats"]["url"] == data["proxy_url"]
        assert data["host"] in ("1.1.1.1", "2.2.2.2")
        assert int(data["port"]) == 8080


def test_compatible_alias_and_text_formats(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))

    p1 = Proxy("10.0.0.1:3128", source="t")
    p2 = Proxy("10.0.0.2:3128", source="t")
    with patch("helper.proxyDispatcher.ProxyHandler", return_value=_handler_with(p1, p2)):
        r1 = client.get("/v1/compatible?client_id=x&pool=http&lease=30")
        assert r1.status_code == 200
        assert r1.get_json()["proxy_url"].startswith("http://")

        r2 = client.get("/compatible?client_id=x&pool=http&format=text")
        assert r2.status_code == 200
        assert r2.content_type.startswith("text/plain")
        assert r2.data.decode("utf-8") in ("10.0.0.1:3128", "10.0.0.2:3128")

        r3 = client.get("/compatible?client_id=x&pool=http&format=url")
        assert r3.status_code == 200
        body = r3.data.decode("utf-8")
        assert body.startswith("http://")

        r4 = client.get("/compatible?client_id=x&pool=http&format=env")
        assert r4.status_code == 200
        assert "export HTTP_PROXY=" in r4.data.decode("utf-8")

        r5 = client.get("/compatible?client_id=x&pool=http&format=curl")
        assert r5.status_code == 200
        assert r5.data.decode("utf-8").startswith("-x http://")


def test_v1_proxy_compatible_format(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_FILE", str(tmp_path / "dispatch_rules.json"))
    monkeypatch.setenv("PROXY_POOL_DISPATCH_STATE", str(tmp_path / "dispatch_state.json"))

    p1 = Proxy("8.8.8.8:8080", source="t")
    p2 = Proxy("8.8.4.4:8080", source="t")
    with patch("helper.proxyDispatcher.ProxyHandler", return_value=_handler_with(p1, p2)):
        resp = client.get("/v1/proxy/?client_id=fmt&pool=http&format=compatible")
        data = resp.get_json()
        assert data["code"] == 0
        assert data["HTTP_PROXY"].startswith("http://")
        assert "formats" in data
