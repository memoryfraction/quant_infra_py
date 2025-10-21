import logging
import pandas as pd
import ccxt
import requests  # For CoinMarketCap API
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import read_env


class Utility:
    MAX_LIMIT = 1500  # Single fetch_ohlcv max rows supported by Binance via ccxt
    TARGET_ROWS_1Y_1H = 8760  # 365d * 24h
    DEFAULT_CMC_CONVERT = "USD"
    logger = logging.getLogger(__name__)
    def utility_test(self):
        print("这是一个Utility类的测试方法 123")
    # -------------------------------------------------------------
    # CoinMarketCap helpers
    # -------------------------------------------------------------
    @staticmethod
    def _get_cmc_market_caps() -> Dict[
        str, float]:
        """
        Call CMC listings API and return {symbol -> market_cap} map (sorted by market cap desc).
        Returns empty dict on any failure.
        """
        key = read_env.read_and_print_config(env_file_name="\\backtest\\.env")
        if not key:
            return {}
        url = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"
        headers = {"Accepts": "application/json", "X-CMC_PRO_API_KEY": key}
        params = {"limit": 1000, "convert": "USD", "sort": "market_cap", "sort_dir": "desc"}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            caps: Dict[str, float] = {}
            for item in data:
                sym = str(item.get("symbol", "")).upper()
                cap = (item.get("quote") or {}).get("USD", {}).get("market_cap")
                if sym and isinstance(cap, (int, float)):
                    caps[sym] = float(cap)
            return caps
        except Exception as e:
            Utility.logger.warning(f"CoinMarketCap 调用失败，降级到成交量排序。原因: {e}")
            return {}

    @staticmethod
    def _normalize_base_for_cmc(base: str) -> str:
        """
        规范 Binance base 符号以匹配 CMC symbol。
        - 精确映射：处理常见 '1000' 前缀与分叉别名
        - 注意不要破坏 '1INCH' 这类本身就是以数字开头的标准符号
        """
        base_u = (base or "").upper()
        mapping = {
            # Binance 以 1000 倍面额上市的一些代币
            "1000PEPE": "PEPE",
            "1000SHIB": "SHIB",
            "1000BONK": "BONK",
            "1000XEC": "XEC",
            # 别名/锚定资产
            "BTCB": "BTC",
        }
        return mapping.get(base_u, base_u)

    # -------------------------------------------------------------
    # Common utilities
    # -------------------------------------------------------------
    @staticmethod
    def ms_to_naive_dt(ms: int) -> datetime:
        if not isinstance(ms, (int, float)):
            raise ValueError("时间戳必须是数值类型 | Timestamp must be numeric type")
        if ms < 0:
            raise ValueError("时间戳不能为负数 | Timestamp cannot be negative")
        return pd.to_datetime(ms, unit="ms", utc=True).tz_localize(None).to_pydatetime()


    @staticmethod
    def pad_to_hour_grid(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
        """
        Align df to an hourly grid [start_dt, end_dt].
        Missing hours: volume=0; close ffill; open/high/low = filled close.
        """
        idx = pd.date_range(start=start_dt, end=end_dt, freq="1H")
        if df.empty:
            out = pd.DataFrame({"DateTime": idx})
            out["close"] = None
            out["open"] = out["high"] = out["low"] = None
            out["volume"] = 0.0
            return out

        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")

        gdf = df.set_index("DateTime").reindex(idx)
        gdf["close"] = gdf["close"].ffill()
        gdf["open"] = gdf["open"].fillna(gdf["close"])
        gdf["high"] = gdf["high"].fillna(gdf["close"])
        gdf["low"] = gdf["low"].fillna(gdf["close"])
        gdf["volume"] = gdf["volume"].fillna(0.0)
        gdf = gdf.reset_index().rename(columns={"index": "DateTime"})
        return gdf

    @staticmethod
    def _ohlcv_to_df(raw: List[List]) -> pd.DataFrame:
        """Convert [ts, open, high, low, close, volume] to DataFrame."""
        if not isinstance(raw, list) or not raw:
            return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])
        cleaned: List[List] = []
        for row in raw:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            cleaned.append(row[:6])
        if not cleaned:
            return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(cleaned, columns=["timestamp", "open", "high", "low", "close", "volume"])
        dt_utc = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["DateTime"] = dt_utc.dt.tz_localize(None)
        for c in ["open", "high", "low", "close", "volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df[["DateTime", "open", "high", "low", "close", "volume"]]