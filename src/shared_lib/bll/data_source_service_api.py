import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# Binance USDT-M 期货备用域名
FAPI_BASES = [
    "https://fapi.binance.com",
    "https://fapi1.binance.com",
    "https://fapi2.binance.com",
    "https://fapi3.binance.com",
]

MAX_LIMIT = 1500            # /fapi/v1/klines 单次最大条数
TARGET_ROWS_1Y_1H = 8760    # 1年*24小时

class BinanceFuturesUSDTClient:
    def __init__(self, interval="1h", timeout=10, proxies=None):
        self.interval = interval
        self.timeout = timeout
        self.base_index = 0

        self.sess = requests.Session()
        retries = Retry(
            total=5, connect=5, read=5,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self.sess.headers.update({"User-Agent": "Mozilla/5.0 (data-fetcher/1.2)"})
        self.sess.mount("https://", HTTPAdapter(max_retries=retries))
        if proxies:
            self.sess.proxies.update(proxies)

    @property
    def base(self):
        return FAPI_BASES[self.base_index % len(FAPI_BASES)]

    def _get_json(self, path, params=None):
        for _ in range(len(FAPI_BASES)):
            url = f"{self.base}{path}"
            try:
                r = self.sess.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except requests.exceptions.SSLError as e:
                logger.warning(f"SSL error on {url}, switch endpoint: {e}")
                self.base_index += 1; time.sleep(0.3)
            except requests.RequestException as e:
                logger.warning(f"HTTP error on {url}, switch endpoint: {e}")
                self.base_index += 1; time.sleep(0.3)
        raise RuntimeError(f"All endpoints failed for {path} with {params}")

    def fetch_usdt_perp_symbols(self) -> List[str]:
        """
        获取所有 USDT 计价的永续合约符号
        """
        markets = getattr(self.binance, "markets", None)
        if not markets:
            self.binance.load_markets(reload=True)
            markets = self.binance.markets or {}

        syms: List[str] = []
        logger.debug(f"Loaded markets: {markets}")  # 打印加载的市场数据

        for m in markets.values():
            logger.debug(f"Market: {m}")  # 打印每个合约的详细信息

            # 放宽筛选条件：不再强制要求是线性合约
            if m.get("quote") != "USDT":
                continue
            if m.get("contractType") == "PERPETUAL" and m.get("status") == "TRADING":
                syms.append(m["symbol"])

        logger.info(f"USDT-M 永续候选数：{len(syms)}")
        if not syms:
            logger.warning("未获取到 USDT-M 永续合约列表。")
        return syms

    def top_by_quote_volume(self, pool, topn=200):
        """在给定符号池 pool 中，按 24h quoteVolume 降序取前 topn"""
        stats = self._get_json("/fapi/v1/ticker/24hr")
        pool_set = set(pool)
        rows = [d for d in stats if d.get("symbol") in pool_set]
        rows.sort(key=lambda x: float(x.get("quoteVolume", "0") or 0.0), reverse=True)
        return [r["symbol"] for r in rows[:topn]]

    # K线
    @staticmethod
    def _klines_to_df(raw):
        cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_asset_volume', 'number_of_trades',
                'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore']
        if not isinstance(raw, list) or not raw:
            return pd.DataFrame(columns=["DateTime", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(raw, columns=cols)

        # 对 Series 用 .dt 访问器来去时区
        dt_utc = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["DateTime"] = dt_utc.dt.tz_localize(None)

        # 可选：把数值列转为浮点，避免后续 pad/reindex 出现类型问题
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

    def earliest_kline_time(self, symbol):
        """拿到该合约最早一根 K 的时间（用于判断是否≥1年历史）"""
        data = self._get_json("/fapi/v1/klines", params={
            "symbol": symbol, "interval": self.interval, "limit": 1, "startTime": 0
        })
        df = self._klines_to_df(data)
        if df.empty:
            return None
        return df["DateTime"].iloc[0]

# ---------- 辅助：时间网格补齐（可选） ----------
def pad_to_hour_grid(df, start_dt, end_dt):
    """
    对齐到整点网格 [start_dt, end_dt]，频率 1H。
    缺失小时：volume=0；close前向填充；open/high/low=填充后close
    """
    idx = pd.date_range(start=start_dt, end=end_dt, freq="1H")
    if df.empty:
        base = pd.DataFrame({"DateTime": idx})
        base["close"] = None
        base["open"] = base["high"] = base["low"] = None
        base["volume"] = 0.0
        return base

    for c in ["open","high","low","close","volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    gdf = df.set_index("DateTime").reindex(idx)
    gdf["close"] = gdf["close"].ffill()
    gdf["open"]  = gdf["open"].fillna(gdf["close"])
    gdf["high"]  = gdf["high"].fillna(gdf["close"])
    gdf["low"]   = gdf["low"].fillna(gdf["close"])
    gdf["volume"]= gdf["volume"].fillna(0.0)
    gdf = gdf.reset_index().rename(columns={"index":"DateTime"})
    return gdf

# ---------- 选择“历史≥1年 & 24h成交额Top-50”并抓取 ----------
def fetch_top50_last_year_1h_history_ge_1y(pad_missing=False, out_dir="./data_crypho/", proxies=None):
    """
    选择条件：
      1) USDT-M 永续，状态 TRADING
      2) 在这些合约里按 24h 报价量降序
      3) 逐个检查最早K线时间，只有“上市≥1年”的才入选，直到凑满50个
    抓取：
      最近一年 1h K线（时间对齐到当前整点）。可选 pad_missing 补齐为 8760 行。
    """
    client = BinanceFuturesUSDTClient(interval="1h", proxies=proxies)

    # 候选池：USDT-M 永续
    pool = client.fetch_usdt_perp_symbols()
    # 先按 24h 成交额排序，取较大的候选集，方便筛掉历史不足1年的
    ranked = client.top_by_quote_volume(pool, topn=max(200, len(pool)))
    one_year_ago = datetime.utcnow() - timedelta(days=365)

    selected = []
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

    # 抓取最近1年窗口（恰好 8760 小时网格）
    end_dt = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(hours=TARGET_ROWS_1Y_1H - 1)
    end_ms = int(end_dt.timestamp() * 1000)
    start_ms = int(start_dt.timestamp() * 1000)

    saved = []
    for sym in selected:
        try:
            logger.info(f"Fetching {sym} 1h last 1y ...")
            df = client.fetch_klines_range(sym, start_ms=start_ms, end_ms=end_ms)

            if pad_missing:
                df = pad_to_hour_grid(df, start_dt, end_dt)

            # 最终裁剪为 <= 8760 行（pad 模式下恰好 8760）
            if len(df) > TARGET_ROWS_1Y_1H:
                df = df.iloc[-TARGET_ROWS_1Y_1H:].reset_index(drop=True)

            fn = f"{out_dir.rstrip('/')}/{sym}_1h_last1y.csv"
            df.to_csv(fn, index=False)
            logger.info(f"{sym}: saved {len(df)} rows -> {fn}")
            saved.append(fn)
        except Exception as e:
            logger.warning(f"{sym}: failed, skip. {e}")
            continue
    return saved
