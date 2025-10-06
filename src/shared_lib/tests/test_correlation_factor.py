import unittest
import sys
import os
import pandas as pd
import numpy as np

# 添加 shared_lib 目录到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from factors.correlation_factor import CorrelationFactor


class TestCorrelationFactor(unittest.TestCase):
    def setUp(self):
        """初始化测试环境"""
        self.corr_factor = CorrelationFactor(min_corr=0.7, max_corr=1.0)
        # 模拟 91 天 1 小时数据
        np.random.seed(42)
        self.dates = pd.date_range(end="2025-09-22", periods=91 * 24, freq="h")
        self.btc_prices = pd.Series(60000 + np.random.normal(0, 1200, len(self.dates)))
        self.eth_prices = pd.Series(3000 + self.btc_prices * 0.05 + np.random.normal(0, 90, len(self.dates)))

    def test_normal_case(self):
        """测试正常情况下的相关性因子得分"""
        result = self.corr_factor.calculate(self.btc_prices, self.eth_prices)

        # 动态计算预期值，而不是写死常数
        expected_corr = np.corrcoef(self.btc_prices, self.eth_prices)[0, 1]
        expected_score = (
            (expected_corr - self.corr_factor.min_corr)
            / (self.corr_factor.max_corr - self.corr_factor.min_corr)
            * 100
            if expected_corr >= self.corr_factor.min_corr
            else 0
        )
        expected_score = min(expected_score, 100)

        self.assertAlmostEqual(result['correlation'], expected_corr, places=6)
        self.assertAlmostEqual(result['score'], expected_score, places=6)

    def test_below_min_corr(self):
        """测试相关性低于阈值的情况"""
        np.random.seed(43)
        uncorrelated_prices = pd.Series(np.random.normal(0, 100, len(self.dates)))
        result = self.corr_factor.calculate(self.btc_prices, uncorrelated_prices)
        self.assertLess(result['correlation'], self.corr_factor.min_corr)
        self.assertEqual(result['score'], 0)

    def test_perfect_correlation(self):
        """测试相关性为 1.0 的情况"""
        perfect_corr_prices = self.btc_prices * 0.05  # 完全线性相关
        result = self.corr_factor.calculate(self.btc_prices, perfect_corr_prices)
        self.assertAlmostEqual(result['correlation'], 1.0, places=6)
        self.assertAlmostEqual(result['score'], 100.0, places=6)

    def test_min_corr_boundary(self):
        """测试相关性接近 min_corr 的情况"""
        np.random.seed(44)
        min_corr_prices = self.btc_prices * 0.05 + np.random.normal(0, 1200, len(self.dates))
        result = self.corr_factor.calculate(self.btc_prices, min_corr_prices)
        # 验证分数逻辑是否符合 min_corr 设定
        if result['correlation'] >= self.corr_factor.min_corr:
            self.assertGreaterEqual(result['score'], 0)
        else:
            self.assertEqual(result['score'], 0)

    def test_unequal_length(self):
        """测试价格序列长度不一致的情况"""
        short_prices = self.eth_prices[:-10]
        with self.assertRaises(ValueError) as context:
            self.corr_factor.calculate(self.btc_prices, short_prices)
        self.assertEqual(str(context.exception), "两个资产的价格序列长度不一致")

    def test_missing_values(self):
        """测试包含缺失值的情况"""
        btc_prices_with_nan = self.btc_prices.copy()
        btc_prices_with_nan.iloc[10] = np.nan
        with self.assertRaises(ValueError) as context:
            self.corr_factor.calculate(btc_prices_with_nan, self.eth_prices)
        self.assertEqual(str(context.exception), "价格序列中包含缺失值")

    def test_invalid_parameters(self):
        """测试无效参数的情况"""
        with self.assertRaises(ValueError) as context:
            CorrelationFactor(min_corr=1.0, max_corr=0.7)
        self.assertEqual(str(context.exception), "min_corr 必须在 [0, 1) 且小于 max_corr，max_corr 必须在 (0, 1]")


if __name__ == '__main__':
    unittest.main()
