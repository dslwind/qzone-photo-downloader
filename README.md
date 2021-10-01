# QQ 空间照片下载器

## 使用方法

- 克隆

  ```shell
  git clone https://github.com/dslwind/qzone-photo-downloader.git
  cd qzone-photo-downloader
  ```

- 虚拟环境

  ```shell
  $ python3 -m venv venv
  $ source venv/bin/activate 或 > venv\Scripts\activate.bat
  $ pip install -r requirements.txt
  ```

- [chromedriver](https://sites.google.com/a/chromium.org/chromedriver/downloads)

- 修改 QQ 号

  打开`downloader.py`，定位到以下代码

  ```python
  def entry():
      # 你的 QQ和密码，QQ号必须写，密码可以省略，然后使用网页快速登录功能
      main_user = 123456
      main_pass = ''

      # 要处理的目标 QQ 号，此处可填入多个QQ号，中间用逗号隔开
      dest_users = [123456, ]
  ```

## 更新说明

- 2021.09.28 更新

  已更新代码，目前已经能够导出相册，欢迎下载使用。

- 2021.09.16 更新说明

  已经通过 Chrome 开发者工具获得新的相册列表和图片列表，过几天更新代码

- 2021.05.29 更新说明

  这个脚本写于 2018 年，当初是为了方便从好友的 QQ 空间相册下载原图，没想到陆陆续续收到了二十多个 Star，现在测试该方法已经失效了。

  推荐使用其他 GitHub 项目（例如[QQzoneExporter](https://github.com/wwwpf/QzoneExporter)）代替。

## 旧版说明：

本脚本在`python3.6`下测试通过

### 安装依赖

- selenium

  `pip install selenium`

- ChromeDriver

  需要 webdriver 配合 chrome 浏览器登录，获取 cookie

  chromedriver 下载地址：<https://sites.google.com/a/chromium.org/chromedriver/downloads>

  下载解压后，将 chromedriver.exe 放在脚本所在目录 或加入系统环境变量

### 使用说明

打开`downloader.py`，定位到以下代码

```python
def entry():
    # 你的 QQ和密码，QQ号必须写，密码可以省略，然后使用网页快速登录功能
    main_user = 123456
    main_pass = ''

    # 要处理的目标 QQ 号，此处可填入多个QQ号，中间用逗号隔开
    dest_users = [123456, ]
```

按程序注释修改你的 QQ 号和目标 QQ 号（可以是好友的），然后保存运行即可开始下载。
