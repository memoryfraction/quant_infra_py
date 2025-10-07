import pandas as pd
import numpy as np
from statsmodels.regression.linear_model import OLS
from statsmodels.tsa.stattools import adfuller

class CointegrationFactor:
    """
    用于计算配对交易协整性因子的类。
    得分公式：min((1 - p_value / max_p) × 100, 100)
    """

    def __init__(self, max_p=0.05):
        """
        初始化协整性因子类。

        参数：
        - max_p: ADF p 值最大阈值（默认 0.05）
        """
        self.max_p = max_p

        if not 0 < max_p <= 1:
            raise ValueError("max_p 必须在 (0, 1] 范围内")

    def calculate(self, asset1_prices, asset2_prices):
        """
        计算配对的协整性因子得分。

        参数：
        - asset1_prices: 资产1的收盘价序列（pd.Series 或 np.array）
        - asset2_prices: 资产2的收盘价序列（pd.Series 或 np.array）

        返回：
        - dict: 包含因子得分和 ADF p 值的字典
            - 'score': 协整性因子得分（0-100）
            - 'p_value': ADF 检验的 p 值
            - 'hedge_ratio': OLS 回归的斜率（a）
            - 'intercept': OLS 回归的截距（c）
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

        # 进行 OLS 回归：asset1 = a * asset2 + c
        X = asset2_prices
        y = asset1_prices
        model = OLS(y, np.vstack([X, np.ones(len(X))]).T).fit()
        hedge_ratio = model.params[0]  # 斜率 a
        intercept = model.params[1]    # 截距 c

        # 计算价差序列：asset1 - a * asset2 - c
        spread = asset1_prices - hedge_ratio * asset2_prices - intercept

        # 进行 ADF 检验
        adf_result = adfuller(spread, maxlag=None, regression='c', autolag='AIC')
        p_value = adf_result[1]  # ADF 检验的 p 值

        # 如果 p 值大于阈值，返回 0 分（未通过筛选）
        if p_value > self.max_p:
            return {
                'score': 0,
                'p_value': p_value,
                'hedge_ratio': hedge_ratio,
                'intercept': intercept
            }

        # 计算得分
        score = min((1 - p_value / self.max_p) * 100, 100)

        return {
            'score': score,
            'p_value': p_value,
            'hedge_ratio': hedge_ratio,
            'intercept': intercept
        }

# 示例使用
if __name__ == "__main__":
    # 模拟 91 天 1 小时 OHLC 数据
    np.random.seed(42)
    dates = pd.date_range(end="2025-09-22", periods=91*24, freq="H")
    btc_prices = pd.Series(60000 + np.random.normal(0, 1200, len(dates)))
    eth_prices = pd.Series(3000 + btc_prices * 0.05 + np.random.normal(0, 90, len(dates)))

    # 实例化 CointegrationFactor 类
    cointegration_factor = CointegrationFactor(max_p=0.05)

    # 计算协整性因子得分
    result = cointegration_factor.calculate(btc_prices, eth_prices)
    print(f"ADF p 值: {result['p_value']:.4f}")
    print(f"协整性因子得分: {result['score']:.2f}")
    print(f"对冲比率 (hedge_ratio): {result['hedge_ratio']:.4f}")
    print(f"截距 (intercept): {result['intercept']:.4f}")