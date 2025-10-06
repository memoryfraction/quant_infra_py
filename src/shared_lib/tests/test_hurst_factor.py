# test_hurst_factor.py
import unittest
import pandas as pd
import numpy as np
from factors.hurst_factor import HurstFactor

class TestHurstFactor(unittest.TestCase):
    def setUp(self):
        self.factor = HurstFactor(window=200)

    def test_mean_reverting_series(self):
        # AR(1) 均值回复
        np.random.seed(0)
        x = [0]
        for _ in range(999):
            x.append(0.8 * x[-1] + np.random.normal())
        series = pd.Series(x)
        score = self.factor.calculate(series)
        latest_score = score.iloc[-1]  # 取最后一个值
        print("Mean-reverting score:", latest_score)
        self.assertGreater(latest_score, 50)

    def test_trending_series(self):
        # 随机游走趋势
        np.random.seed(1)
        x = np.cumsum(np.random.normal(size=1000))
        series = pd.Series(x)
        score = self.factor.calculate(series)
        latest_score = score.iloc[-1]  # 取最后一个值
        print("Trending score:", latest_score)
        self.assertLess(latest_score, 50)


if __name__ == "__main__":
    unittest.main()
