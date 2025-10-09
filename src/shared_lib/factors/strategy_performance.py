from strategy_performance_model import StrategyPerformanceModel
import numpy as np

class StrategyPerformanceScorer:
    """
    对策略表现模型进行百分比打分（0-100），
    根据 min/max 动态范围或 percentile。
    """

    def __init__(self, models: list[StrategyPerformanceModel]):
        self.models = models

        # 根据所有 pairs 计算 min/max
        self.min_annual_return = min(m.annual_return for m in models)
        self.max_annual_return = max(m.annual_return for m in models)

        self.min_sharpe_ratio = min(m.sharpe_ratio for m in models)
        self.max_sharpe_ratio = max(m.sharpe_ratio for m in models)

        self.min_return_drawdown = min(m.return_drawdown_ratio for m in models)
        self.max_return_drawdown = max(m.return_drawdown_ratio for m in models)

        self.min_holding_days = min(m.avg_holding_days for m in models)
        self.max_holding_days = max(m.avg_holding_days for m in models)

    # -------------------------
    #   通用 percentile 打分函数
    # -------------------------
    def _score_percentile(self, value: float, all_values: list[float], reverse: bool = False) -> float:
        """
        基于 percentile 打分
        reverse=True 表示值越小分数越高（适用于持仓天数）
        """
        percentile = (np.sum(np.array(all_values) <= value) / len(all_values)) * 100
        if reverse:
            percentile = 100 - percentile
        return max(min(percentile, 100), 0)

    def score_annual_return(self, model: StrategyPerformanceModel) -> float:
        return self._score_percentile(model.annual_return,
                                      [m.annual_return for m in self.models])

    def score_sharpe_ratio(self, model: StrategyPerformanceModel) -> float:
        return self._score_percentile(model.sharpe_ratio,
                                      [m.sharpe_ratio for m in self.models])

    def score_return_drawdown(self, model: StrategyPerformanceModel) -> float:
        return self._score_percentile(model.return_drawdown_ratio,
                                      [m.return_drawdown_ratio for m in self.models])

    def score_avg_holding_days(self, model: StrategyPerformanceModel) -> float:
        return self._score_percentile(model.avg_holding_days,
                                      [m.avg_holding_days for m in self.models],
                                      reverse=True)

    def calculate_score(self, model: StrategyPerformanceModel) -> dict:
        scores = {
            "annual_return_score": self.score_annual_return(model),
            "sharpe_ratio_score": self.score_sharpe_ratio(model),
            "return_drawdown_score": self.score_return_drawdown(model),
            "avg_holding_days_score": self.score_avg_holding_days(model)
        }

        # 根据权重计算加权分数
        weights = model.weights_dict()
        total_factor_score = (
                scores["annual_return_score"] * weights["annual_return"] +
                scores["sharpe_ratio_score"] * weights["sharpe_ratio"] +
                scores["return_drawdown_score"] * weights["return_drawdown_ratio"] +
                scores["avg_holding_days_score"] * weights["avg_holding_days"]
        )

        scores["factor_score"] = round(total_factor_score, 2)
        scores["final_score"] = round(total_factor_score * (model.total_weight / 100), 4)
        return scores