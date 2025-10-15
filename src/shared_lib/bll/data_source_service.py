import os
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from enums import UnderlyingType
from underlying import Underlying
from utility import Utility
import pandas as pd
import ccxt

logger = logging.getLogger(__name__)

MAX_LIMIT = 1500  # 单次 OHLCV 最大条数（ccxt->binance 支持到 1500）
TARGET_ROWS_1Y_1H = 8760  # 1 年 * 24 小时


# -------------------- Binance USDT-M 永续客户端（基于 ccxt） -------------------- #
class BinanceFuturesUSDTClient:
    """
    使用 ccxt 的 binanceusdm 客户端，限定在 USDT-M 永续（contract, linear, expiry=None）市场。
    """

    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None):
        self.interval = interval

        # ✅ 直接使用 USDⓈ-M 期货实例，更稳
        self.binance = ccxt.binanceusdm({
            "enableRateLimit": True,
        })

        if proxies:
            # 设置代理（Clash 的代理端口 7897）
            self.binance.proxies = proxies

        # ✅ 显式加载市场，避免 self.binance.markets 为 None
        self.binance.load_markets(reload=True)

        # 预计算步长（毫秒）
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

    def fetch_usdt_perp_symbols(self, top_n: int = 50) -> List[str]:
        """
        获取所有 USDT 计价的永续合约符号，并根据市值排序选出前 N 名
        """
        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        syms: List[str] = []
        market_data = []  # 用来存储市场符号及其市值（假设市值是通过交易量推算的）

        logger.debug(f"Loaded markets: {markets}")  # 打印加载的市场数据

        for m in markets.values():
            logger.debug(f"Market: {m}")  # 打印每个合约的详细信息

            # 只获取 USDT 计价的合约
            if m.get("quote") != "USDT":
                continue

            # 确保是永续合约，contractType 为 'PERPETUAL'，在 info 字段中
            if m.get("info", {}).get("contractType") != "PERPETUAL":
                continue

            # 排除非活跃的合约
            if m.get("active") is False:
                continue

            sym = m["symbol"]  # 形如 "BTC/USDT" 或 "BTC/USDT:USDT"
            # 假设我们使用市场的 `volume` 或其他字段作为市值的代理
            volume = float(m.get("volume", 0))  # 取交易量作为排序依据

            # 将符号和市值放入列表
            market_data.append((sym, volume))

        # 按市值排序，降序
        market_data.sort(key=lambda x: x[1], reverse=True)

        # 选择前 top_n 个合约
        syms = [sym for sym, _ in market_data[:top_n]]

        # 打印筛选后的永续合约符号
        logger.debug(f"Filtered perpetual symbols: {syms}")

        logger.info(f"USDT-M 永续候选数：{len(syms)}")
        if not syms:
            logger.warning("未获取到 USDT-M 永续合约列表。")

        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        """
        在 pool 中，按 24h 报价量（quoteVolume）降序，返回前 topn。
        若 fetch_tickers 返回为空/字段缺失，会退化为按 pool 的顺序截取。
        """
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

            # 统一字段
            qv = t.get("quoteVolume")
            # 原始 info 兜底
            if qv is None:
                info = t.get("info") or {}
                qv = info.get("quoteVolume")
            # 最后兜底：last * baseVolume
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

    # ---------- OHLCV 处理 ---------- #
    @staticmethod
    def _ohlcv_to_df(raw: List[List]) -> pd.DataFrame:
        """
        ccxt.fetch_ohlcv 返回 [ts, open, high, low, close, volume]（6列）。
        这里统一清洗：只取前 6 列，转成 DataFrame，并输出标准列。
        """
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
        # 转时间（UTC）并去掉时区，统一用“UTC 上的 naive 时间”
        dt_utc = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["DateTime"] = dt_utc.dt.tz_localize(None)

        # 数值化
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

                # 下一页：上一个最后时间 + 一个步长（1h）
                last_ts = int(data[-1][0])
                cur = last_ts + self.step_ms
                if cur > end_ms:
                    break

                # 稍微退避，避免限流
                time.sleep(0.08)
            except Exception as e:
                logger.warning(f"Error fetching data for {symbol}: {e}")
                break

        if frames:
            result_df = pd.concat(frames, ignore_index=True)
            result_df = result_df.drop_duplicates(subset=["DateTime"]).sort_values("DateTime").reset_index(drop=True)
            return result_df
        return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])  # 返回空的 DataFrame



    def earliest_kline_time(self, symbol: str):
        """
        获取该合约最早一根 K 的时间。
        说明：Binance 通常对 since=0, limit=1 会返回最早一根；若返回为空则视为无数据。
        """
        data = self.binance.fetch_ohlcv(symbol, timeframe=self.interval, since=0, limit=1)
        df = self._ohlcv_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

# -------------------- Binance 现货 USDT 客户端（基于 ccxt） -------------------- #
class BinanceSpotUSDTClient:
    """
    使用 ccxt 的 binance 现货客户端，仅筛 USDT 计价的现货交易对（非合约）。
    """
    def __init__(self, interval: str = "1h", proxies: Optional[Dict[str, str]] = None):
        self.interval = interval
        self.binance = ccxt.binance({
            "enableRateLimit": True,
        })
        if proxies:
            self.binance.proxies = proxies

        # 显式加载市场
        self.binance.load_markets(reload=True)
        self.step_ms = int(self.binance.parse_timeframe(self.interval) * 1000)

    def fetch_usdt_spot_symbols(self, top_n: int = 50) -> List[str]:
        """
        获取所有 USDT 计价的“现货”交易对符号，并按交易量粗排选出前 N 名。
        """
        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        market_data: List[Tuple[str, float]] = []
        for m in markets.values():
            # 仅 USDT 计价
            if m.get("quote") != "USDT":
                continue
            # 仅现货（非合约）
            if m.get("spot") is not True:
                continue
            # 排除非活跃
            if m.get("active") is False:
                continue

            sym = m["symbol"]          # 形如 "BTC/USDT"
            volume = float(m.get("volume", 0))
            market_data.append((sym, volume))

        market_data.sort(key=lambda x: x[1], reverse=True)
        syms = [sym for sym, _ in market_data[:top_n]]

        logger.info(f"USDT 现货候选数：{len(syms)}")
        if not syms:
            logger.warning("未获取到 USDT 现货交易对列表。")
        return syms

    def top_by_quote_volume(self, pool: List[str], topn: int = 200) -> List[str]:
        """
        在 pool 里按 24h quoteVolume 排序，返回前 topn。
        """
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
        # 与期货版一致，复用相同数据清洗规则
        return BinanceFuturesUSDTClient._ohlcv_to_df(raw)

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

# -------------------- 工具：时间、补齐 -------------------- #
def ms_to_naive_dt(ms: int) -> datetime:
    # 注意：Timestamp/Series 的“去时区”方式不同，这里是单个值（Timestamp），可直接 tz_localize(None)
    return pd.to_datetime(ms, unit="ms", utc=True).tz_localize(None).to_pydatetime()


def pad_to_hour_grid(df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """
    将 df 对齐到 [start_dt, end_dt] 的整点网格（1H）。
    缺失小时：
      - volume = 0
      - close 前向填充
      - open/high/low = 填充后的 close
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


# -------------------- 顶层：历史 ≥1年 + 24h 成交额 Top-50 -------------------- #
def fetch_top50_last_year_1h_history_ge_1y(pad_missing: bool = False,
                                           out_dir: str = ".",
                                           proxies: Optional[Dict[str, str]] = None) -> List[str]:

    client = BinanceFuturesUSDTClient(interval="1h", proxies=proxies)

    # 候选池：USDT-M 永续
    pool = client.fetch_usdt_perp_symbols()
    logger.info(f"USDT-M 永续候选数：{len(pool)}")
    if not pool:
        logger.warning("未获取到 USDT-M 永续合约列表。")
        return []

    # 先在池内按 24h 成交额排序，多拿一些作为候选（避免严格筛选后不够 50 个）
    ranked = client.top_by_quote_volume(pool, topn=max(250, len(pool)))
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    selected: List[str] = []
    for sym in ranked:
        if len(selected) >= 50:
            break
        try:
            t0 = client.earliest_kline_time(sym)
            if t0 is None:
                continue
            if t0 <= one_year_ago:
                selected.append(sym)
        except Exception as e:
            logger.warning(f"{sym}: earliest time check failed, skip. {e}")
            continue

    if not selected:
        logger.warning("No symbol satisfies 'history ≥ 1 year'.")
        return []

    # 构造“一年整点网格”的时间窗口
    end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(hours=TARGET_ROWS_1Y_1H - 1)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    # 确保输出目录存在
    os.makedirs(out_dir or ".", exist_ok=True)

    saved: List[str] = []
    for sym in selected:
        try:
            # 【移动】把文件名的构造提前到循环一开始
            base_quote = sym.split(':')[0].replace('/', '_')
            fn = os.path.join(out_dir, f"{base_quote}.csv")

            # 【新增】如果文件已存在，就跳过该交易对
            if os.path.exists(fn):
                logger.info(f"{sym}: 目标文件已存在，跳过 -> {fn}")
                # 如需把已存在的文件也计入返回结果，可取消下一行注释
                # saved.append(fn)
                continue
            logger.info(f"Fetching {sym} 1h last 1y ...")
            df = client.fetch_klines_range(sym, start_ms=start_ms, end_ms=end_ms)

            if pad_missing:
                df = pad_to_hour_grid(df, start_dt, end_dt)

            # 最终裁剪为 <= 8760 行（pad 模式下恰好 8760）
            if len(df) > TARGET_ROWS_1Y_1H:
                df = df.iloc[-TARGET_ROWS_1Y_1H:].reset_index(drop=True)

            # base_quote = sym.split(':')[0]
            # base_quote = base_quote.replace('/', '_')    # 将冒号和斜杠替换为下划线
            fn = os.path.join(out_dir, f"{base_quote}.csv")  # 修改文件名格式为 "***_USDT.csv"

            df.to_csv(fn, index=False)
            logger.info(f"{sym}: saved {len(df)} rows -> {fn}")
            saved.append(fn)
        except Exception as e:
            logger.warning(f"{sym}: failed, skip. {e}")
            continue
    return saved

# -------------------- 顶层：历史 ≥1年 + 24h 成交额 Top-50（现货版） -------------------- #
def fetch_top50_last_year_1h_history_ge_1y_spot(pad_missing: bool = False,
                                                out_dir: str = ".",
                                                proxies: Optional[Dict[str, str]] = None) -> List[str]:
    """
    与期货函数同名风格：获取 USDT 现货 Top-50（按 24h 报价量），
    且历史覆盖 ≥ 1 年，导出 1h 近一年数据到 CSV。已存在文件将跳过。
    """
    client = BinanceSpotUSDTClient(interval="1h", proxies=proxies)

    # 候选池：USDT 现货
    pool = client.fetch_usdt_spot_symbols()
    logger.info(f"USDT 现货候选数：{len(pool)}")
    if not pool:
        logger.warning("未获取到 USDT 现货交易对列表。")
        return []

    # 排序并做历史长度筛选
    ranked = client.top_by_quote_volume(pool, topn=max(250, len(pool)))
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    selected: List[str] = []
    for sym in ranked:
        if len(selected) >= 50:
            break
        try:
            t0 = client.earliest_kline_time(sym)
            if t0 is None:
                continue
            if t0 <= one_year_ago:
                selected.append(sym)
        except Exception as e:
            logger.warning(f"[现货] {sym}: earliest time check failed, skip. {e}")
            continue

    if not selected:
        logger.warning("[现货] No symbol satisfies 'history ≥ 1 year'.")
        return []

    # 时间窗口（对齐到整点）
    end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(hours=TARGET_ROWS_1Y_1H - 1)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    os.makedirs(out_dir or ".", exist_ok=True)

    saved: List[str] = []
    for sym in selected:
        try:
            # 文件名：沿用 "BASE_USDT.csv" 形式；与期货区分可自行加前缀，如 spot_*
            base_quote = sym.replace('/', '_')  # 现货无 ":USDT" 后缀
            fn = os.path.join(out_dir, f"{base_quote}.csv")

            if os.path.exists(fn):
                logger.info(f"[现货] {sym}: 目标文件已存在，跳过 -> {fn}")
                # 如需把已存在文件也放回结果，解除下一行注释
                # saved.append(fn)
                continue

            logger.info(f"[现货] Fetching {sym} 1h last 1y ...")
            df = client.fetch_klines_range(sym, start_ms=start_ms, end_ms=end_ms)

            if pad_missing:
                df = pad_to_hour_grid(df, start_dt, end_dt)

            if len(df) > TARGET_ROWS_1Y_1H:
                df = df.iloc[-TARGET_ROWS_1Y_1H:].reset_index(drop=True)

            df.to_csv(fn, index=False)
            logger.info(f"[现货] {sym}: saved {len(df)} rows -> {fn}")
            saved.append(fn)
        except Exception as e:
            logger.warning(f"[现货] {sym}: failed, skip. {e}")
            continue

    return saved


