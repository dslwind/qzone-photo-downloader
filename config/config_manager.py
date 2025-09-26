"""
配置管理模块
"""

import errno
import json
import os
import re
import sys

# --- 配置信息 ---
CONFIG_FILE = "config.json"
CONFIG = {}


def load_config():
    """从配置文件加载配置。
    
    从指定的配置文件中读取JSON格式的配置信息。
    如果文件不存在或格式错误，将输出错误信息并退出程序。
    
    Raises:
        FileNotFoundError: 当配置文件不存在时
        json.JSONDecodeError: 当配置文件格式错误时
        Exception: 当发生其他意外错误时
    """
    global CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
        print(f"成功从 {CONFIG_FILE} 加载配置。")
    except FileNotFoundError:
        print(f"错误: 配置文件 {CONFIG_FILE} 未找到。请确保它存在。")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"错误: 解析配置文件 {CONFIG_FILE} 失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"加载配置文件时发生意外错误: {e}")
        sys.exit(1)


# 在脚本开始时加载配置
load_config()

# 请在json文件中修改配置
APP_CONFIG = {
    "max_workers": CONFIG.get("max_workers", 10),       # 并行下载线程数量
    "timeout_init": CONFIG.get("timeout_init", 30),     # 请求初始超时时间 (秒)
    "max_attempts": CONFIG.get("max_attempts", 3),      # 下载失败后最大重试次数
    "is_api_debug": CONFIG.get("is_api_debug", True),   # 是否打印 API 请求 URL 和响应内容
    "exclude_albums": CONFIG.get("exclude_albums", []), # 需要排除、不下载的相册名称列表
    "download_path": CONFIG.get("download_path", "qzone_photo"),    # 下载路径（相对于脚本位置）
}

USER_CONFIG = {
    "main_user_qq": CONFIG.get("main_user_qq", "123456"),       # 替换为您的 QQ 号码
    "main_user_pass": CONFIG.get("main_user_pass", ""),         # 建议留空以进行手动登录
    "dest_users_qq": CONFIG.get("dest_users_qq", ["123456",]),   # 替换为目标 QQ 号码（字符串列表）
}


def get_script_directory() -> str:
    """获取项目根目录的绝对路径。
    
    Returns:
        str: 项目根目录的绝对路径
    """
    # 获取当前文件所在目录
    current_dir = os.path.dirname(os.path.realpath(__file__))
    # 返回上级目录（项目根目录）
    return os.path.dirname(current_dir)


def is_path_valid(pathname: str) -> bool:
    """
    检查给定路径名在当前操作系统中是否（可能）有效。
    主要依赖 os.path.normpath 和一次 os.lstat 调用。
    它旨在捕获明显的无效路径，例如包含空字符、名称过长或无效字符（由 lstat 检测）。

    注意：如果路径的某个部分不存在（导致 ENOENT），此函数可能无法捕获
    后续路径组件中的无效名称，因为 os.lstat 会因 ENOENT 而首先失败。
    
    Args:
        pathname (str): 需要检查的路径名
        
    Returns:
        bool: 如果路径有效返回True，否则返回False
    """
    # 1. 初始类型和空值检查
    if not isinstance(pathname, str) or not pathname:
        return False

    # 2. 检查空字符（在路径组件中通常无效）
    if "\0" in pathname:
        return False

    # 3. 尝试规范化路径
    try:
        normalized_pathname = os.path.normpath(pathname)
        # 如果规范化后路径为空字符串（例如，原始路径本身就是问题，或 normpath 的罕见行为），则视为无效。
        # 初始的 `if not pathname:` 已处理输入为空字符串的情况。
        # 此处检查确保 normpath 返回的是一个非空字符串。
        if not normalized_pathname:
            return False
    except (
        ValueError
    ):  # 例如，Windows 上的 normpath 可能会对包含嵌入空字符的路径引发 ValueError
        return False
    except Exception:  # normpath 期间的其他特定于操作系统的错误（不太可能，但作为防护）
        return False

    # 4. 尝试对整个规范化路径执行 lstat
    try:
        os.lstat(normalized_pathname)
        return True  # 如果 lstat 成功，路径有效
    except OSError as exc:
        # 如果文件或路径组件不存在 (ENOENT)，我们假设名称本身仍然可能是有效的。
        # 函数的目的是检查名称的有效性，而不是路径的存在性。
        if exc.errno == errno.ENOENT:
            return True
        # 以下错误明确表示名称/路径本身存在问题
        elif (
            hasattr(exc, "winerror") and exc.winerror == 123
        ):  # ERROR_INVALID_NAME (Windows)
            return False
        elif exc.errno in [errno.ENAMETOOLONG, errno.ELOOP]:  # 名称过长或符号链接循环
            return False
        elif exc.errno == errno.EINVAL:  # 无效参数
            # 特殊处理 Windows 上的驱动器号（例如 "C:"）。
            # os.lstat("C:") 在 Windows 上会引发 EINVAL，但我们认为 "C:" 是一个有效的路径前缀。
            drive, tail = os.path.splitdrive(normalized_pathname)
            if os.name == "nt" and drive == normalized_pathname and not tail:
                # 这确实是一个驱动器号，例如 "C:" (normalized_pathname == "C:")
                return True
            else:
                # 其他 EINVAL 情况（或非 Windows 系统上的 EINVAL）表示路径无效。
                return False
        else:
            # 其他 OSError（例如 EACCES - 权限问题）不一定意味着名称无效，
            # 但为了简化和安全起见，我们将它们视为路径无效。
            return False
    except Exception:  # 捕获 lstat 期间的任何其他非 OSError 异常（不太可能）
        return False


def sanitize_filename_component(name_component: str) -> str:
    """安全处理文件名组件，替换所有非法字符为下划线

    参数:
        name_component: 需要处理的原始文件名组件

    返回:
        处理后的安全字符串
        
    Args:
        name_component (str): 需要处理的原始文件名组件
        
    Returns:
        str: 处理后的安全字符串，所有非法字符已被替换为下划线
    """
    if not isinstance(name_component, str):
        raise TypeError("输入必须是字符串类型")

    # 定义正则表达式模式，匹配各种操作系统中的非法文件名字符
    illegal_chars = r'[\/\\:*?"<>|\0]'  # 包含路径分隔符和其他特殊字符

    # 使用单个正则替换所有非法字符
    return re.sub(illegal_chars, "_", name_component)


def get_save_directory(user_qq: str) -> str:
    """确定给定用户的照片保存目录
    
    根据配置的下载路径和用户QQ号，构建照片保存的完整目录路径。
    
    Args:
        user_qq (str): 用户的QQ号
        
    Returns:
        str: 照片保存的完整目录路径
    """
    download_path = APP_CONFIG.get("download_path", "downloads")
    return os.path.join(get_script_directory(), download_path, str(user_qq))