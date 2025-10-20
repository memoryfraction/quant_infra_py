# test_config.py
import unittest
import os
from unittest.mock import patch, MagicMock
from typing import Dict, Any

# 引入 dotenv_values 用于读取真实文件
from dotenv import dotenv_values

# 假设您的项目结构允许这样导入，请根据实际路径调整
# 示例： from src.config_loader import get_config, ConfigError
from config_loader import get_config, ConfigError

# 临时 .env 文件的内容 (包含中文注释，但密钥是 ASCII 字符)
REAL_ENV_CONTENT = """
# ============== 外部服务 API 密钥 ==============
# 第三方 API 密钥
OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
DEBUG="True"
SERVER_PORT="9999"
"""


class TestConfigLoading(unittest.TestCase):
    """单元测试 config_loader.py 中的配置逻辑。"""

    def setUp(self):
        """测试前的准备工作：设置预期的默认值，并创建临时的 .env 文件。"""
        self.MOCK_API_KEY = "sk-mock-key-98765"
        self.DEFAULT_DEBUG = False
        self.DEFAULT_PORT = 8080
        self.TEMP_ENV_FILE = ".temp_test_config.env"

        # 核心修复：创建临时文件时，明确指定编码为 'utf-8'
        with open(self.TEMP_ENV_FILE, "w", encoding='utf-8') as f:
            f.write(REAL_ENV_CONTENT)

    def tearDown(self):
        """测试后的清理工作：删除创建的临时文件。"""
        if os.path.exists(self.TEMP_ENV_FILE):
            os.remove(self.TEMP_ENV_FILE)

    # ----------------------------------------------------------------------
    # 0. 真实读取测试：读取并打印实际的 .env 文件内容
    # ----------------------------------------------------------------------
    def test_read_and_print_real_env_content(self):
        """直接读取临时 .env 文件，并打印其中的内容。"""

        # 直接读取真实内容
        real_config_data: Dict[str, Any] = dotenv_values(self.TEMP_ENV_FILE)

        print("\n--- Running 0: 实际 .env 文件内容读取与打印 ---")

        key_to_print = "OPENAI_API_KEY"

        if key_to_print in real_config_data:
            value = real_config_data[key_to_print]
            safe_value = f"{value[:5]}***{value[-4:]}"
            print(f"键: {key_to_print}, 值为: \"{safe_value}\" (已从真实文件读取)")

        print(f"同时加载的其他配置：{real_config_data}")
        print("PASS: 真实内容读取成功并打印。")
        self.assertIn(key_to_print, real_config_data)

    # ----------------------------------------------------------------------
    # 1. 模拟测试：密钥存在 (使用 Mock 确保隔离性)
    # ----------------------------------------------------------------------
    @patch('config_loader.dotenv_values')
    def test_api_key_is_loaded_when_present(self, mock_dotenv_values: MagicMock):
        """测试当 OPENAI_API_KEY 存在时，配置加载器是否能正确处理。"""

        mock_dotenv_values.return_value = {
            "OPENAI_API_KEY": self.MOCK_API_KEY,
            "DEBUG": "False"
        }

        print("\n--- Running 1: 模拟测试：密钥存在 ---")
        config_data = get_config()

        print(f"PASS: 模拟加载的密钥：{config_data['OPENAI_API_KEY']}")

        self.assertEqual(config_data["OPENAI_API_KEY"], self.MOCK_API_KEY)
        self.assertFalse(config_data["DEBUG"])
        print("PASS: 模拟密钥正确加载，且类型转换正确。")

    # ----------------------------------------------------------------------
    # 2. 模拟测试：密钥缺失 (验证异常抛出)
    # ----------------------------------------------------------------------
    @patch('config_loader.dotenv_values')
    def test_api_key_is_missing_raises_error(self, mock_dotenv_values: MagicMock):
        """测试当 OPENAI_API_KEY 缺失时，get_config 是否抛出 ConfigError。"""

        mock_dotenv_values.return_value = {}

        print("\n--- Running 2: 模拟测试：密钥缺失 (期望抛错) ---")

        with self.assertRaises(ConfigError) as cm:
            get_config()

        error_message = str(cm.exception)
        print(f"PASS: 捕获到错误信息：{error_message[:50]}...")
        self.assertIn("OPENAI_API_KEY 未设置", error_message)
        print("PASS: 密钥缺失时抛出 ConfigError 异常。")


if __name__ == '__main__':
    unittest.main()