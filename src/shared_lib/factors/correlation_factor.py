import pandas as pd
import numpy as np


class CorrelationFactor:
    """
    用于计算配对交易相关性因子的类。
    得分公式：(correlation - min_corr) / (max_corr - min_corr) × 100
    """

    def __init__(self, min_corr=0.7, max_corr=1.0):
        """
        初始化相关性因子类。

        参数：
        - min_corr: 相关性最低阈值（默认 0.7）
        - max_corr: 相关性最大值（默认 1.0）
        """
        self.min_corr = min_corr
        self.max_corr = max_corr

        # 验证参数
        if not 0 <= min_corr < max_corr <= 1:
            raise ValueError("min_corr 必须在 [0, 1) 且小于 max_corr，max_corr 必须在 (0, 1]")

    def calculate(self, asset1_prices, asset2_prices):
        """
        计算配对的相关性因子得分。

        参数：
        - asset1_prices: 资产1的收盘价序列（pd.Series 或 np.array）
        - asset2_prices: 资产2的收盘价序列（pd.Series 或 np.array）

        返回：
        - dict: 包含因子得分和相关性系数的字典
            - 'score': 相关性因子得分（0-100）
            - 'correlation': 皮尔逊相关系数
        """
        # 转换为 numpy 数组
        asset1_prices = np.array(asset1_prices)
        asset2_prices = np.array(asset2_prices)

        # 检查数据长度是否一致
        if len(asset1_prices) != len(asset2_prices):
            raise ValueError("两个资产的价格序列长度不一致")

        # 检查是否有缺失值
        if np.any(np.isnan(asset1_prices)) or np.any(np.isnan(asset2_prices)):
            raise ValueError("价格序列中包含缺失值")

        # 计算皮尔逊相关系数
        correlation = np.corrcoef(asset1_prices, asset2_prices)[0, 1]

        # 如果相关性低于阈值，返回 0 分（未通过筛选）
        if correlation < self.min_corr:
            return {'score': 0, 'correlation': correlation}

        # 计算得分
        score = (correlation - self.min_corr) / (self.max_corr - self.min_corr) * 100
        score = min(score, 100)  # 确保得分不超过 100

        return {'score': score, 'correlation': correlation}


# 示例使用
if __name__ == "__main__":
    # 模拟 91 天 1 小时 OHLC 数据
    np.random.seed(42)
    dates = pd.date_range(end="2025-09-22", periods=91 * 24, freq="H")
    btc_prices = pd.Series(60000 + np.random.normal(0, 1200, len(dates)), index=dates)  # BTCUSDT 收盘价
    eth_prices = pd.Series(3000 + btc_prices * 0.05 + np.random.normal(0, 90, len(dates)), index=dates)  # ETHUSDT 收盘价

    # 实例化 CorrelationFactor 类
    corr_factor = CorrelationFactor(min_corr=0.7, max_corr=1.0)

    # 计算相关性因子得分
    result = corr_factor.calculate(btc_prices, eth_prices)
    print(f"相关性系数: {result['correlation']:.4f}")
    print(f"相关性因子得分: {result['score']:.2f}")