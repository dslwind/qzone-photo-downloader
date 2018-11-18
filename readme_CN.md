# QQ空间照片下载器

本脚本在`python3.6`下测试通过
## 安装依赖

- selenium

    ```pip install selenium```
- ChromeDriver

    需要webdriver配合chrome浏览器登录，获取cookie
    
    chromedriver下载地址：https://sites.google.com/a/chromium.org/chromedriver/downloads

    下载解压后，将chromedriver.exe放在脚本所在目录 或加入系统环境变量

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
按程序注释修改你的QQ号和目标QQ号（可以是好友的），然后保存运行即可开始下载。