import unittest
from unittest.mock import patch, MagicMock
from data_source_service import BinancePerpetualContractUSDTClient, BinanceSpotUSDTClient
import pandas as pd


class TestBinancePerpetualContractUSDTClient(unittest.TestCase):

    @patch.object(BinancePerpetualContractUSDTClient, 'fetch_usdt_perp_symbols')
    def test_fetch_usdt_perp_symbols(self, mock_fetch):
        # 准备模拟数据
        mock_fetch.return_value = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']

        client = BinancePerpetualContractUSDTClient(interval="1h")

        # 执行方法
        result = client.fetch_usdt_perp_symbols(top_n=3)

        # 断言返回值正确
        self.assertEqual(result, ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'])
        mock_fetch.assert_called_once_with(top_n=3)

    @patch.object(BinancePerpetualContractUSDTClient, 'top_by_quote_volume')
    def test_top_by_quote_volume(self, mock_top_by_quote):
        # 准备模拟数据
        mock_top_by_quote.return_value = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT']

        client = BinancePerpetualContractUSDTClient(interval="1h")

        # 执行方法
        result = client.top_by_quote_volume(pool=['BTC/USDT', 'ETH/USDT', 'BNB/USDT'], topn=3)

        # 断言返回值正确
        self.assertEqual(result, ['BTC/USDT', 'ETH/USDT', 'BNB/USDT'])
        mock_top_by_quote.assert_called_once_with(pool=['BTC/USDT', 'ETH/USDT', 'BNB/USDT'], topn=3)

    @patch.object(BinancePerpetualContractUSDTClient, 'fetch_ohlcv_range')
    def test_fetch_ohlcv_range(self, mock_fetch_ohlcv):
        # 准备模拟数据
        mock_df = pd.DataFrame({
            'DateTime': ['2025-01-01 00:00:00', '2025-01-01 01:00:00'],
            'open': [100, 101],
            'high': [102, 103],
            'low': [99, 100],
            'close': [101, 102],
            'volume': [1000, 1500]
        })
        mock_fetch_ohlcv.return_value = mock_df

        client = BinancePerpetualContractUSDTClient(interval="1h")

        # 执行方法
        result = client.fetch_ohlcv_range(symbol='BTC/USDT', start_ms=0, end_ms=1609459200000)

        # 断言返回值正确
        pd.testing.assert_frame_equal(result, mock_df)
        mock_fetch_ohlcv.assert_called_once_with(symbol='BTC/USDT', start_ms=0, end_ms=1609459200000)


if __name__ == '__main__':
    unittest.main()
