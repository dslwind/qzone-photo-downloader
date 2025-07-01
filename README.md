# QQ 空间相册下载工具

一款用于下载 QQ 空间相册照片的工具，支持命令行和图形界面两种使用方式。

## ✨ 功能特性

- 双模式运行：GUI 界面和命令行两种使用方式
- 配置分离：通过`config.json`管理 QQ 账号和下载配置
- 自动更新：集成`webdriver_manager`自动管理浏览器驱动
- 断点续传：支持跳过已下载照片
- 多账号支持：可同时下载多个好友的相册
- 多线程：支持多线程下载提高效率
- 日志记录：详细的下载日志和错误信息
- 追踪下载进度：实时显示当前下载进度

## 🚀 快速开始

### 前置要求

- Python 3.7+
- Chrome 浏览器

### 安装方法

#### 方法一：直接运行(无需 Python 环境)

1. 从[Releases 页面](https://github.com/dslwind/qzone-photo-downloader/releases)下载打包好的 exe 文件
2. 解压后运行`QzonePhotoDownloader.exe`

#### 方法二：源码运行

```bash
git clone https://github.com/dslwind/qzone-photo-downloader.git
cd qzone-photo-downloader

# 创建虚拟环境(可选)
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate.bat  # Windows

# 安装依赖
pip install -r requirements.txt  # 基础版本
pip install -r requirements-gui.txt  # GUI版本额外依赖
```

### 配置说明

编辑 `config.json` 文件:

```json
{
  "main_user_qq": "你的QQ号",
  "dest_users_qq": ["目标QQ号1", "目标QQ号2"]
}
```

将`main_user_qq`修改为您的 QQ 号码，`dest_users_qq`修改为好友的 QQ 号码。

> 注意: 多个 QQ 号之间用逗号分隔，最后一个 QQ 号后不要加逗号，例如：`["123", "456"]`

### 使用方法

#### 命令行模式

```bash
python main.py
```

#### 图形界面模式

```bash
python gui.py
```

#### 打包为独立应用

```bash
pyinstaller --name "QzonePhotoDownloader" --windowed --collect-submodules PyQt6 --hidden-import PyQt6.Qt gui.py
```

## 📦 项目结构

```
qzone-photo-downloader/
├── config.json          # 配置文件
├── gui.py               # PyQt6 GUI实现
├── main.py              # 核心逻辑
├── requirements.txt     # 基础依赖
└── requirements-gui.txt # GUI额外依赖
```

## ⚙️ 高级配置

可在 `config.json` 中调整以下参数:

- `max_workers`: 并发下载线程数 (默认: 5)
- `timeout_init`: 初始化超时时间(秒) (默认: 30)
- `is_api_debug`: 是否开启 API 调试 (默认: false)
- `exclude_albums`: 要排除的相册名称列表

## ❓ 常见问题

1. 下载过程中出现错误怎么办？
   - 尝试减少并发数 (`max_workers`)
   - 增加超时时间 (`timeout_init`)
   - 分批下载相册
1. 如何只下载特定相册？
   在 `exclude_albums` 中添加不想下载的相册名称
1. 支持视频下载吗？
   不支持直接下载视频，但会保留视频缩略图作为标记

## 📜 版本历史

已更新代码，目前已经能够导出相册，欢迎下载使用。
| 版本 | 日期 | 更新内容 |
|------|------|----------|
| v2.0 | 2025.06.20 | 新增 GUI 界面，自动管理浏览器驱动 |
| v1.5 | 2025.06.06 | 迁移配置到 config.json 文件 |
| v1.0 | 2025.05.14 | 移除 Python 2 支持，优化 API 接口 |

## 🤝 参与贡献

欢迎提交 Issue 或 Pull Request

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=dslwind/qzone-photo-downloader&type=Date)](https://www.star-history.com/#dslwind/qzone-photo-downloader&Date)
