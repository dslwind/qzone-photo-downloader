"""
QQ空间相册照片下载器 - 命令行入口

使用方法:
  1. 在 config.json 中配置 QQ 账号信息和下载参数
  2. 运行脚本: python main.py
  3. 在弹出的浏览器窗口中登录 QQ 空间
  4. 脚本将自动开始下载照片

注意事项:
  - 需要安装 Chrome 浏览器
  - 需要确保网络连接正常
  - 大量照片下载可能需要较长时间
"""

import logging
import sys
import traceback

from core import (
    APP_CONFIG,
    USER_CONFIG,
    QzonePhotoManager,
    load_config,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main() -> None:
    """脚本主入口点。"""
    load_config(exit_on_error=True)

    main_user_qq = USER_CONFIG["main_user_qq"]
    dest_users_qq = USER_CONFIG["dest_users_qq"]

    if main_user_qq == "123456":
        print("请在配置文件中更新 'main_user_qq' 和 'dest_users_qq'。")
        return

    try:
        qzone_manager = QzonePhotoManager(main_user_qq)
        qzone_manager._login_and_get_cookies()
    except Exception as e:
        print(f"初始化 QzonePhotoManager 失败: {e}")
        return

    print("登录过程已完成。")

    for target_qq in dest_users_qq:
        target_qq_str = str(target_qq)
        print(f"\n--- 正在处理用户: {target_qq_str} ---")
        try:
            qzone_manager.download_all_photos_for_user(target_qq_str)
        except Exception as e:
            print(f"处理用户 {target_qq_str} 时发生意外错误: {e}")
            traceback.print_exc()
        print(f"--- 完成处理用户: {target_qq_str} ---")

    print("\n所有指定用户处理完毕。")


if __name__ == "__main__":
    main()
