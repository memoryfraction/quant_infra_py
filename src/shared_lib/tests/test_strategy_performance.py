# test_strategy_performance.py

import unittest

from factors.strategy_performance import StrategyPerformanceScorer
from strategy_performance_model import StrategyPerformanceModel


class TestStrategyPerformance(unittest.TestCase):

    def setUp(self):
        # 模拟 6 个策略 pair 的回测数据
        self.models = [
            StrategyPerformanceModel(annual_return=0.50, sharpe_ratio=1.2, return_drawdown_ratio=4.0, avg_holding_days=5),
            StrategyPerformanceModel(annual_return=0.60, sharpe_ratio=1.5, return_drawdown_ratio=5.0, avg_holding_days=3),
            StrategyPerformanceModel(annual_return=0.30, sharpe_ratio=0.8, return_drawdown_ratio=3.0, avg_holding_days=7),
            StrategyPerformanceModel(annual_return=0.55, sharpe_ratio=1.0, return_drawdown_ratio=4.5, avg_holding_days=4),
            StrategyPerformanceModel(annual_return=0.40, sharpe_ratio=1.3, return_drawdown_ratio=3.5, avg_holding_days=6),
            StrategyPerformanceModel(annual_return=0.65, sharpe_ratio=1.8, return_drawdown_ratio=5.5, avg_holding_days=2),
        ]

        # 初始化打分器
        self.scorer = StrategyPerformanceScorer(self.models)

    def test_scores_range(self):
        """
        测试所有 pair 打分是否在 0-100 之间
        """
        for model in self.models:
            scores = self.scorer.calculate_score(model)
            for key, value in scores.items():
                # final_score 可以小于 1，因为 total_weight/100
                if key != "final_score":
                    self.assertTrue(0 <= value <= 100, f"{key} out of range: {value}")

    def test_percentile_order(self):
        """
        测试 annual_return 百分位数排序逻辑
        annual_return 越大 score 越高
        """
        scores_list = [self.scorer.calculate_score(m)["annual_return_score"] for m in self.models]
        # 对应 annual_return 从小到大排序
        sorted_returns = sorted([m.annual_return for m in self.models])
        # score 应该是单调递增的
        for i in range(len(scores_list)):
            model_return = self.models[i].annual_return
            score = self.scorer.calculate_score(self.models[i])["annual_return_score"]
            expected_score = self.scorer._score_percentile(model_return, [m.annual_return for m in self.models])
            self.assertAlmostEqual(score, expected_score, places=4)

    def test_print_scores(self):
        """
        打印所有 pair 的最终分数，便于实战观察
        """
        print("\n=== Strategy Performance Scores ===")
        for i, model in enumerate(self.models):
            scores = self.scorer.calculate_score(model)
            print(f"Pair {i+1}: {scores}")

if __name__ == "__main__":
    unittest.main()
