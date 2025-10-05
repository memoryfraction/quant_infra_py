from abc import ABC, abstractmethod
from factor_input_model import FactorInputModel


class FactorCalcuInterface(ABC):
    """因子计算服务接口"""

    @abstractmethod
    def calculate_weighted_score(self, input_model: FactorInputModel) -> float:
        """计算因子加权打分

        Args:
            input_model (FactorInputModel): 因子输入模型，包含协整性、相关性、Hurst指数、半衰期和历史回测表现

        Returns:
            float: 加权总分 (0-100)

        Raises:
            ValueError: 如果输入参数无效
        """
        pass



class FactorCalcuService(FactorCalcuInterface):
    def __init__(self, data_source=None):
        """初始化因子计算服务

        Args:
            data_source: 数据源，可以是DataFrame、数据库连接或其他数据结构
        """
        self.data_source = data_source
        self.results = {}  # 存储计算结果

    def calculate_factor(self, factor_name: str, params=None):
        """计算指定因子

        Args:
            factor_name (str): 因子名称
            params (dict, optional): 计算因子所需的参数

        Returns:
            Result of the factor calculation
        """
        if not self.data_source:
            raise ValueError("Data source is not initialized")

        method_name = f"_calc_{factor_name.lower()}"
        calc_method = getattr(self, method_name, None)

        if not calc_method:
            raise NotImplementedError(f"Factor {factor_name} calculation is not implemented")

        result = calc_method(params)
        self.results[factor_name] = result
        return result

    def get_result(self, factor_name: str):
        """获取指定因子的计算结果

        Args:
            factor_name (str): 因子名称

        Returns:
            Stored result for the specified factor
        """
        return self.results.get(factor_name, None)

    def _calc_moving_average(self, params=None):
        """示例：计算移动平均因子

        Args:
            params (dict): 包含窗口大小等参数，例如 {'window': 20}

        Returns:
            Calculated moving average
        """
        if not params or 'window' not in params:
            raise ValueError("Window size must be specified in params")

        window = params['window']
        if hasattr(self.data_source, 'close'):
            return self.data_source['close'].rolling(window=window).mean()
        else:
            raise ValueError("Data source must contain 'close' column")

    def add_custom_factor(self, factor_name: str, calc_function):
        """添加自定义因子计算方法

        Args:
            factor_name (str): 自定义因子名称
            calc_function (callable): 计算函数
        """
        setattr(self, f"_calc_{factor_name.lower()}", calc_function)

    def calculate_weighted_score(self, input_model: FactorInputModel) -> float:
        """实现接口：计算因子加权打分

        Args:
            input_model (FactorInputModel): 因子输入模型，包含协整性、相关性、Hurst指数、半衰期和历史回测表现

        Returns:
            float: 加权总分 (0-100)
        """
        # 定义权重
        weights = {
            'cointegration': 0.20,  # 20%
            'correlation': 0.15,  # 15%
            'hurst': 0.15,  # 15%
            'half_life': 0.15,  # 15%
            'backtest': 0.35  # 35%
        }
        backtest_subweights = {
            'annual_return': 0.25,  # 25%
            'sharpe_ratio': 0.20,  # 20%
            'return_drawdown': 0.20,  # 20%
            'avg_holding_days': 0.15  # 15%
        }

        # 验证输入（pydantic 已保证范围，但这里再确认）
        for factor, value in [
            ('cointegration', input_model.cointegration),
            ('correlation', input_model.correlation),
            ('hurst', input_model.hurst),
            ('half_life', input_model.half_life),
            ('backtest.annual_return', input_model.backtest.annual_return),
            ('backtest.sharpe_ratio', input_model.backtest.sharpe_ratio),
            ('backtest.return_drawdown', input_model.backtest.return_drawdown),
            ('backtest.avg_holding_days', input_model.backtest.avg_holding_days)
        ]:
            if not 0 <= value <= 100:
                raise ValueError(f"{factor} must be between 0 and 100")

        # 标准化分数 (0-1)
        normalized_scores = {
            'cointegration': input_model.cointegration / 100.0,
            'correlation': input_model.correlation / 100.0,
            'hurst': input_model.hurst / 100.0,
            'half_life': input_model.half_life / 100.0
        }

        # 计算历史回测表现子因子的加权分数
        backtest_score = (
                input_model.backtest.annual_return / 100.0 * backtest_subweights['annual_return'] +
                input_model.backtest.sharpe_ratio / 100.0 * backtest_subweights['sharpe_ratio'] +
                input_model.backtest.return_drawdown / 100.0 * backtest_subweights['return_drawdown'] +
                input_model.backtest.avg_holding_days / 100.0 * backtest_subweights['avg_holding_days']
        )
        normalized_scores['backtest'] = backtest_score

        # 计算总加权分数
        total_score = sum(normalized_scores[factor] * weight for factor, weight in weights.items())

        # 保存结果（包括总分和明细）
        self.results['weighted_score'] = {
            'total_score': total_score * 100,
            'breakdown': {
                factor: normalized_scores[factor] * weight for factor, weight in weights.items()
            }
        }

        return total_score * 100