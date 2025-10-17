import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import pandas as pd
import ccxt

logger = logging.getLogger(__name__)

MAX_LIMIT = 1500  # 单次 OHLCV 最大条数（ccxt->binance 支持到 1500）
TARGET_ROWS_1Y_1H = 8760  # 1 年 * 24 小时


# -------------------- Binance USDT-M 永续客户端（基于 ccxt） -------------------- #
class BinancePerpetualContractUSDTClient:
    """
    使用 ccxt 的 binanceusdm 客户端，限定在 USDT-M 永续（contract, linear, expiry=None）市场。
    """
    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None):
        self.interval = interval
        self.binance = ccxt.binanceusdm({"enableRateLimit": True})
        if proxies:
            self.binance.proxies = proxies
        self.binance.load_markets(reload=True)
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

    def fetch_usdt_perp_symbols(self, top_n: int = 50) -> List[str]:
        """获取所有 USDT 计价的永续合约符号，并按成交量粗排选出前 N 名。"""
        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        market_data: List[Tuple[str, float]] = []
        for m in markets.values():
            if m.get("quote") != "USDT":
                continue
            if m.get("info", {}).get("contractType") != "PERPETUAL":
                continue
            if m.get("active") is False:
                continue
            sym = m["symbol"]  # "BTC/USDT:USDT" 等
            vol = float(m.get("volume", 0))
            market_data.append((sym, vol))

        market_data.sort(key=lambda x: x[1], reverse=True)
        syms = [sym for sym, _ in market_data[:top_n]]
        logger.info(f"USDT-M 永续候选数：{len(syms)}")
        if not syms:
            logger.warning("未获取到 USDT-M 永续合约列表。")
        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        """在 pool 中按 24h 报价量 quoteVolume 排序后返回前 topn。"""
        pool_set = set(pool)
        rows: List[Tuple[str, float]] = []
        try:
            tickers = self.binance.fetch_tickers()
        except Exception as e:
            logger.warning(f"fetch_tickers 失败，降级使用 pool 顺序。原因：{e}")
            return pool[:topn]

        for sym, t in tickers.items():
            if sym not in pool_set:
                continue
            qv = t.get("quoteVolume")
            if qv is None:
                info = t.get("info") or {}
                qv = info.get("quoteVolume")
            if qv is None:
                last = t.get("last") or 0
                base_vol = t.get("baseVolume") or 0
                try:
                    qv = float(last) * float(base_vol)
                except Exception:
                    qv = 0.0
            try:
                qv_float = float(qv or 0.0)
            except Exception:
                qv_float = 0.0
            rows.append((sym, qv_float))

        if not rows:
            logger.warning("tickers 中无匹配到的 USDT-M 永续，降级使用 pool 顺序。")
            return pool[:topn]

        rows.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in rows[:topn]]

    @staticmethod
    def _ohlcv_to_df(raw: List[List]) -> pd.DataFrame:
        """将 [ts, open, high, low, close, volume] 转为标准 DataFrame。"""
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

    def fetch_klines_range(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cur = start_ms
        while True:
            try:
                data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=cur, limit=MAX_LIMIT)
                if not data:
                    break
                df = self._ohlcv_to_df(data)
                frames.append(df)
                last_ts = int(data[-1][0])
                cur = last_ts + self.step_ms
                if cur > end_ms:
                    break
                time.sleep(0.08)
            except Exception as e:
                logger.warning(f"Error fetching data for {symbol}: {e}")
                break

        if frames:
            result_df = pd.concat(frames, ignore_index=True)
            result_df = result_df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime").reset_index(drop=True)
            return result_df
        return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

    def earliest_kline_time(self, symbol: str):
        data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=0, limit=1)
        df = self._ohlcv_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

    def fetch_top50_last_year_1h_history_ge_1y(self, pad_missing: bool = False, out_dir: str = ".") -> List[str]:
        """
        在 USDT-M 永续里，按24h报价额选 Top-50，且历史覆盖>=1年，
        拉取【近一年】1h数据到 CSV（已存在文件跳过）。
        """
        pool = self.fetch_usdt_perp_symbols()
        logger.info(f"[FUTURES] USDT-M 永续候选数：{len(pool)}")
        if not pool:
            logger.warning("[FUTURES] 未获取到合约列表。")
            return []

        ranked = self.top_by_quote_volume(pool, topn=max(250, len(pool)))
        one_year_ago = datetime.utcnow() - timedelta(days=365)

        selected: List[str] = []
        for sym in ranked:
            if len(selected) >= 50:
                break
            try:
                t0 = self.earliest_kline_time(sym)
                if t0 and t0 <= one_year_ago:
                    selected.append(sym)
            except Exception as e:
                logger.warning(f"[FUTURES]{sym}: earliest time check failed, skip. {e}")

        if not selected:
            logger.warning("[FUTURES] 没有交易对满足“历史 ≥ 1 年”。")
            return []

        end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=TARGET_ROWS_1Y_1H - 1)
        end_ms = int(end_dt.timestamp() * 1000)
        start_ms = int(start_dt.timestamp() * 1000)

        os.makedirs(out_dir or ".", exist_ok=True)

        saved: List[str] = []
        for sym in selected:
            try:
                base_quote = sym.split(':')[0].replace('/', '_')
                fn = os.path.join(out_dir, f"{base_quote}.csv")

                if os.path.exists(fn):
                    logger.info(f"[FUTURES]{sym}: 文件已存在，跳过 -> {fn}")
                    continue

                df = self.fetch_klines_range(sym, start_ms=start_ms, end_ms=end_ms)

                if pad_missing:
                    df = pad_to_hour_grid(df, start_dt, end_dt)

                if len(df) > TARGET_ROWS_1Y_1H:
                    df = df.iloc[-TARGET_ROWS_1Y_1H:].reset_index(drop=True)

                df.to_csv(fn, index=False)
                logger.info(f"[FUTURES]{sym}: saved {len(df)} rows -> {fn}")
                saved.append(fn)
            except Exception as e:
                logger.warning(f"[FUTURES]{sym}: failed, skip. {e}")

        return saved


# -------------------- Binance 现货 USDT 客户端（基于 ccxt） -------------------- #
class BinanceSpotUSDTClient:
    """使用 ccxt 的 binance 现货客户端，仅筛 USDT 计价的现货交易对（非合约）。"""
    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None):
        self.interval = interval
        self.binance = ccxt.binance({"enableRateLimit": True})
        if proxies:
            self.binance.proxies = proxies
        self.binance.load_markets(reload=True)
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

    def fetch_usdt_spot_symbols(self, top_n: int = 50) -> List[str]:
        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        market_data: List[Tuple[str, float]] = []
        for m in markets.values():
            if m.get("quote") != "USDT":
                continue
            if m.get("spot") is not True:
                continue
            if m.get("active") is False:
                continue
            sym = m["symbol"]  # "BTC/USDT"
            vol = float(m.get("volume", 0))
            market_data.append((sym, vol))

        market_data.sort(key=lambda x: x[1], reverse=True)
        syms = [sym for sym, _ in market_data[:top_n]]
        logger.info(f"USDT 现货候选数：{len(syms)}")
        if not syms:
            logger.warning("未获取到 USDT 现货交易对列表。")
        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        pool_set = set(pool)
        rows: List[Tuple[str, float]] = []
        try:
            tickers = self.binance.fetch_tickers()
        except Exception as e:
            logger.warning(f"fetch_tickers 失败（现货），降级用 pool 顺序：{e}")
            return pool[:topn]

        for sym, t in tickers.items():
            if sym not in pool_set:
                continue
            qv = t.get("quoteVolume")
            if qv is None:
                info = t.get("info") or {}
                qv = info.get("quoteVolume")
            if qv is None:
                last = t.get("last") or 0
                base_vol = t.get("baseVolume") or 0
                try:
                    qv = float(last) * float(base_vol)
                except Exception:
                    qv = 0.0
            try:
                qv_float = float(qv or 0.0)
            except Exception:
                qv_float = 0.0
            rows.append((sym, qv_float))

        if not rows:
            logger.warning("tickers 中无匹配到的现货，降级使用 pool 顺序。")
            return pool[:topn]

        rows.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in rows[:topn]]

    @staticmethod
    def _ohlcv_to_df(raw: List[List]) -> pd.DataFrame:
        return BinancePerpetualContractUSDTClient._ohlcv_to_df(raw)

    def fetch_klines_range(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cur = start_ms
        while True:
            try:
                data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=cur, limit=MAX_LIMIT)
                if not data:
                    break
                df = self._ohlcv_to_df(data)
                frames.append(df)
                last_ts = int(data[-1][0])
                cur = last_ts + self.step_ms
                if cur > end_ms:
                    break
                time.sleep(0.08)
            except Exception as e:
                logger.warning(f"[现货] 拉取 {symbol} 出错：{e}")
                break

        if frames:
            result_df = pd.concat(frames, ignore_index=True)
            result_df = result_df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime").reset_index(drop=True)
            return result_df
        return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

    def earliest_kline_time(self, symbol: str):
        data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=0, limit=1)
        df = self._ohlcv_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

    def fetch_top50_last_year_1h_history_ge_1y_spot(self, pad_missing: bool = False, out_dir: str = ".") -> List[str]:
        """
        在 USDT 现货里，按24h报价额选 Top-50，且历史覆盖>=1年，
        拉取【近一年】1h数据到 CSV（已存在文件跳过）。
        """
        try:
            pool = self.fetch_usdt_spot_symbols()
        except Exception as e:
            logger.warning(f"[SPOT] 获取 USDT 现货列表失败：{e}")
            pool = []

        logger.info(f"[SPOT] USDT 现货候选数：{len(pool)}")
        if not pool:
            return []

        ranked = self.top_by_quote_volume(pool, topn=max(250, len(pool)))
        one_year_ago = datetime.utcnow() - timedelta(days=365)

        selected: List[str] = []
        for sym in ranked:
            if len(selected) >= 50:
                break
            try:
                t0 = self.earliest_kline_time(sym)
                if t0 and t0 <= one_year_ago:
                    selected.append(sym)
            except Exception as e:
                logger.warning(f"[SPOT]{sym}: earliest time check failed, skip. {e}")

        if not selected:
            logger.warning("[SPOT] 没有交易对满足“历史 ≥ 1 年”。")
            return []

        end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=TARGET_ROWS_1Y_1H - 1)
        end_ms = int(end_dt.timestamp() * 1000)
        start_ms = int(start_dt.timestamp() * 1000)

        os.makedirs(out_dir or ".", exist_ok=True)

        saved: List[str] = []
        for sym in selected:
            try:
                base_quote = sym.replace('/', '_')
                fn = os.path.join(out_dir, f"{base_quote}.csv")

                if os.path.exists(fn):
                    logger.info(f"[SPOT]{sym}: 文件已存在，跳过 -> {fn}")
                    continue

                df = self.fetch_klines_range(sym, start_ms=start_ms, end_ms=end_ms)

                if pad_missing:
                    df = pad_to_hour_grid(df, start_dt, end_dt)

                if len(df) > TARGET_ROWS_1Y_1H:
                    df = df.iloc[-TARGET_ROWS_1Y_1H:].reset_index(drop=True)

                df.to_csv(fn, index=False)
                logger.info(f"[SPOT]{sym}: saved {len(df)} rows -> {fn}")
                saved.append(fn)
            except Exception as e:
                logger.warning(f"[SPOT]{sym}: failed, skip. {e}")

        return saved


# -------------------- 工具：时间、补齐 -------------------- #
def ms_to_naive_dt(ms: int) -> datetime:
    return pd.to_datetime(ms, unit="ms", utc=True).tz_localize(None).to_pydatetime()


def pad_to_hour_grid(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """
    将 df 对齐到 [start_dt, end_dt] 的整点网格（1H）。
    缺失小时：volume = 0；close 前向填充；open/high/low = 填充后的 close
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
