import numpy as np
import pandas as pd


class HalfLifeFactor:
    def __init__(self, window: int = 100, max_half_life: float = 100):
        """
        window: 滚动窗口长度
        max_half_life: 映射到0分的最大半衰期
        """
        self.window = window
        self.max_half_life = max_half_life

    def calculate(self, series1: pd.Series, series2: pd.Series = None) -> pd.Series:
        """
        计算滚动半衰期，并映射到 [0, 100] 的均值回复得分：
        半衰期越短 => 分数越高（强均值回复）
        半衰期越长 => 分数越低（趋势性强）
        """
        hl_list = []
        for i in range(len(series1)):
            if i < self.window:
                hl_list.append(np.nan)
                continue

            y = series1[i - self.window:i]
            y_lag = y.shift(1).iloc[1:]
            y_ret = y.diff().iloc[1:]

            # 避免除以零
            if y_lag.std() < 1e-6:
                hl_list.append(np.nan)
                continue

            beta = np.polyfit(y_lag, y_ret, 1)[0]
            if abs(beta) < 1e-6:
                hl_list.append(np.nan)
                continue

            hl = -np.log(2) / beta
            if hl < 0 or np.isnan(hl) or np.isinf(hl):
                hl_list.append(np.nan)
                continue

            # 限制范围
            hl = np.clip(hl, 0, self.max_half_life)
            hl_list.append(hl)

        # 平滑结果
        hl_series = pd.Series(hl_list, index=series1.index)
        hl_series = hl_series.rolling(3, min_periods=1).mean()

        # 映射到 0-100 分：半衰期越短，得分越高
        score = 100 * np.clip(1 - hl_series / self.max_half_life, 0, 1)
        return score
