# trade_service.py
import os
import csv
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple
from decimal import Decimal, ROUND_UP, getcontext

import ccxt

getcontext().prec = 28  # 高精度小数计算，避免浮点误差


class TradeService:
    """
    ccxt 交易封装（支持 Binance USDT-M 合约/现货）
    - dry_run: True 只模拟，不发真实订单（且尽量启用 testnet/sandbox）
    - 自动对时 + recvWindow，避免 -1021
    - 自动将现货式符号规范化为合约符号（DOGE/USDT -> DOGE/USDT:USDT）
    - 读取交易所 filters 获取 stepSize / 最小名义额，严格进位
    - 自动满足最小名义额（默认 5 USDT），并在下单前二次复核 + 安全余量
    - CSV 审计日志
    """

    def __init__(
        self,
        exchange: str = "binanceusdm",
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
        audit_csv_path: Optional[str] = None,
        default_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        api_key = api_key or os.getenv("BINANCE_KEY")
        api_secret = api_secret or os.getenv("BINANCE_SECRET")

        ex_klass = getattr(ccxt, exchange)
        self.ex = ex_klass({
            "enableRateLimit": True,
            **({"apiKey": api_key, "secret": api_secret} if api_key and api_secret else {}),
        })
        self.ex.verbose = bool(verbose)

        # 自动对时，避免 -1021
        try:
            if not getattr(self.ex, "options", None):
                self.ex.options = {}
            self.ex.options["adjustForTimeDifference"] = True
            try:
                self.ex.load_time_difference()
            except Exception:
                pass
        except Exception:
            pass

        # dry-run 尽量走 sandbox（注意：需要对应 testnet key）
        try:
            self.ex.set_sandbox_mode(bool(dry_run))
        except Exception:
            pass

        self.exchange_id = exchange
        self.dry_run = bool(dry_run)
        self.audit_csv_path = audit_csv_path
        self.default_params = default_params or {"newOrderRespType": "RESULT", "recvWindow": 10000}
        self._markets_loaded = False

    # ---------------------- Public API ----------------------
    def market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        params: Optional[Dict[str, Any]] = None,
        position_side: Optional[str] = None,  # "LONG" | "SHORT"（对冲模式）
        reduce_only: Optional[bool] = None,
        client_order_id: Optional[str] = None,
        enforce_min_notional: bool = True,
        min_notional_usdt: Optional[float] = None,
        safety_factor: float = 1.02,  # 额外留 2% 余量，防价格跳变
    ) -> Dict[str, Any]:
        """
        市价单；若 enforce_min_notional=True 且非 reduce_only，会自动把数量补到 >= 最小名义额（默认 >=5 USDT）
        """
        self._ensure_markets_loaded()

        side_l = side.lower()
        if side_l not in {"buy", "sell"}:
            raise ValueError(f"Invalid side: {side}")

        symbol = self._normalize_symbol(symbol)
        market = self._get_market_or_raise(symbol)

        # 取价格：优先 markPrice，再退 last/close
        price = self._safe_price(symbol)

        # 先按交易所精度量化用户传入的数量
        q_amount = self._quantize_amount(amount, market)

        # 自动满足最小名义额（开仓/加仓时；reduce_only 跳过）
        if enforce_min_notional and not reduce_only and price is not None:
            step, ex_min_from_filter = self._binance_step_and_min_notional(market)
            ex_min_notional = ex_min_from_filter
            if ex_min_notional is None and self.exchange_id == "binanceusdm":
                ex_min_notional = 5.0
            target_min = float(min_notional_usdt) if min_notional_usdt is not None else (
                float(ex_min_notional) if ex_min_notional is not None else None
            )
            if target_min is not None:
                # 若当前名义额不足，按安全系数补量
                if q_amount * price < target_min:
                    q_amount = self._amount_for_min_notional(target_min * float(safety_factor), float(price), market)

        # 基本限额检查（数量最小/最大 + 名义额）
        self._check_amount_limits(q_amount, market, price)

        # 发单前再次复核最新价（防瞬时波动）
        if enforce_min_notional and not reduce_only:
            latest = self._safe_price(symbol) or price
            if latest is not None:
                step, ex_min_from_filter = self._binance_step_and_min_notional(market)
                ex_min_notional = ex_min_from_filter
                if ex_min_notional is None and self.exchange_id == "binanceusdm":
                    ex_min_notional = 5.0
                target_min = float(min_notional_usdt) if min_notional_usdt is not None else (
                    float(ex_min_notional) if ex_min_notional is not None else None
                )
                if target_min is not None and q_amount * latest < target_min:
                    q_amount = self._amount_for_min_notional(target_min * float(safety_factor), float(latest), market)

        # 组装参数
        final_params: Dict[str, Any] = {**self.default_params}
        if params:
            final_params.update(params)
        if position_side:
            final_params["positionSide"] = position_side
        if reduce_only is not None:
            final_params["reduceOnly"] = bool(reduce_only)
        if client_order_id:
            final_params["newClientOrderId"] = client_order_id

        ts_ms = int(time.time() * 1000)

        if self.dry_run:
            auto_adjusted = enforce_min_notional and not reduce_only and price is not None
            sim_order = {
                "id": f"SIM-{ts_ms}",
                "timestamp": ts_ms,
                "datetime": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "type": "market",
                "side": side_l,
                "amount": q_amount,
                "filled": q_amount,
                "remaining": 0.0,
                "status": "closed",
                "fee": None,
                "price": None,
                "cost": None,
                "info": {
                    "dry_run": True,
                    "params": final_params,
                    "autoAdjusted": bool(auto_adjusted),
                    "usedPrice": price,
                },
            }
            self._audit("market_order", symbol, side_l, q_amount, final_params, sim_order, is_error=False)
            return sim_order

        # 真下单
        try:
            order = self.ex.create_market_order(symbol, side_l, q_amount, final_params)
            if isinstance(order, dict):
                info = order.get("info") or {}
                info.setdefault("autoAdjusted", enforce_min_notional and not reduce_only)
                if price is not None:
                    info.setdefault("usedPrice", price)
                order["info"] = info
            self._audit("market_order", symbol, side_l, q_amount, final_params, order, is_error=False)
            return order
        except Exception as e:
            self._audit("market_order", symbol, side_l, q_amount, final_params, {"error": str(e)}, is_error=True)
            raise

    # ---------------------- Internals ----------------------
    def _ensure_markets_loaded(self) -> None:
        if not self._markets_loaded:
            self.ex.load_markets(reload=True)
            self._markets_loaded = True

    def _normalize_symbol(self, symbol: str) -> str:
        # 对 binanceusdm，把 "DOGE/USDT" 优先转成 "DOGE/USDT:USDT"
        s = symbol
        if self.exchange_id == "binanceusdm":
            if ":USDT" not in symbol and symbol.endswith("/USDT"):
                candidate = f"{symbol}:USDT"
                if candidate in self.ex.markets:
                    s = candidate
        return s

    def _get_market_or_raise(self, symbol: str) -> Dict[str, Any]:
        m = self.ex.markets.get(symbol)
        if not m:
            candidates = [k for k, v in self.ex.markets.items() if v.get("swap") and symbol.split("/")[0] in k]
            hint = f". Did you mean: {', '.join(candidates[:8])}" if candidates else ""
            raise ValueError(f"Symbol not found on {self.exchange_id}: {symbol}{hint}")
        return m

    def _safe_price(self, symbol: str) -> Optional[float]:
        try:
            t = self.ex.fetch_ticker(symbol)
            # 优先用 markPrice（合约更稳），再退 last/close
            info = t.get("info") or {}
            for key in ("markPrice", "lastPrice", "close"):
                v = info.get(key)
                if v:
                    try:
                        f = float(v)
                        if f > 0:
                            return f
                    except Exception:
                        pass
            for k in ("last", "close"):
                v = t.get(k)
                if isinstance(v, (int, float)) and v > 0:
                    return float(v)
        except Exception:
            return None
        return None

    def _binance_step_and_min_notional(self, market: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
        step = None
        min_notional = None
        try:
            for f in market.get("info", {}).get("filters", []):
                t = f.get("filterType")
                if t in ("LOT_SIZE", "MARKET_LOT_SIZE"):
                    ss = f.get("stepSize")
                    if ss is not None:
                        step = float(ss)
                if t in ("MIN_NOTIONAL", "NOTIONAL"):
                    mn = f.get("minNotional") or f.get("notional")
                    if mn is not None:
                        min_notional = float(mn)
        except Exception:
            pass
        return step, min_notional

    def _quantize_amount(self, amount: float, market: Dict[str, Any]) -> float:
        prec = market.get("precision", {}).get("amount")
        # precision 可能是整数（小数位）或浮点（步进）
        if isinstance(prec, int):
            fmt = "{:.%df}" % max(0, prec)
            return float(fmt.format(float(amount)))
        if isinstance(prec, float):
            # 当作步进
            if prec >= 1:
                return float(int(round(float(amount) / prec)) * prec)
            # 推导小数位
            from math import floor, log10
            try:
                decimals = max(0, -int(floor(log10(prec))))
            except Exception:
                decimals = 8
            fmt = "{:.%df}" % decimals
            return float(fmt.format(float(amount)))
        return float(amount)

    def _amount_for_min_notional(self, min_notional: float, price: float, market: Dict[str, Any]) -> float:
        # 用 Decimal 严格按 stepSize 向上取整
        step, _ = self._binance_step_and_min_notional(market)
        target = Decimal(str(min_notional))
        p = Decimal(str(price))
        raw = (target / max(p, Decimal("1e-12")))

        if step:
            s = Decimal(str(step))
            q = (raw / s).to_integral_value(rounding=ROUND_UP) * s  # ceil(raw/step) * step
        else:
            prec = market.get("precision", {}).get("amount")
            decimals = prec if isinstance(prec, int) and prec >= 0 else 8
            q = raw.quantize(Decimal("1." + "0" * decimals), rounding=ROUND_UP)

        return float(q)

    def _check_amount_limits(self, amount: float, market: Dict[str, Any], price: Optional[float] = None) -> None:
        limits = (market.get("limits") or {})
        amt_limits = limits.get("amount") or {}
        min_amt = amt_limits.get("min")
        max_amt = amt_limits.get("max")
        if min_amt is not None and amount < float(min_amt):
            raise ValueError(f"Amount {amount} is below min {min_amt} for {market.get('symbol')}")
        if max_amt is not None and amount > float(max_amt):
            raise ValueError(f"Amount {amount} is above max {max_amt} for {market.get('symbol')}")

        # 名义额（若能拿到价格）
        if price is not None:
            _, ex_min_from_filter = self._binance_step_and_min_notional(market)
            min_notional = ex_min_from_filter
            if min_notional is None and self.exchange_id == "binanceusdm":
                min_notional = 5.0
            if min_notional is not None:
                notional = amount * float(price)
                if notional < float(min_notional):
                    raise ValueError(
                        f"Order's notional {notional:.8f} < min {float(min_notional)} for {market.get('symbol')}"
                    )

    def _audit(
        self,
        action: str,
        symbol: str,
        side: str,
        amount: float,
        params: Dict[str, Any],
        result: Dict[str, Any],
        is_error: bool,
    ) -> None:
        if not self.audit_csv_path:
            return
        try:
            exists = os.path.exists(self.audit_csv_path)
            with open(self.audit_csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "ts_iso",
                        "exchange",
                        "action",
                        "symbol",
                        "side",
                        "amount",
                        "params",
                        "is_error",
                        "result",
                    ],
                )
                if not exists:
                    writer.writeheader()
                writer.writerow({
                    "ts_iso": datetime.now(timezone.utc).isoformat(),
                    "exchange": self.exchange_id,
                    "action": action,
                    "symbol": symbol,
                    "side": side,
                    "amount": amount,
                    "params": str(params),
                    "is_error": is_error,
                    "result": str(result),
                })
        except Exception:
            # 记录失败不影响交易
            pass



