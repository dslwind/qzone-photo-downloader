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

- [chromedriver](https://googlechromelabs.github.io/chrome-for-testing/) : 

  下载对应系统的 chromedriver，比如 windows上的 chromedriver.exe 简单的话就放到项目根目录就可以了

- 修改 QQ 号

  打开`config.json`，修改以下配置（更多配置说明请参考`main.py`的注释）：

  ```json
  "main_user_qq": "123456",
  "dest_users_qq": ["123456"],
  ```
  
  将`main_user_qq`修改为您的QQ号码，`dest_users_qq`修改为好友的QQ号码，多个号码用`,`分隔，注意`]`前不要有`,`，例如`["123", "456"]`。

## 更新说明
- 2025.06.06 更新
  将配置信息移到`config.json`文件中，不再修改`.py`文件

- 2025.05.14 更新
  1. 移除Python 2.x支持，简化为单文件，改用`f-string`格式化输出调试信息
  2. 更新相册列表API
  3. 通过文件开头的`USER_CONFIG`配置QQ号，不再在`main`函数中配置

- 2022.06.09 更新
  
  1. 抽象了一些默认配置可以在入口处自定义
  2. API 返回的数据结构已经变更了，这个已经适配到最新的数据结构，可以正常下载了
  3. 根据抽象的配置，改变了一些 API 调式信息的输出控制
  4. 修复了最多只能下载 500 张照片的问题，现在可以全部下载
  5. 新增视频缩略图标识：由于照片是有序的（接口响应顺序），本软件无法下载视频，可以根据有顺序的视频缩略图人工去定位下载

  本版实际使用反馈：重试下载经常会出现，目前我是并发数量改小、超时时间增大，挂着慢慢下载；
  另外原本程序实现了跳过本地已经下载过的照片，所以如果发现有下载失败的照片，可以等待每一次任务执行完成之后，将完全下载好的相册放到排除配置中，然后再继续尝试下载，就有很大概率将之前下载失败的都下载下来

- 2021.09.28 更新

  已更新代码，目前已经能够导出相册，欢迎下载使用。

- 2021.09.16 更新说明

  已经通过 Chrome 开发者工具获得新的相册列表和图片列表，过几天更新代码

- 2021.05.29 更新说明

  这个脚本写于 2018 年，当初是为了方便从好友的 QQ 空间相册下载原图，没想到陆陆续续收到了二十多个 Star，现在测试该方法已经失效了。

  推荐使用其他 GitHub 项目（例如[QQzoneExporter](https://github.com/wwwpf/QzoneExporter)）代替。


## 支持一下

  如果你觉得这个脚本对您有用，可以打赏我以表支持。

  <img src="https://cdn.jsdelivr.net/gh/dslwind/CDN/images/mm_reward_qrcode.png" width=300/>
