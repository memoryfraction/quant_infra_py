from enum import Enum

class ResolutionLevel(Enum):
    Tick = "t"
    Second = "s"
    Minute = "min"
    Hourly = "h"
    Daily = "d"
    Weekly = "wk"
    Monthly = "mo"
    Other = "other"

class UnderlyingType(Enum):
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_PERPETUAL_CONTRACT = "crypto_perpetual_contract"
    CRYPTO_FUTURES = "crypto_futures"
    STOCK = "stock"
    ETF = "etf"