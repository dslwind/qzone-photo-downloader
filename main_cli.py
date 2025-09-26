"""
QQ空间相册照片下载器 - 命令行版本

该脚本可以自动登录QQ空间并下载指定用户的所有可访问相册照片。
支持多线程下载、断点续传、排除特定相册等功能。

使用方法:
1. 在config.json中配置QQ账号信息和下载参数
2. 运行脚本: python main_cli.py
3. 在弹出的浏览器窗口中登录QQ空间
4. 脚本将自动开始下载照片

注意事项:
- 需要安装Chrome浏览器
- 需要确保网络连接正常
- 大量照片下载可能需要较长时间
"""

import sys

from config.config_manager import USER_CONFIG
from core.qzone_manager import QzonePhotoManager


def main():
    """脚本主入口点。"""
    # --- 用户配置 ---
    main_user_qq = USER_CONFIG["main_user_qq"]
    main_user_pass = USER_CONFIG["main_user_pass"]
    dest_users_qq = USER_CONFIG["dest_users_qq"]

    if main_user_qq == "123456":  # 检查是否使用了默认的QQ号
        print("请在配置文件中更新 'main_user_qq' 和 'dest_users_qq'。")
        return

    try:
        qzone_manager = QzonePhotoManager(main_user_qq, main_user_pass)
    except Exception as e:
        print(f"初始化 QzonePhotoManager 失败: {e}")
        return

    print("登录过程已完成 (或已启动手动登录)。")

    for target_qq in dest_users_qq:
        target_qq_str = str(target_qq)  # 确保是字符串
        print(f"\n--- 正在处理用户: {target_qq_str} ---")
        try:
            from core.downloader import download_all_photos_for_user
            download_all_photos_for_user(qzone_manager, target_qq_str)
        except Exception as e:
            print(f"处理用户 {target_qq_str} 时发生意外错误: {e}")
            import traceback
            traceback.print_exc()  # 打印堆栈跟踪以进行调试
        print(f"--- 完成处理用户: {target_qq_str} ---")

    print("\n所有指定用户处理完毕。")


if __name__ == "__main__":
    main()