# hurst_factor.py
import pandas as pd
import numpy as np
import statsmodels.api as sm
from hurst import compute_Hc

class HurstFactor:
    def __init__(self, window: int = 100, max_score: float = 100):
        """
        window: 滚动窗口长度
        max_score: Hurst 因子最大得分
        """
        self.window = window
        self.max_score = max_score

    def calculate(self, series1: pd.Series, series2: pd.Series = None) -> pd.Series:
        """
        返回 Hurst 因子得分 Series (0-100)
        支持单序列或两序列（Spread）
        """
        series1 = series1.astype(float)
        if series2 is not None:
            series2 = series2.astype(float)
            if series1.var() < 1e-8 or series2.var() < 1e-8:
                return pd.Series(50, index=series1.index)

            # 计算 Spread
            spread = []
            for i in range(len(series1)):
                if i < self.window:
                    spread.append(np.nan)
                else:
                    y_window = series1[i - self.window:i]
                    x_window = series2[i - self.window:i]
                    X = sm.add_constant(x_window)
                    model = sm.OLS(y_window, X).fit()
                    B = model.params[0]
                    A = model.params[1]
                    spread.append(y_window.iloc[-1] - (A * x_window.iloc[-1] + B))
            series_to_calc = pd.Series(spread, index=series1.index)
        else:
            series_to_calc = series1.copy()

        # Hurst 滚动计算
        hurst_scores = []
        for i in range(len(series_to_calc)):
            if i < self.window:
                hurst_scores.append(np.nan)
            else:
                window_data = series_to_calc[i - self.window:i].values
                if np.all(window_data == window_data[0]):
                    hurst_scores.append(50)  # 常数序列默认 50
                else:
                    try:
                        H, c, data_reg = compute_Hc(window_data, kind='random_walk', simplified=True)
                        score = (1 - H) * self.max_score
                        score = np.clip(score, 0, self.max_score)
                        hurst_scores.append(score)
                    except:
                        hurst_scores.append(50)
        return pd.Series(hurst_scores, index=series1.index)