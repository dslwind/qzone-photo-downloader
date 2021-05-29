# QQ 空间照片下载器

2021.05.29 更新说明

这个脚本写于 2018 年，当初是为了方便从好友的 QQ 空间相册下载原图，没想到陆陆续续收到了二十多个 Star，现在测试该方法已经失效了。

建议使用其他 GitHub 项目（例如[QQ 空间导出助手](https://github.com/ShunCai/QZoneExport)）代替，或者自行研究 QQ 空间 API。

---分割线---

以下是原说明：

本脚本在`python3.6`下测试通过

## 安装依赖

- selenium

  `pip install selenium`

- ChromeDriver

  需要 webdriver 配合 chrome 浏览器登录，获取 cookie

  chromedriver 下载地址：<https://sites.google.com/a/chromium.org/chromedriver/downloads>

  下载解压后，将 chromedriver.exe 放在脚本所在目录 或加入系统环境变量

## 使用说明

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
