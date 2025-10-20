# config_loader.py
import os
from typing import Dict, Any, Optional
from dotenv import dotenv_values


class ConfigError(Exception):
    """
    自定义配置错误异常。
    当关键配置项缺失或值无效时抛出，用于在应用启动阶段进行快速失败。
    """
    pass


def get_config(env_file: str = ".env") -> Dict[str, Any]:
    """
    从 .env 文件和系统环境变量中加载应用配置。

    优先级：系统环境变量 (os.environ) > .env 文件内容。
    执行类型转换和关键配置项检查。

    参数:
        env_file: 要加载的 .env 文件名。

    返回:
        一个包含所有应用配置的字典，配置值已转换为正确的 Python 类型。
    """

    # 1. 加载和合并环境变量
    # dotenv_values 只读取文件，不影响 os.environ
    env_vars = dotenv_values(env_file)
    # 将 os.environ 中的变量合并进来，并覆盖 .env 中的同名变量（优先级最高）
    config_data = {**env_vars, **os.environ}

    # 2. 集中处理、类型转换 和 缺失检查

    # --- 外部服务 API 密钥 (强制检查) ---
    openai_api_key: Optional[str] = config_data.get("OPENAI_API_KEY")

    # 强制检查：密钥必须设置且不能为空字符串
    if not openai_api_key:
        raise ConfigError("致命错误: 环境变量 OPENAI_API_KEY 未设置或为空。请检查 .env 文件或系统环境变量。")

    # --- 应用程序配置 (类型转换和默认值) ---

    # 布尔值转换 (默认值 'False')
    # 接受 'True', '1', 't' 等为 True
    debug_str = config_data.get("DEBUG", "False")
    is_debug: bool = debug_str.lower() in ('true', '1', 't')

    # 整数转换 (默认值 8080)
    port_str = config_data.get("SERVER_PORT", "8080")
    try:
        server_port: int = int(port_str)
    except ValueError:
        # 记录错误，并使用安全默认值
        print(f"警告：SERVER_PORT 配置值 '{port_str}' 无效，使用默认值 8080。")
        server_port = 8080

    # 3. 返回最终的配置字典
    return {
        "OPENAI_API_KEY": openai_api_key,
        "DEBUG": is_debug,
        "SERVER_PORT": server_port,
    }

# -------------------------------------------------------------------------
# !!! 关键修复 !!!
# 移除了 APP_CONFIG = get_config() 这一行，以避免在 Pytest 收集测试时失败。
# 应用程序应在入口点 (例如 main.py 或 __init__.py) 手动调用 get_config()
# 或使用一个懒加载函数来获取配置。
# -------------------------------------------------------------------------

# 示例：如果您需要一个全局对象，可以这样进行延迟加载 (Lazy Loading)
# APP_CONFIG = None

# def get_app_config():
#     """懒加载函数：在首次访问时才加载配置。"""
#     global APP_CONFIG
#     if APP_CONFIG is None:
#         APP_CONFIG = get_config()
#     return APP_CONFIG