
# tests/test_data_service.py
import os
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
import pandas as pd


from bll.data_source_service import (
    BinanceFuturesUSDTClient,
    pad_to_hour_grid,
    fetch_top50_last_year_1h_history_ge_1y,
)

# -------- 一个最小可用的 fake ccxt 客户端 --------
class FakeBinanceUSDM:
    def __init__(self, markets=None, tickers=None, ohlcv_pages=None):
        self.markets = markets or {}
        self._tickers = tickers or {}
        self._ohlcv_pages = ohlcv_pages or []
        self._ohlcv_call = 0
        self.has = {"fetchTickers": True}

    def load_markets(self, reload=False):
        return self.markets

    def fetch_tickers(self):
        return self._tickers

    def fetch_ohlcv(self, symbol, timeframe="1h", since=None, limit=None):
        # 依次返回预置分页；返回 [] 代表结束
        if self._ohlcv_call < len(self._ohlcv_pages):
            page = self._ohlcv_pages[self._ohlcv_call]
            self._ohlcv_call += 1
            return page
        return []

class TestDataService(unittest.TestCase):
    # ---------- 纯函数：补齐到整点网格 ----------
    def test_pad_to_hour_grid(self):
        start = datetime(2024, 1, 1, 0, 0, 0)
        end   = datetime(2024, 1, 1, 5, 0, 0)
        raw = pd.DataFrame({
            "DateTime": [start, start + timedelta(hours=2), start + timedelta(hours=5)],
            "open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3],
            "close": [1, 2, 3], "volume": [10, 20, 30],
        })
        out = pad_to_hour_grid(raw, start, end)
        self.assertEqual(len(out), 6)          # 0~5 共 6 小时
        self.assertEqual(out["volume"].iloc[1], 0)   # 缺口 volume=0
        self.assertEqual(out["close"].isna().sum(), 0)  # close 前向填充

    # ---------- USDT 永续筛选（当前实现） ----------
    def test_fetch_usdt_perp_symbols_current_logic(self):
        """
        你当前实现按 m['quote']=="USDT" 且 info.contractType=="PERPETUAL" 且 active=True，
        还会读取 m['volume'] 作为排序依据（在真实 ccxt 的 markets 里通常没有 volume 字段；
        但单测里我们可以提供），并不依赖 ccxt 网络。
        """
        markets = {
            # 带冒号（真实 ccxt 常见），仍满足 USDT & PERPETUAL & active
            "BTC/USDT:USDT": {
                "symbol":"BTC/USDT:USDT","quote":"USDT","active":True,
                "contract":True,"swap":True,"linear":True,"expiry":None,
                "info":{"contractType":"PERPETUAL"},
                "volume": 500
            },
            # 不带冒号，也满足
            "ETH/USDT": {
                "symbol":"ETH/USDT","quote":"USDT","active":True,
                "contract":True,"swap":True,"linear":True,"expiry":None,
                "info":{"contractType":"PERPETUAL"},
                "volume": 300
            },
            # 非 USDT
            "BTC/USDC:USDC": {
                "symbol":"BTC/USDC:USDC","quote":"USDC","active":True,
                "contract":True,"swap":True,"linear":True,"expiry":None,
                "info":{"contractType":"PERPETUAL"},
                "volume": 999
            },
            # 非 PERPETUAL
            "FOO/USDT:USDT": {
                "symbol":"FOO/USDT:USDT","quote":"USDT","active":True,
                "contract":True,"swap":False,"linear":True,"expiry":9999999999,
                "info":{"contractType":"DELIVERY"},
                "volume": 800
            },
        }
        fake = FakeBinanceUSDM(markets=markets)
        client = BinanceFuturesUSDTClient(interval="1h", proxies=None)
        # 用 fake 覆盖真实 ccxt 客户端，避免联网
        client.binance = fake

        syms = client.fetch_usdt_perp_symbols(top_n=10)
        # 只会保留 BTC/USDT:USDT 与 ETH/USDT，且按 volume 降序
        self.assertEqual(syms, ["BTC/USDT:USDT", "ETH/USDT"])

    # ---------- 24h 报价额排序 ----------
    def test_top_by_quote_volume(self):
        tickers = {
            "BTC/USDT:USDT":{"symbol":"BTC/USDT:USDT","quoteVolume":"500000000"},
            "ETH/USDT:USDT":{"symbol":"ETH/USDT:USDT","quoteVolume":"300000000"},
            "FOO/USDT:USDT":{"symbol":"FOO/USDT:USDT","quoteVolume":"100000000"},
            "BAR/USDT:USDT":{"symbol":"BAR/USDT:USDT","quoteVolume":"999999999"},  # 不在 pool，应忽略
        }
        fake = FakeBinanceUSDM(tickers=tickers)
        client = BinanceFuturesUSDTClient(interval="1h", proxies=None)
        client.binance = fake

        pool = ["BTC/USDT:USDT","ETH/USDT:USDT","FOO/USDT:USDT"]
        ranked = client.top_by_quote_volume(pool, topn=2)
        self.assertEqual(ranked, ["BTC/USDT:USDT","ETH/USDT:USDT"])

    # ---------- K 线分页拼接 ----------
    def test_fetch_klines_range_pagination(self):
        # 三页 1h K 线（毫秒时间戳），依次返回
        page1 = [[0, "1","1","1","1","10"]]
        page2 = [[3600000, "2","2","2","2","20"]]
        page3 = [[7200000, "3","3","3","3","30"]]
        fake = FakeBinanceUSDM(ohlcv_pages=[page1, page2, page3])

        client = BinanceFuturesUSDTClient(interval="1h", proxies=None)
        client.binance = fake

        df = client.fetch_klines_range("BTC/USDT:USDT", start_ms=0, end_ms=20_000_000)
        self.assertEqual(len(df), 3)
        self.assertEqual(list(df["close"].astype(float)), [1.0,2.0,3.0])
        self.assertSetEqual(set(df.columns), {"DateTime","open","high","low","close","volume"})

    # ---------- 端到端（轻桩）：保存 CSV ----------
    @patch("bll.data_source_service.BinanceFuturesUSDTClient")
    def test_fetch_top50_and_save_csv(self, MockClient):
        """
        测顶层函数：不联网，走“候选→≥1年→抓取→落盘”。注意：
        你的实现会把文件名中的冒号去掉，仅保留 'BTC/USDT' -> 'BTC_USDT.csv'（已在源码中处理）。
        """

        # fake client：各环节都返回可控数据
        class FakeClientObj:
            def __init__(self, *args, **kwargs): pass

            # 模拟返回50个符号
            def fetch_usdt_perp_symbols(self):
                return [f"SYM{i}/USDT:USDT" for i in range(1, 51)]  # 返回50个合约符号

            def top_by_quote_volume(self, pool, topn=200):
                return pool  # 不改变顺序

            def earliest_kline_time(self, sym):
                return datetime.utcnow() - timedelta(days=400)  # 历史>1年

            def fetch_klines_range(self, sym, start_ms, end_ms):
                idx = pd.date_range(start=datetime(2024, 1, 1, 0, 0, 0), periods=5, freq="1h")
                return pd.DataFrame({
                    "DateTime": idx,
                    "open": [1, 2, 3, 4, 5],
                    "high": [1, 2, 3, 4, 5],
                    "low": [1, 2, 3, 4, 5],
                    "close": [1, 2, 3, 4, 5],
                    "volume": [10, 20, 30, 40, 50],
                })

        MockClient.return_value = FakeClientObj()

        out_dir = "tests/_tmp_data_crypto"
        os.makedirs(out_dir, exist_ok=True)

        saved = fetch_top50_last_year_1h_history_ge_1y(
            pad_missing=False,
            out_dir=out_dir,
            proxies=None,
        )

        # 这里期望返回 50 个文件
        self.assertEqual(len(saved), 50)
        for fp in saved:
            self.assertTrue(fp.endswith(".csv"))
            self.assertTrue(os.path.exists(fp))
            df = pd.read_csv(fp)
            self.assertFalse(df.empty)


if __name__ == "__main__":
    unittest.main(verbosity=2)

