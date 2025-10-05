import unittest
import sys
import os
import pandas as pd
import numpy as np
from statsmodels.tsa.stattools import adfuller

# 添加 shared_lib 目录到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from factors.cointegration_factor import CointegrationFactor

class TestCointegrationFactor(unittest.TestCase):
    """测试 CointegrationFactor 类的功能"""

    def setUp(self):
        """初始化测试环境"""
        self.coint_factor = CointegrationFactor(max_p=0.05)
        np.random.seed(42)
        self.dates = pd.date_range(end="2025-09-22", periods=91*24, freq="h")  # 'H' 已弃用，改为 'h'
        self.btc_prices = pd.Series(60000 + np.random.normal(0, 1200, len(self.dates)))
        self.eth_prices = pd.Series(3000 + self.btc_prices * 0.05 + np.random.normal(0, 90, len(self.dates)))

    def test_normal_case(self):
        """测试正常情况下的协整性因子得分"""
        result = self.coint_factor.calculate(self.btc_prices, self.eth_prices)
        self.assertTrue(0 <= result['score'] <= 100, "Score must be between 0 and 100")
        self.assertTrue(0 <= result['p_value'] <= 1, "p_value must be between 0 and 1")
        self.assertIsInstance(result['hedge_ratio'], float, "hedge_ratio must be float")
        self.assertIsInstance(result['intercept'], float, "intercept must be float")

    def test_stationary_spread(self):
        """测试价差平稳（p 值接近 0）的情况"""
        eth_prices_stationary = self.btc_prices * 0.05 + np.random.normal(0, 10, len(self.dates))
        result = self.coint_factor.calculate(self.btc_prices, eth_prices_stationary)
        self.assertLess(result['p_value'], 0.05, "p_value should be small for stationary spread")
        self.assertGreater(result['score'], 0, "Score should be positive for stationary spread")

    def test_non_stationary_spread(self):
        """测试价差非平稳（p 值 > 0.05）的情况"""
        # 构造两个独立随机游走序列，保证非平稳
        np.random.seed(42)
        x = np.cumsum(np.random.normal(0, 500, len(self.dates))) + 60000
        y = np.cumsum(np.random.normal(0, 500, len(self.dates))) + 3000
        result = self.coint_factor.calculate(pd.Series(y), pd.Series(x))

        print(f"Non-stationary p_value: {result['p_value']:.4f}")  # 调试输出
        print(f"Non-stationary score: {result['score']:.2f}")       # 调试输出

        self.assertGreater(result['p_value'], 0.05, "p_value should be > 0.05 for non-stationary spread")
        self.assertEqual(result['score'], 0, "Score should be 0 for non-stationary spread")

    def test_boundary_p_value(self):
        """测试 p 值接近 max_p (0.05) 的边界情况"""
        boundary_prices = self.btc_prices * 0.05 + np.random.normal(0, 500, len(self.dates))
        result = self.coint_factor.calculate(self.btc_prices, boundary_prices)
        self.assertTrue(0 <= result['score'] <= 100, "Score must be between 0 and 100")
        self.assertTrue(0 <= result['p_value'] <= 1, "p_value must be between 0 and 1")

    def test_unequal_length(self):
        """测试价格序列长度不一致的情况"""
        short_prices = self.eth_prices[:-10]
        with self.assertRaises(ValueError) as context:
            self.coint_factor.calculate(self.btc_prices, short_prices)
        self.assertEqual(str(context.exception), "两个资产的价格序列长度不一致")

    def test_missing_values(self):
        """测试包含缺失值的情况"""
        btc_prices_with_nan = self.btc_prices.copy()
        btc_prices_with_nan.iloc[10] = np.nan
        with self.assertRaises(ValueError) as context:
            self.coint_factor.calculate(btc_prices_with_nan, self.eth_prices)
        self.assertEqual(str(context.exception), "价格序列中包含缺失值")

    def test_invalid_parameters(self):
        """测试无效参数的情况"""
        with self.assertRaises(ValueError) as context:
            CointegrationFactor(max_p=0)
        self.assertEqual(str(context.exception), "max_p 必须在 (0, 1] 范围内")

        with self.assertRaises(ValueError) as context:
            CointegrationFactor(max_p=1.5)
        self.assertEqual(str(context.exception), "max_p 必须在 (0, 1] 范围内")

if __name__ == '__main__':
    unittest.main()
