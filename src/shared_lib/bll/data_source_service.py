
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import pandas as pd
import ccxt
import requests  # For CoinMarketCap API
import bll.utility as utility
print(dir(utility))


# -------------------------------------------------------------
# Binance Perpetual USDT-M (Futures)
# -------------------------------------------------------------
class BinancePerpetualContractUSDTClient:
    """ccxt binanceusdm client limited to USDT-M perpetual markets."""
    print("DEFAULT_CMC_CONVERT value:", utility.Utility.DEFAULT_CMC_CONVERT)
    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None,
                 cmc_api_key: Optional[str] = None, cmc_convert: str = utility.Utility.DEFAULT_CMC_CONVERT):
        valid = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"]
        if interval not in valid:
            raise ValueError(f"无效的时间间隔: '{interval}', 必须是有效值之一：{', '.join(valid)}")

        if proxies is not None:
            if not isinstance(proxies, dict):
                raise ValueError("代理配置必须是字典类型")
            for key in proxies.keys():
                if key not in ["http", "https"]:
                    raise ValueError(f"无效代理协议: '{key}'，必须 'http' 或 'https'")

        self.interval = interval
        self.binance = ccxt.binanceusdm({"enableRateLimit": True})
        if proxies is not None:
            self.binance.proxies = proxies

        self.binance.load_markets(reload=True)
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

        # CMC credentials
        self.cmc_api_key = cmc_api_key
        self.cmc_convert = cmc_convert or utility.Utility.DEFAULT_CMC_CONVERT

    def fetch_usdt_perp_symbols(self, top_n: int = 50) -> List[str]:
        """Return USDT-M perpetual symbols ranked by CMC market cap; backfill with volume to ensure up-to-50."""
        if not isinstance(top_n, int) or top_n <= 0:
            raise ValueError("交易对数量必须是正整数")

        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        cmc_caps = utility.Utility._get_cmc_market_caps()
        if cmc_caps:
            rows: List[Tuple[str, float]] = []
            unmatched = set()
            total_scanned = 0

            for m in markets.values():
                if m.get("quote") != "USDT":
                    continue
                if m.get("info", {}).get("contractType") != "PERPETUAL":
                    continue
                if m.get("active") is False:
                    continue
                base = utility.Utility._normalize_base_for_cmc(m.get("base"))
                total_scanned += 1
                cap = cmc_caps.get(base)
                if cap:
                    rows.append((m["symbol"], cap))
                else:
                    unmatched.add(base)

            if rows:
                if unmatched:
                    utility.Utility.logger.info(f"[FUTURES] CMC未匹配的base约 {len(unmatched)} / 扫描 {total_scanned}")
                rows.sort(key=lambda x: x[1], reverse=True)
                syms = [sym for sym, _ in rows[:top_n]]

                # Backfill with volume if needed
                if len(syms) < top_n:
                    market_data: List[Tuple[str, float]] = []
                    for m in markets.values():
                        if m.get("quote") != "USDT":
                            continue
                        if m.get("info", {}).get("contractType") != "PERPETUAL":
                            continue
                        if m.get("active") is False:
                            continue
                        sym = m["symbol"]
                        try:
                            vol = float(m.get("volume", 0))
                        except (TypeError, ValueError):
                            vol = 0.0
                        market_data.append((sym, vol))
                    market_data.sort(key=lambda x: x[1], reverse=True)
                    for sym, _ in market_data:
                        if sym not in syms:
                            syms.append(sym)
                        if len(syms) >= top_n:
                            break

                utility.Utility.logger.info(f"USDT-M 永续候选数（按市值+补齐）：{len(syms)}/{top_n}")
                return syms

        # Fallback: Volume-only ranking
        market_data: List[Tuple[str, float]] = []
        for m in markets.values():
            if m.get("quote") != "USDT":
                continue
            if m.get("info", {}).get("contractType") != "PERPETUAL":
                continue
            if m.get("active") is False:
                continue
            sym = m["symbol"]
            try:
                vol = float(m.get("volume", 0))
            except (TypeError, ValueError):
                vol = 0.0
            market_data.append((sym, vol))
        market_data.sort(key=lambda x: x[1], reverse=True)
        syms = [sym for sym, _ in market_data[:top_n]]
        utility.Utility.logger.info(f"USDT-M 永续候选数（按成交量回退）：{len(syms)}/{len(market_data)}")
        if not syms:
            utility.Utility.logger.warning("未获取到有效的 USDT-M 永续合约列表")
        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        """Kept for backward-compat; not used in market-cap top-50 path."""
        if not isinstance(pool, list) or not pool:
            raise ValueError("交易对池必须是非空列表")
        if not isinstance(topn, int) or topn <= 0:
            raise ValueError("排序数量必须是正整数")
        pool_set = set(pool)
        rows: List[Tuple[str, float]] = []
        try:
            tickers = self.binance.fetch_tickers()
        except Exception as e:
            utility.Utility.logger.warning(f"fetch_tickers 失败（合约），降级用 pool 顺序：{e}")
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
            utility.Utility.logger.warning("tickers 中无匹配到的永续，降级使用 pool 顺序。")
            return pool[:topn]

        rows.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in rows[:topn]]

    def fetch_ohlcv_range(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cur = start_ms
        while True:
            try:
                data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=cur, limit=utility.Utility.MAX_LIMIT)
                if not data:
                    break
                df = utility.Utility._ohlcv_to_df(data)
                frames.append(df)
                last_ts = int(data[-1][0])
                cur = last_ts + self.step_ms
                if cur > end_ms:
                    break
                time.sleep(0.08)
            except Exception as e:
                utility.Utility.logger.warning(f"[FUTURES] 拉取 {symbol} 出错：{e}")
                break

        if frames:
            result_df = pd.concat(frames, ignore_index=True)
            result_df = result_df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime").reset_index(drop=True)
            return result_df
        return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

    def earliest_kline_time(self, symbol: str):
        data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=0, limit=1)
        df = utility.Utility._ohlcv_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

    def fetch_top50_last_year_1h_history_ge_1y(self, pad_missing: bool = False, out_dir: str = ".") -> List[str]:
        """By CMC market-cap pool, require >=1y if possible; fill to 50 with remaining top-cap if not enough."""
        pool = self.fetch_usdt_perp_symbols()  # already market-cap ranked with backfill
        utility.Utility.logger.info(f"[FUTURES] USDT-M 永续候选数（CMC池）：{len(pool)}")
        if not pool:
            return []

        one_year_ago = datetime.utcnow() - timedelta(days=365)
        selected: List[str] = []
        for sym in pool:
            if len(selected) >= 50:
                break
            try:
                t0 = self.earliest_kline_time(sym)
                if t0 and t0 <= one_year_ago:
                    selected.append(sym)
            except Exception as e:
                utility.Utility.logger.warning(f"[FUTURES]{sym}: earliest time check failed, skip. {e}")

        if len(selected) < 50:
            utility.Utility.logger.warning(f"[FUTURES] 满足‘历史 ≥ 1 年’的仅 {len(selected)} 个，将用其余市值Top补齐到50（允许 <1年）。")
            for sym in pool:
                if len(selected) >= 50:
                    break
                if sym not in selected:
                    selected.append(sym)

        end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=utility.Utility.TARGET_ROWS_1Y_1H - 1)
        end_ms = int(end_dt.timestamp() * 1000)
        start_ms = int(start_dt.timestamp() * 1000)

        os.makedirs(out_dir or ".", exist_ok=True)
        saved: List[str] = []
        for sym in selected:
            try:
                base_quote = sym.split(':')[0].replace('/', '_')
                fn = os.path.join(out_dir, f"{base_quote}.csv")

                if os.path.exists(fn):
                    utility.Utility.logger.info(f"[FUTURES]{sym}: 文件已存在，跳过 -> {fn}")
                    continue

                df = self.fetch_ohlcv_range(sym, start_ms=start_ms, end_ms=end_ms)
                if pad_missing:
                    df = utility.Utility.pad_to_hour_grid(df, start_dt, end_dt)

                if len(df) > utility.Utility.TARGET_ROWS_1Y_1H:
                    df = df.iloc[-utility.Utility.TARGET_ROWS_1Y_1H:].reset_index(drop=True)

                df.to_csv(fn, index=False)
                utility.Utility.logger.info(f"[FUTURES]{sym}: saved {len(df)} rows -> {fn}")
                saved.append(fn)
            except Exception as e:
                utility.Utility.logger.warning(f"[FUTURES]{sym}: failed, skip. {e}")

        return saved


# -------------------------------------------------------------
# Binance Spot USDT
# -------------------------------------------------------------
class BinanceSpotUSDTClient:
    """ccxt binance client for USDT spot markets with CMC market-cap ranking."""

    BINANCE_INTERVALS = ["1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d","3d","1w","1M"]

    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None,
                 cmc_api_key: Optional[str] = None, cmc_convert: str = utility.Utility.DEFAULT_CMC_CONVERT):
        if interval not in self.BINANCE_INTERVALS:
            valid = ", ".join(self.BINANCE_INTERVALS)
            raise ValueError(f"无效的时间间隔. 有效值: {valid}")

        self.interval = interval
        self.binance = ccxt.binance({"enableRateLimit": True})
        if proxies:
            if not isinstance(proxies, dict) or not all(k in ['http', 'https'] for k in proxies.keys()):
                raise ValueError("无效的代理配置. 必须是包含'http'和/或'https'的字典")
            self.binance.proxies = proxies

        self.binance.load_markets(reload=True)
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

        # CMC credentials
        self.cmc_api_key = cmc_api_key or os.getenv("COINMARKETCAP_API_KEY") or os.getenv("CMC_API_KEY")
        self.cmc_convert = cmc_convert or utility.Utility.DEFAULT_CMC_CONVERT

    def fetch_usdt_spot_symbols(self, top_n: int = 50) -> List[str]:
        """Return USDT spot symbols ranked by CMC market cap; backfill with volume to ensure up-to-50."""
        if not isinstance(top_n, int) or top_n <= 0:
            raise ValueError("交易对数量必须是正整数")

        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        cmc_caps = utility.Utility._get_cmc_market_caps()
        if cmc_caps:
            rows: List[Tuple[str, float]] = []
            unmatched = set()
            total_scanned = 0

            for m in markets.values():
                if m.get("quote") != "USDT":
                    continue
                if not m.get("spot", False):
                    continue
                if m.get("active") is False:
                    continue
                base = utility.Utility._normalize_base_for_cmc(m.get("base"))
                total_scanned += 1
                cap = cmc_caps.get(base)
                if cap:
                    rows.append((m["symbol"], cap))
                else:
                    unmatched.add(base)

            if rows:
                if unmatched:
                    utility.Utility.logger.info(f"[SPOT] CMC未匹配的base约 {len(unmatched)} / 扫描 {total_scanned}")
                rows.sort(key=lambda x: x[1], reverse=True)
                syms = [sym for sym, _ in rows[:top_n]]

                # Backfill with volume if needed
                if len(syms) < top_n:
                    market_data: List[Tuple[str, float]] = []
                    for m in markets.values():
                        if m.get("quote") != "USDT":
                            continue
                        if not m.get("spot", False):
                            continue
                        if m.get("active") is False:
                            continue
                        sym = m["symbol"]
                        try:
                            vol = float(m.get("volume", 0))
                        except (TypeError, ValueError):
                            vol = 0.0
                        market_data.append((sym, vol))
                    market_data.sort(key=lambda x: x[1], reverse=True)
                    for sym, _ in market_data:
                        if sym not in syms:
                            syms.append(sym)
                        if len(syms) >= top_n:
                            break

                utility.Utility.logger.info(f"USDT 现货候选数（按市值+补齐）：{len(syms)}/{top_n}")
                return syms

        # Fallback: Volume-only ranking
        market_data: List[Tuple[str, float]] = []
        for m in markets.values():
            if m.get("quote") != "USDT":
                continue
            if not m.get("spot", False):
                continue
            if m.get("active") is False:
                continue
            sym = m["symbol"]
            try:
                vol = float(m.get("volume", 0))
            except (TypeError, ValueError):
                vol = 0.0
            market_data.append((sym, vol))

        market_data.sort(key=lambda x: x[1], reverse=True)
        syms = [sym for sym, _ in market_data[:top_n]]
        utility.Utility.logger.info(f"USDT 现货候选数（按成交量回退）：{len(syms)}/{len(market_data)}")
        if not syms:
            utility.Utility.logger.warning("未获取到有效的 USDT 现货交易对列表")
        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        """Kept for backward-compat; not used in market-cap top-50 path."""
        if not isinstance(pool, list) or not pool:
            raise ValueError("交易对池必须是非空列表")
        if not isinstance(topn, int) or topn <= 0:
            raise ValueError("排序数量必须是正整数")

        pool_set = set(pool)
        rows: List[Tuple[str, float]] = []
        try:
            tickers = self.binance.fetch_tickers()
        except Exception as e:
            utility.Utility.logger.warning(f"fetch_tickers 失败（现货），降级用 pool 顺序：{e}")
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
            utility.Utility.logger.warning("tickers 中无匹配到的现货，降级使用 pool 顺序。")
            return pool[:topn]

        rows.sort(key=lambda x: x[1], reverse=True)
        return [sym for sym, _ in rows[:topn]]

    def fetch_ohlcv_range(self, symbol: str, start_ms: int, end_ms: int) -> pd.DataFrame:
        frames: List[pd.DataFrame] = []
        cur = start_ms
        while True:
            try:
                data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=cur, limit=utility.Utility.MAX_LIMIT)
                if not data:
                    break
                df = utility.Utility._ohlcv_to_df(data)
                frames.append(df)
                last_ts = int(data[-1][0])
                cur = last_ts + self.step_ms
                if cur > end_ms:
                    break
                time.sleep(0.08)
            except Exception as e:
                utility.Utility.logger.warning(f"[SPOT] 拉取 {symbol} 出错：{e}")
                break

        if frames:
            result_df = pd.concat(frames, ignore_index=True)
            result_df = result_df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime").reset_index(drop=True)
            return result_df
        return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

    def earliest_kline_time(self, symbol: str):
        data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=0, limit=1)
        df = utility.Utility._ohlcv_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

    def fetch_top50_last_year_1h_history_ge_1y_spot(self, pad_missing: bool = False, out_dir: str = ".") -> List[str]:
        """By CMC market-cap pool, require >=1y if possible; fill to 50 with remaining top-cap if not enough."""
        pool = self.fetch_usdt_spot_symbols()  # already market-cap ranked with backfill
        utility.Utility.logger.info(f"[SPOT] USDT 现货候选数（CMC池）：{len(pool)}")
        if not pool:
            return []

        one_year_ago = datetime.utcnow() - timedelta(days=365)
        selected: List[str] = []
        for sym in pool:
            if len(selected) >= 50:
                break
            try:
                t0 = self.earliest_kline_time(sym)
                if t0 and t0 <= one_year_ago:
                    selected.append(sym)
            except Exception as e:
                utility.Utility.logger.warning(f"[SPOT]{sym}: earliest time check failed, skip. {e}")

        if len(selected) < 50:
            utility.Utility.logger.warning(f"[SPOT] 满足‘历史 ≥ 1 年’的仅 {len(selected)} 个，将用其余市值Top补齐到50（允许 <1年）。")
            for sym in pool:
                if len(selected) >= 50:
                    break
                if sym not in selected:
                    selected.append(sym)

        end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start_dt = end_dt - timedelta(hours=utility.Utility.TARGET_ROWS_1Y_1H - 1)
        end_ms = int(end_dt.timestamp() * 1000)
        start_ms = int(start_dt.timestamp() * 1000)

        os.makedirs(out_dir or ".", exist_ok=True)
        saved: List[str] = []
        for sym in selected:
            try:
                base_quote = sym.replace('/', '_')
                fn = os.path.join(out_dir, f"{base_quote}.csv")

                if os.path.exists(fn):
                    utility.Utility.logger.info(f"[SPOT]{sym}: 文件已存在，跳过 -> {fn}")
                    continue

                df = self.fetch_ohlcv_range(sym, start_ms=start_ms, end_ms=end_ms)
                if pad_missing:
                    df = utility.Utility.pad_to_hour_grid(df, start_dt, end_dt)

                if len(df) > utility.Utility.TARGET_ROWS_1Y_1H:
                    df = df.iloc[-utility.Utility.TARGET_ROWS_1Y_1H:].reset_index(drop=True)

                df.to_csv(fn, index=False)
                utility.Utility.logger.info(f"[SPOT]{sym}: saved {len(df)} rows -> {fn}")
                saved.append(fn)
            except Exception as e:
                utility.Utility.logger.warning(f"[SPOT]{sym}: failed, skip. {e}")

        return saved
