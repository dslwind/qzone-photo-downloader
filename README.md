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

- [chromedriver](https://sites.google.com/a/chromium.org/chromedriver/downloads) : 

  下载对应系统的 chromedriver，比如 windows上的 chromedriver.exe 简单的话就放到项目根目录就可以了

- 修改 QQ 号

  打开`downloader.py`，定位到以下代码（文件末尾）

  ```python
  def entry():
      # 你的 QQ和密码，QQ号必须写，密码可以省略，然后使用网页快速登录功能
      main_user = 123456
      main_pass = ''

      # 要处理的目标 QQ 号，此处可填入多个QQ号，中间用逗号隔开
      dest_users = [123456, ]
      # 另外抽象出来的参数配置 app_config，可以按需修改，代码里面有详细注释可参考
  ```

## 更新说明
- 2022.06.09 更新
  
  1. 抽象了一些默认配置可以在入口处自定义
  2. API 返回的数据结构已经变更了，这个已经适配到最新的数据结构，可以正常下载了
  3. 根据抽象的配置，改变了一些 API 调式信息的输出控制

  本版实际使用反馈：重试下载经常会出现，目前我是并发数量改小、超时时间增大，挂着慢慢下载；
  另外原本程序实现了跳过本地已经下载过的照片，所以如果发现有下载失败的照片，可以等待每一次任务执行完成之后，将完全下载好的相册放到排除配置中，然后再继续尝试下载，就有很大概率将之前下载失败的都下载下来

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
