"""
QQ空间相册照片下载器 - 主入口点

该脚本是程序的主入口点，支持命令行和GUI两种模式。

使用方法:
1. 命令行模式: python main.py cli
2. GUI模式: python main.py gui (默认)

或者直接运行:
1. 命令行版本: python main_cli.py
2. GUI版本: python main_gui.py

注意事项:
- 需要安装Chrome浏览器
- 需要确保网络连接正常
- 大量照片下载可能需要较长时间
"""

import sys


def main():
    """主入口函数"""
    # 检查命令行参数
    if len(sys.argv) > 1 and sys.argv[1].lower() == 'cli':
        # 运行命令行版本
        try:
            from main_cli import main as cli_main
            cli_main()
        except ImportError as e:
            print(f"无法导入命令行模块: {e}")
            sys.exit(1)
    else:
        # 运行GUI版本
        try:
            from main_gui import main as gui_main
            gui_main()
        except ImportError as e:
            print(f"无法导入GUI模块: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()