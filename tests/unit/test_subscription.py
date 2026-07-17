# -*- coding: utf-8 -*-
"""Clash/节点订阅解析与导入测试"""
from helper.subscription import parse_subscription_text, import_from_text


class TestParseSubscription:

    def test_parse_clash_yaml_http_and_skip_vmess(self):
        content = """
proxies:
  - {name: a, type: http, server: 1.2.3.4, port: 8080}
  - {name: b, type: vmess, server: 2.2.2.2, port: 443}
  - name: c
    type: https
    server: proxy.example.com
    port: 8443
    username: u
    password: p
"""
        result = parse_subscription_text(content, source_name="t")
        assert result["format"].startswith("clash")
        assert "1.2.3.4:8080" in result["proxies"]
        assert "u:p@proxy.example.com:8443" in result["proxies"]
        assert result["stats"]["http_nodes"] >= 1
        assert result["stats"]["protocol_nodes"] >= 1

    def test_parse_text_proxies(self):
        content = "1.1.1.1:8080\n8.8.8.8:3128\n"
        result = parse_subscription_text(content)
        assert "1.1.1.1:8080" in result["proxies"]
        assert "8.8.8.8:3128" in result["proxies"]

    def test_parse_base64_text(self):
        import base64
        raw = "9.9.9.9:8080\n"
        content = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        result = parse_subscription_text(content)
        assert "9.9.9.9:8080" in result["proxies"]

    def test_import_from_text_writes_pool(self, app):
        # app fixture mocks db; still exercise write path with mocked handler
        from unittest.mock import patch, MagicMock
        from helper.proxy import Proxy
        with patch("helper.subscription.ProxyHandler") as mock_cls:
            handler = MagicMock()
            handler.exists.return_value = False
            mock_cls.return_value = handler
            result = import_from_text("1.2.3.4:8080\n", source_name="paste", write_pool=True)
            assert result["pool"]["added"] == 1
            assert handler.put.called


    def test_parse_share_links(self):
        content = "\n".join([
            "ss://YWVzLTI1Ni1nY206cGFzc0AxLjIuMy40OjgzODg#ss-node",
            "trojan://password@example.com:443?sni=example.com#trojan-node",
            "1.2.3.4:8080",
        ])
        result = parse_subscription_text(content)
        assert result["stats"]["total_nodes"] >= 2
        assert any(n.get("type") in ("ss", "trojan") for n in result["nodes"])


def test_node_pool_get_count(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_NODES_FILE", str(tmp_path / "nodes.json"))
    from helper.subscription import import_from_text, get_node, count_nodes
    content = """
proxies:
  - {name: v1, type: vmess, server: 2.2.2.2, port: 443}
  - {name: s1, type: ss, server: 3.3.3.3, port: 8388, cipher: aes-256-gcm, password: x}
"""
    result = import_from_text(content, source_name="t", write_pool=False, save_nodes_flag=True)
    assert result["stats"]["protocol_nodes"] >= 2
    c = count_nodes()
    assert c["count"] >= 2
    n = get_node(node_type="vmess")
    assert n is not None
    assert n["type"] == "vmess"


def test_import_nodes_into_proxy_pool(tmp_path, monkeypatch):
    monkeypatch.setenv("PROXY_POOL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PROXY_POOL_NODES_FILE", str(tmp_path / "nodes.json"))
    from helper.proxy import Proxy
    from unittest.mock import patch, MagicMock
    content = """
proxies:
  - {name: a, type: http, server: 1.2.3.4, port: 8080}
  - {name: b, type: vmess, server: 2.2.2.2, port: 443}
  - {name: c, type: ss, server: 3.3.3.3, port: 8388, cipher: aes-256-gcm, password: x}
"""
    put_keys = []
    class H:
        def exists(self, obj):
            return False
        def put(self, obj):
            put_keys.append(obj.proxy)
            return True
    with patch("helper.subscription.ProxyHandler", return_value=H()):
        from helper.subscription import import_from_text
        result = import_from_text(content, source_name="t", write_pool=True, save_nodes_flag=True)
    assert result["pool"]["total"] >= 3
    assert any(k == "1.2.3.4:8080" for k in put_keys)
    assert any(str(k).startswith("node:") for k in put_keys)
