from pydantic import BaseModel, Field
from typing import Dict

class BacktestInput(BaseModel):
    """历史回测表现输入模型"""
    annual_return: float = Field(ge=0, le=100, description="年化收益 (0-100)")
    sharpe_ratio: float = Field(ge=0, le=100, description="夏普比率 (0-100)")
    return_drawdown: float = Field(ge=0, le=100, description="收益回撤比 (0-100)")
    avg_holding_days: float = Field(ge=0, le=100, description="平均持仓天数 (0-100)")

class FactorInputModel(BaseModel):
    """因子输入模型"""
    cointegration: float = Field(ge=0, le=100, description="协整性分数 (0-100)")
    correlation: float = Field(ge=0, le=100, description="相关性分数 (0-100)")
    hurst: float = Field(ge=0, le=100, description="Hurst指数 (0-100)")
    half_life: float = Field(ge=0, le=100, description="半衰期 (0-100)")
    backtest: BacktestInput = Field(description="历史回测表现")

    def to_dict(self) -> Dict:
        """将模型转换为字典格式，兼容 FactorCalcuService 的输入"""
        return {
            "cointegration": self.cointegration,
            "correlation": self.correlation,
            "hurst": self.hurst,
            "half_life": self.half_life,
            "backtest": {
                "annual_return": self.backtest.annual_return,
                "sharpe_ratio": self.backtest.sharpe_ratio,
                "return_drawdown": self.backtest.return_drawdown,
                "avg_holding_days": self.backtest.avg_holding_days
            }
        }