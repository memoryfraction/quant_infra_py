import unittest
from dependency_injector import containers, providers
from factor_input_model import FactorInputModel
from factor_calcu_service import FactorCalcuService
from pydantic_core import ValidationError


class Container(containers.DeclarativeContainer):
    """IoC 容器"""
    data_source = providers.Object(None)  # 可替换为实际数据源
    factor_calcu_service = providers.Factory(FactorCalcuService, data_source=data_source)


class TestFactorCalcuService(unittest.TestCase):
    def setUp(self):
        """初始化测试环境，使用 IoC 容器"""
        self.container = Container()
        self.service = self.container.factor_calcu_service()
        self.valid_input = FactorInputModel(
            cointegration=80.0,
            correlation=75.0,
            hurst=60.0,
            half_life=70.0,
            backtest={
                "annual_return": 90.0,
                "sharpe_ratio": 85.0,
                "return_drawdown": 70.0,
                "avg_holding_days": 65.0
            }
        )

    def test_calculate_weighted_score_valid_input(self):
        """测试有效输入的加权打分"""
        score = self.service.calculate_weighted_score(self.valid_input)
        expected_score = 68.8875
        print(f"实际总得分: {score}")
        result = self.service.get_result('weighted_score')
        print(f"详细结果: {result}")

        self.assertAlmostEqual(score, expected_score, places=4, msg="总分与预期值不符，预期总分：68.8875")

        expected_result = {
            'total_score': 68.8875,
            'breakdown': {
                'cointegration': 0.16,
                'correlation': 0.1125,
                'hurst': 0.09,
                'half_life': 0.105,
                'backtest': 0.221375
            }
        }
        self.assertAlmostEqual(result['total_score'], expected_result['total_score'], places=4, msg="总分与预期值不符")
        for factor, value in expected_result['breakdown'].items():
            self.assertAlmostEqual(result['breakdown'][factor], value, places=4, msg=f"{factor} 的明细与预期值不符")

    def test_calculate_weighted_score_invalid_input(self):
        """测试无效输入（超出范围）"""
        with self.assertRaises(ValidationError, msg="未捕获无效 half_life 的 ValidationError"):
            FactorInputModel(
                cointegration=80.0,
                correlation=75.0,
                hurst=60.0,
                half_life=-10.0,
                backtest={
                    "annual_return": 90.0,
                    "sharpe_ratio": 85.0,
                    "return_drawdown": 70.0,
                    "avg_holding_days": 65.0
                }
            )

        with self.assertRaises(ValidationError, msg="未捕获无效 return_drawdown 的 ValidationError"):
            FactorInputModel(
                cointegration=80.0,
                correlation=75.0,
                hurst=60.0,
                half_life=70.0,
                backtest={
                    "annual_return": 90.0,
                    "sharpe_ratio": 85.0,
                    "return_drawdown": 170.0,
                    "avg_holding_days": 65.0
                }
            )


if __name__ == '__main__':
    unittest.main()