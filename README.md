# QQ 空间相册照片下载器

这是一个可以自动登录 QQ 空间并下载指定用户的所有可访问相册照片的工具。支持多线程下载、断点续传、排除特定相册等功能。

## 项目结构

```
qzone-photo-downloader/
├── config/              # 配置管理模块
│   ├── __init__.py
│   └── config_manager.py
├── core/                # 核心逻辑模块
│   ├── __init__.py
│   ├── qzone_manager.py  # QQ空间管理器
│   └── downloader.py     # 下载器
├── gui/                 # GUI相关模块
│   ├── __init__.py
│   ├── main_window.py    # GUI主窗口
│   ├── download_worker.py # 下载工作线程
│   └── gui_logger.py     # GUI日志处理器
├── utils/               # 工具函数模块
│   ├── __init__.py
│   └── helpers.py        # 辅助函数
├── main.py              # 程序主入口点
├── main_cli.py          # 命令行版本主程序
├── main_gui.py          # GUI版本主程序
├── gui.py               # GUI兼容层（向后兼容）
├── config.json          # 配置文件
├── requirements.txt     # 命令行版本依赖
└── requirements-gui.txt # GUI版本依赖
```

## 功能特点

- 支持多线程下载，提高下载速度
- 支持断点续传，避免重复下载
- 可以排除特定相册不下载
- 支持命令行和图形界面两种使用方式
- 自动处理文件名中的非法字符
- 支持 Cookie 复用，避免频繁扫码登录

## 安装依赖

根据使用方式选择安装依赖：

### 命令行版本

```bash
pip install -r requirements.txt
```

### GUI 版本

```bash
pip install -r requirements-gui.txt
```

## 使用方法

### 1. 配置文件设置

在`config.json`中配置 QQ 账号信息和下载参数：

```json
{
  "main_user_qq": "123456", // 替换为您的QQ号
  "main_user_pass": "", // QQ密码（建议留空以进行手动登录）
  "dest_users_qq": ["123456"], // 替换为目标QQ号
  "max_workers": 10, // 并行下载线程数量
  "timeout_init": 30, // 请求初始超时时间(秒)
  "max_attempts": 3, // 下载失败后最大重试次数
  "is_api_debug": false, // 是否打印API请求URL和响应内容
  "exclude_albums": [], // 需要排除、不下载的相册名称列表
  "download_path": "qzone_photo" // 下载路径（相对于脚本位置）
}
```

### 2. 运行程序

#### 命令行模式

```bash
python main.py cli
# 或者
python main_cli.py
```

#### GUI 模式

```bash
python main.py
# 或者
python main.py gui
# 或者
python main_gui.py
```

### 3. 使用流程

1. 运行程序后，会自动打开 Chrome 浏览器窗口
2. 在浏览器中登录您的 QQ 空间账号
3. 登录成功后，程序将自动开始下载照片
4. 照片将保存在`qzone_photo`目录下，按 QQ 号和相册名分类存储

## 注意事项

- 需要安装 Chrome 浏览器
- 需要确保网络连接正常
- 大量照片下载可能需要较长时间
- 请遵守 QQ 空间的使用条款，不要过于频繁地请求数据
- 如果遇到验证码，需要手动处理

## 常见问题

### 1. Chrome 浏览器版本不兼容

如果遇到 Chrome 浏览器版本不兼容的问题，请更新 Chrome 浏览器到最新版本，或者手动下载对应版本的 ChromeDriver。

### 2. 下载速度慢

可以适当增加`max_workers`参数的值来提高并发下载线程数，但不要设置过高以免被限制访问。

### 3. 部分照片下载失败

可以重新运行程序，利用断点续传功能继续下载未完成的照片。

## 技术说明

### 模块化设计

项目采用模块化设计，各个功能模块职责分明：

- `config`模块负责配置管理
- `core`模块负责核心逻辑，包括 QQ 空间 API 访问和数据处理
- `gui`模块负责图形界面相关功能
- `utils`模块提供通用的工具函数

### Cookie 复用机制

为了提升用户体验，避免频繁扫码登录，程序实现了 Cookie 复用机制：

1. 首次运行时，通过扫码登录获取 Cookie
2. 后续运行时，先检查已保存的 Cookie 是否有效
3. 如果 Cookie 有效，则直接使用，无需重新扫码登录
4. 如果 Cookie 失效，则重新打开浏览器获取新的 Cookie

## 贡献

欢迎提交 Issue 和 Pull Request 来改进这个项目。

## 许可证

本项目采用 MIT 许可证。
