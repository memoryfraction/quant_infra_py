# read_env.py

import os
from dotenv import dotenv_values, find_dotenv
from typing import Dict, Any

def read_and_print_config(env_file_name: str = ".env"):
    """
    查找、读取 .env 文件的内容，并格式化打印出来。
    """
    # 1. 查找 .env 文件路径
    try:
        # find_dotenv 会从当前目录开始向上层目录搜索文件
        env_path = find_dotenv(env_file_name, usecwd=True, raise_error_if_not_found=True)
    except IOError:
        print(f"错误：未找到文件 {env_file_name}。请确保它存在于当前目录或上级目录中。")
        return

    print(f"--- 成功找到 .env 文件：{env_path} ---")

    # 2. 读取文件内容到字典
    # dotenv_values 不会影响 os.environ，只返回一个字典
    config_dict: Dict[str, Any] = dotenv_values(env_path)

    # 3. 格式化打印结果
    print("\n--- .env 文件解析结果 ---")

    if not config_dict:
        print("警告：.env 文件为空或只包含注释。")
        return
    returnvalue = None
    for key, value in config_dict.items():
        # 针对您提供的 OPENAI_API_KEY 格式化打印
        if key == "OPENAI_API_KEY" and value:
            # 打印您想要的部分，并隐藏机密信息的中间部分
            safe_value = f"{value[:5]}***{value[-4:]}"
            returnvalue = value
            print(f"OPENAI_API_KEY: {safe_value}")
        else:
            print(f"{key}: {value}")
    return returnvalue



if __name__ == "__main__":
    read_and_print_config()