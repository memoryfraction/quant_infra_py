# factors/strategy_performance_model.py

from dataclasses import dataclass

@dataclass
class StrategyPerformanceModel:
    """
    策略历史回测表现原始数据模型（不包含计算出的分数）。
    这些字段会被用于计算 strategy_performance 因子得分。
    """

    # 年化收益率（例如 0.6022 表示 60.22%）
    annual_return: float

    # 年化夏普比率（例如 1.2）
    sharpe_ratio: float

    # 收益回撤比（Return / Max Drawdown），例如 5.018
    return_drawdown_ratio: float

    # 平均持仓天数（例如 2）
    avg_holding_days: float

    # 历史表现总权重（例如 0.35）
    total_weight: float = 0.35

    # 子指标权重（默认值，可在外部覆盖）
    annual_return_weight: float = 0.25
    sharpe_weight: float = 0.20
    return_drawdown_weight: float = 0.20
    avg_holding_days_weight: float = 0.15

    def to_dict(self):
        """
        转换为 dict，字段名和打分器对应
        """
        return {
            "annual_return": self.annual_return,
            "sharpe_ratio": self.sharpe_ratio,
            "return_drawdown_ratio": self.return_drawdown_ratio,
            "avg_holding_days": self.avg_holding_days
        }

    def weights_dict(self):
        """
        获取子指标权重字典，字段名必须和 StrategyPerformanceScorer 一致
        """
        return {
            "annual_return": self.annual_return_weight,
            "sharpe_ratio": self.sharpe_weight,
            "return_drawdown_ratio": self.return_drawdown_weight,
            "avg_holding_days": self.avg_holding_days_weight
        }

