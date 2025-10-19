import unittest
import os
import pandas as pd
from unittest.mock import patch, MagicMock
from shared_lib.bll.data_source_service import BinancePerpetualContractUSDTClient, pad_to_hour_grid
from datetime import datetime

class TestDataSourceService(unittest.TestCase):
    def setUp(self):
        # 创建测试目录
        os.makedirs('shared_lib/tests/data', exist_ok=True)
        # 准备测试数据文件
        self.test_data_dir = 'shared_lib/tests/data'
        # 创建数字货币测试文件
        self.btc_path = os.path.join(self.test_data_dir, 'BTC_USDT.csv')
        self.eth_path = os.path.join(self.test_data_dir, 'ETH_USDT.csv')
        
        # 创建数字货币示例数据文件
        if not os.path.exists(self.btc_path):
            pd.DataFrame({
                'DateTime': pd.date_range(start='2023-01-01', periods=100, freq='H'),
                'open': range(100),
                'high': range(100),
                'low': range(100),
                'close': range(100),
                'volume': range(100)
            }).to_csv(self.btc_path, index=False)
            
        if not os.path.exists(self.eth_path):
            pd.DataFrame({
                'DateTime': pd.date_range(start='2023-01-01', periods=100, freq='H'),
                'open': range(100),
                'high': range(100),
                'low': range(100),
                'close': range(100),
                'volume': range(100)
            }).to_csv(self.eth_path, index=False)

    def test_binance_perpetual_client_initialization(self):
        # 测试初始化
        client = BinancePerpetualContractUSDTClient(interval='1h')
        self.assertEqual(client.interval, '1h')
        self.assertEqual(client.step_ms, 3600000)  # 1小时转换为毫秒
        
        # 测试代理配置
        proxies = {'http': 'http://proxy', 'https': 'https://proxy'}
        with patch('ccxt.binanceusdm', return_value=MagicMock()) as mock_binanceusdm:
            mock_binanceusdm.return_value.proxies = proxies
            client_proxies = BinancePerpetualContractUSDTClient(interval='1h', proxies=proxies)
            self.assertEqual(client_proxies.binance.proxies, proxies)

    def test_fetch_usdt_perp_symbols(self):
        # 测试获取USDT永续合约符号
        client = BinancePerpetualContractUSDTClient()
        
        # 设置mock
        client.binance.markets = {
            'BTC/USDT:USDT': {
                'symbol': 'BTC/USDT:USDT',
                'quote': 'USDT',
                'info': {'contractType': 'PERPETUAL'},
                'active': True,
                'volume': 1000000.0
            },
            'BTC/USDT': {
                'symbol': 'BTC/USDT',
                'quote': 'USDT',
                'info': {'contractType': 'PERPETUAL'},
                'active': True,
                'volume': 500000.0
            },
            'ETH/USDT:USDT': {
                'symbol': 'ETH/USDT:USDT',
                'quote': 'USDT',
                'info': {'contractType': 'PERPETUAL'},
                'active': True,
                'volume': 300000.0
            },
            'BTC/USDT:PERPETUAL': {
                'symbol': 'BTC/USDT:PERPETUAL',
                'quote': 'USDT',
                'info': {'contractType': 'PERPETUAL', 'active': False},
                'active': False
            }
        }
        
        syms = client.fetch_usdt_perp_symbols(top_n=2)
        self.assertEqual(len(syms), 2)
        self.assertIn('BTC/USDT:USDT', syms)
        self.assertIn('BTC/USDT', syms)

    def test_fetch_top50_last_year_1h_history_ge_1y(self):
        # 测试获取历史数据
        client = BinancePerpetualContractUSDTClient()
        # 为避免文件冲突，创建临时测试目录
        test_dir = os.path.join(self.test_data_dir, 'top50_temp')
        os.makedirs(test_dir, exist_ok=True)
        
        try:
            # 模拟依赖方法避免真实API调用
            with patch.object(client, 'fetch_usdt_perp_symbols', return_value=['BTC/USDT:USDT', 'ETH/USDT:USDT']):
                with patch.object(client, 'top_by_quote_volume', return_value=['BTC/USDT:USDT']):
                    with patch.object(client.binance, 'fetch_ohlcv', side_effect=[
                        # 创建100小时的模拟数据(足够启动但不填满1年)
                        [[1609459200000 + i * 3600000, 30000, 31000, 29000, 30500, 100] 
                         for i in range(100)],
                        # 第二次调用返回空列表以终止循环
                        []
                    ]):
                        with patch.object(client, 'earliest_kline_time', return_value=datetime(2023, 1, 1)):
                            result = client.fetch_top50_last_year_1h_history_ge_1y(out_dir=test_dir)
                            # 验证结果非空
                            self.assertTrue(len(result) > 0, "Expected non-empty result")
                            # 验证创建的文件数量（应至少为1）
                            created_files = [f for f in os.listdir(test_dir) if f.endswith('.csv')]
                            self.assertGreaterEqual(len(created_files), 1)
                            self.assertTrue(any(f.startswith('BTC_USDT') for f in created_files), 
                                          "Expected BTC_USDT.csv in test directory")
        finally:
            # 清理测试数据
            if os.path.exists(test_dir):
                for f in os.listdir(test_dir):
                    try:
                        os.remove(os.path.join(test_dir, f))
                    except OSError:
                        pass
                try:
                    os.rmdir(test_dir)
                except OSError:
                    pass

    def test_pad_to_hour_grid(self):
        # 测试数据补全
        df = pd.DataFrame({
            'DateTime': pd.date_range(start='2023-01-01', periods=5, freq='h'),
            'open': [1, 2, 3, 4, 5],
            'high': [1, 2, 3, 4, 5],
            'low': [1, 2, 3, 4, 5],
            'close': [1, 2, 3, 4, 5],
            'volume': [1, 2, 3, 4, 5]
        })
        
        padded_df = pad_to_hour_grid(df, start_dt=datetime(2023, 1, 1), end_dt=datetime(2023, 1, 3))
        self.assertEqual(len(padded_df), 49)  # 包含开始和结束时间点
        self.assertEqual(padded_df.columns.tolist(), ['DateTime', 'open', 'high', 'low', 'close', 'volume'])

if __name__ == '__main__':
    unittest.main()
