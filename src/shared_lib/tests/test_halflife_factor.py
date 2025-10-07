import unittest
import numpy as np
import pandas as pd
from factors.halflife_factor import HalfLifeFactor


class TestHalfLifeFactor(unittest.TestCase):
    def setUp(self):
        self.factor = HalfLifeFactor(window=50, max_half_life=100)

    def test_constant_series(self):
        x = np.ones(200)
        series = pd.Series(x)
        score = self.factor.calculate(series)
        latest_score = score.iloc[-1]
        print("Constant score:", latest_score)
        self.assertTrue(np.isnan(latest_score) or 0 <= latest_score <= 100)

    def test_mean_reverting_series(self):
        np.random.seed(0)
        x = [0]
        for _ in range(199):
            x.append(0.8 * x[-1] + np.random.normal())
        series = pd.Series(x)
        score = self.factor.calculate(series)
        latest_score = score.iloc[-1]
        print("Mean-reverting score:", latest_score)
        self.assertGreater(latest_score, 50)

    def test_trending_series(self):
        np.random.seed(1)
        x = np.cumsum(np.random.normal(size=200))
        series = pd.Series(x)
        score = self.factor.calculate(series)
        latest_score = score.iloc[-1]
        print("Trending score:", latest_score)
        self.assertLess(latest_score, 50)


if __name__ == "__main__":
    unittest.main()
