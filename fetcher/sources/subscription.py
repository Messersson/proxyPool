# -*- coding: utf-8 -*-
"""从已保存的 Clash/节点订阅链接采集 HTTP 代理"""
from fetcher.baseFetcher import BaseFetcher
from handler.logHandler import LogHandler
from handler import subscriptionStore
from helper.subscription import import_from_url

logger = LogHandler("fetcher")


class SubscriptionFetcher(BaseFetcher):
    """读取 data/subscriptions.json 中启用的订阅链接"""

    name = "subscription"
    url = "local://subscriptions"
    enabled = True

    def fetch(self):
        items = subscriptionStore.enabled_subscription_urls()
        if not items:
            return
        for item in items:
            url = item.get("url") or ""
            source = item.get("name") or item.get("id") or "subscription"
            try:
                result = import_from_url(url, source_name=source, write_pool=True)
                for proxy in result.get("proxies") or []:
                    yield proxy
                # 协议节点已在 import_from_url(write_pool=True) 时入库
                # 这里额外 yield 便于日志观察数量
                for n in result.get("nodes") or []:
                    if str(n.get("type") or "").lower() not in ("http", "https"):
                        nid = n.get("id")
                        if nid:
                            yield "node:%s" % nid
                # 更新最近同步摘要
                try:
                    item["last_sync_at"] = result.get("fetched_at")
                    item["last_sync_stats"] = result.get("stats") or {}
                    item["last_sync_pool"] = result.get("pool") or {}
                    item["last_error"] = result.get("error") or ""
                    subscriptionStore.upsert_subscription(item)
                except Exception as e:
                    logger.error("ProxyFetch - subscription save meta error: %s" % e)
            except Exception as e:
                logger.error("ProxyFetch - subscription %s error: %s" % (source, e))


if __name__ == "__main__":
    for proxy in SubscriptionFetcher().fetch():
        print(proxy)
