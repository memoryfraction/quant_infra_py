from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enums import ResolutionLevel
from underlying_pair import UnderlyingPair


@dataclass(frozen=True)
class UnderlyingPairAnalysisResult:
    """
    配对交易分析结果的数据容器。
    此结果通常用于评估两个标的物是否适合进行统计套利配对交易。
    使用 frozen=True 使其不可变。
    """

    # --- 核心数据点 ---

    # 标的物对（通常包含符号和文件路径信息）
    underlying_pair: UnderlyingPair

    # 价格序列的相关性系数
    correlation_value: float

    # 检验结果：序列是否高度相关 (如 CorrelationValue > Threshold)
    is_correlated: bool

    # 检验结果：价差（或残差）序列是否平稳 (如 ADF 检验)
    is_stationary: bool

    # 检验结果：价差序列是否符合正态分布 (如 Jarque-Bera 检验)
    is_normal_distributed: bool

    # 描述配对关系的协整（或线性回归）等式，例如："Y = 0.85*X + 5.2"
    diff_equation: str

    # 线性回归的斜率（对冲比率 Beta）
    slope: float

    # 线性回归的截距
    intercept: float

    # --- 分析时间窗口 ---

    # 分析数据的开始时间
    start_dt: datetime

    # 分析数据的结束时间
    end_dt: datetime

    # 分析使用的数据分辨率级别
    resolution_level: ResolutionLevel

    # 可选字段：例如用于存储协整检验的 p-value 或半衰期
    extra_info: Optional[dict] = field(default_factory=dict)

    def __str__(self) -> str:
        """提供简洁的字符串表示。"""
        pair_str = str(self.underlying_pair) if self.underlying_pair else "N/A"
        return (
            f"PairAnalysisResult(Pair={pair_str}, Corr={self.correlation_value:.4f}, "
            f"Stationary={self.is_stationary}, IsNormal={self.is_normal_distributed}, "
            f"HedgeRatio={self.slope:.4f})"
        )