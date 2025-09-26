"""
QQ空间管理器模块
"""

import random
import json
import requests
from collections import namedtuple
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from config.config_manager import APP_CONFIG, get_save_directory, sanitize_filename_component

# --- 命名元组 ---
# QQ空间相册对象，包含相册ID, 相册名, 照片数量
QzoneAlbum = namedtuple("QzoneAlbum", ["uid", "name", "count"])
# QQ空间照片对象，包含照片链接, 照片名, 所属相册名, 是否为视频
QzonePhoto = namedtuple("QzonePhoto", ["url", "name", "album_name", "is_video"])


class QzonePhotoManager:
    """管理 QQ 空间相册和照片的获取与下载。"""

    # 获取相册列表的API URL模板
    ALBUM_LIST_URL_TEMPLATE = (
        "https://user.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3?"
        "g_tk={gtk}&t={t}&hostUin={dest_user}&uin={user}"
        "&appid=4&inCharset=utf-8&outCharset=utf-8&source=qzone&plat=qzone&format=jsonp"
        "&notice=0&filter=1&handset=4&pageNumModeSort=40&pageNumModeClass=15&needUserInfo=1"
        "&idcNum=4&callbackFun=shine0&callback=shine0_Callback"
    )

    ALBUM_LIST_URL_WITH_PAGE_TEMPLATE = (
        "https://user.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/fcg_list_album_v3?"
        "g_tk={gtk}&t={t}&hostUin={dest_user}&uin={user}"
        "&appid=4&inCharset=utf-8&outCharset=utf-8&source=qzone&plat=qzone&format=jsonp"
        "&notice=0&filter=1&handset=4&pageNumModeSort=40&pageNumModeClass=15&needUserInfo=1"
        "&idcNum=4&callbackFun=shine{fn}&mode=2&sortOrder=2&pageStart={pageStart}&pageNum={pageNum}&callback=shine{fn}_Callback"
    )

    # 获取照片列表的API URL模板
    PHOTO_LIST_URL_TEMPLATE = (
        "https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"
        "cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=4&hostUin={dest_user}"
        "&topicId={album_id}&noTopic=0&uin={user}&pageStart={pageStart}&pageNum={pageNum}"
        "&skipCmtCount=0&singleurl=1&batchId=&notice=0&appid=4&inCharset=utf-8&outCharset=utf-8"
        "&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1&question=&answer="
        "&callbackFun=shine0&callback=shine0_Callback"
    )

    def __init__(self, user_qq: str, password: str = "", log_signal=None, is_stopped_func=None):
        """初始化QzonePhotoManager对象。
        
        Args:
            user_qq (str): 用户的QQ号
            password (str): 用户的QQ密码
            log_signal: 日志信号（用于GUI）
            is_stopped_func: 停止检查函数
        """
        self.user_qq = str(user_qq)
        self.password = password
        self.cookies = {}
        self.session = requests.Session()
        self.qzone_g_tk = ""
        self.log_signal = log_signal
        self.is_stopped_func = is_stopped_func if is_stopped_func is not None else (lambda: False)
        self.total_albums = 0
        if password:  # 只有在提供了密码时才自动登录
            self._login_and_get_cookies()

    def _emit_log(self, message: str):
        """
        如果信号可用，则向 GUI 发送日志消息。
        同时使用 logger 记录消息。
        """
        if self.log_signal:
            self.log_signal.emit(message)
        print(message)  # 在命令行模式下也打印日志

    def _login_and_get_cookies(self):
        """使用 Selenium 登录 QQ 空间以获取必要的 cookie。"""
        self._emit_log("尝试启动 Chrome 进行登录...")
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-blink-features")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--lang=zh-CN")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        
        try:
            driver_path = ChromeDriverManager().install()
            service = ChromeService(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {
                    "userAgent": driver.execute_script(
                        "return navigator.userAgent"
                    ).replace("Headless", "")
                },
            )
            driver.execute_cdp_cmd(
                "Page.removeScriptToEvaluateOnNewDocument", {"identifier": "1"}
            )
            driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {
                    "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                """
                },
            )
        except Exception as e:
            self._emit_log(f"启动 ChromeDriver 失败。请确保您的 Chrome 浏览器是最新的，或者手动下载并将其放入PATH。错误: {e}")
            self._emit_log(
                "如果问题仍然存在，您可以从以下地址手动下载 ChromeDriver: https://googlechromelabs.github.io/chrome-for-testing"
            )
            raise

        driver.get("https://user.qzone.qq.com")
        self._emit_log("请在浏览器窗口中登录 QQ 空间。脚本将在登录后继续...")

        LOGIN_TIMEOUT = 300

        try:
            wait = WebDriverWait(driver, LOGIN_TIMEOUT)
            logged_in = wait.until(
                EC.any_of(
                    EC.presence_of_element_located((By.ID, "QM_OwnerInfo_Icon")),
                    EC.presence_of_element_located((By.ID, "QZ_Toolbar_Container")),
                    EC.presence_of_element_located((By.ID, "QM_Mood_Poster_Container")),
                )
            )

            if not logged_in:
                raise TimeoutException("登录超时或无法确认登录状态")

        except TimeoutException:
            self._emit_log(f"错误: {LOGIN_TIMEOUT}秒内未检测到成功登录")
            self._emit_log("建议：1) 确保网络正常 2) 可能需要手动处理验证码")
            driver.quit()
            raise
        except Exception as e:
            self._emit_log(f"登录过程中发生意外错误: {e}")
            driver.quit()
            raise

        selenium_cookies = driver.get_cookies()
        if not selenium_cookies:
            self._emit_log("获取 cookie 失败。登录可能失败或 cookie 无法访问。")
            driver.quit()
            raise Exception("获取 cookie 失败")

        self.cookies = {c["name"]: c["value"] for c in selenium_cookies}

        for cookie_name, cookie_value in self.cookies.items():
            self.session.cookies.set(cookie_name, cookie_value)

        p_skey = self.cookies.get("p_skey") or self.cookies.get("skey")
        if not p_skey:
            self._emit_log("错误: 在 cookie 中未找到 'p_skey' 或 'skey'。无法计算 g_tk。")
            self._emit_log(f"可用的 cookies: {list(self.cookies.keys())}")
            driver.quit()
            raise Exception("无法计算 g_tk")

        self.qzone_g_tk = self._calculate_g_tk(p_skey)
        self._emit_log("成功获取 cookie 和 g_tk。")
        if APP_CONFIG["is_api_debug"]:
            self._emit_log(f"cookie: {self.cookies}")
            self._emit_log(f"g_tk: {self.qzone_g_tk}")

        driver.quit()

    def _calculate_g_tk(self, p_skey: str) -> int:
        """根据 p_skey 计算 g_tk。"""
        hash_val = 5381
        for char in p_skey:
            hash_val += (hash_val << 5) + ord(char)
        return hash_val & 0x7FFFFFFF

    def _access_qzone_api(self, url: str, timeout_seconds: int | None = None) -> dict:
        """访问 QQ 空间 API 端点并解析 JSONP 响应。"""
        if timeout_seconds is None:
            timeout_seconds = APP_CONFIG["timeout_init"]

        try:
            response = self.session.get(url, timeout=timeout_seconds)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._emit_log(f"API 请求失败，URL: {url}: {e}")
            return {}

        text_content = response.text
        if text_content.startswith("shine0_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("shine0_Callback(") : -2]
        elif text_content.startswith("_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("_Callback(") : -2]
        else:
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(
                    f"意外的 API 响应格式 (没有已知的 JSONP 包装器): {text_content[:200]}"
                )
            json_str = text_content

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            self._emit_log(f"JSON 解码失败，响应内容: {json_str[:200]}... 错误: {e}")
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(f"有问题的完整 JSON 字符串: {json_str}")
            return {}

    def _check_cookie_validity(self) -> bool:
        """
        检查当前cookie是否有效。
        通过尝试访问相册列表API来验证cookie有效性。
        """
        if not self.cookies or not self.qzone_g_tk:
            self._emit_log("Cookie或g_tk为空，无法验证有效性。")
            return False
            
        # 使用相册列表API来检查cookie有效性
        # 这里使用自己的QQ号作为目标用户来测试cookie是否有效
        check_url = self.ALBUM_LIST_URL_TEMPLATE.format(
            gtk=self.qzone_g_tk,
            t=random.random(),
            dest_user=self.user_qq,  # 使用自己的QQ号作为目标用户
            user=self.user_qq,
        )
        
        try:
            response = self.session.get(check_url, timeout=APP_CONFIG["timeout_init"])
            response.raise_for_status()
            
            # 检查响应内容是否为有效的JSONP格式且不包含错误
            text_content = response.text
            if ((text_content.startswith("shine0_Callback(") and text_content.endswith(");")) or
                (text_content.startswith("_Callback(") and text_content.endswith(");"))):
                # 尝试解析JSON内容
                if text_content.startswith("shine0_Callback("):
                    json_str = text_content[len("shine0_Callback(") : -2]
                else:
                    json_str = text_content[len("_Callback(") : -2]
                
                try:
                    data = json.loads(json_str)
                    # 检查返回码是否为0（成功）
                    if data.get("code", -1) == 0:
                        self._emit_log("Cookie验证成功，可以继续使用。")
                        return True
                    else:
                        self._emit_log(f"Cookie验证失败，API返回错误码: {data.get('code', '未知')}")
                        return False
                except json.JSONDecodeError:
                    self._emit_log("Cookie验证失败，无法解析API响应。")
                    return False
            else:
                self._emit_log("Cookie验证失败，API响应格式不正确。")
                return False
        except requests.exceptions.RequestException as e:
            self._emit_log(f"Cookie验证请求失败: {e}")
            return False
        except Exception as e:
            self._emit_log(f"Cookie验证过程中发生错误: {e}")
            return False

    def _set_cookies_and_gtk(self, cookies: dict, g_tk: str):
        """
        设置cookie和g_tk，用于复用已有的登录信息。
        
        Args:
            cookies (dict): cookie字典
            g_tk (str): g_tk值
        """
        self.cookies = cookies
        self.qzone_g_tk = g_tk
        
        # 更新会话中的cookie
        for cookie_name, cookie_value in self.cookies.items():
            self.session.cookies.set(cookie_name, cookie_value)
            
        self._emit_log("已设置cookie和g_tk。")

    def get_albums_by_page(self, dest_user_qq: str) -> list[QzoneAlbum]:
        """分页获取相册列表。"""
        pageStart = 0
        allAlbums = []
        while self.total_albums == 0 or pageStart < self.total_albums:
            albums = self.get_albums(dest_user_qq, pageStart)
            if len(albums) == 0:
                break
            pageStart += len(albums)
            allAlbums.extend(albums)
        return allAlbums

    def get_albums(self, dest_user_qq: str, pageStart: int = 0, pageNum: int = 32) -> list[QzoneAlbum]:
        """获取给定用户的相册列表。"""
        albums = []
        if pageStart == 0:
            url = self.ALBUM_LIST_URL_TEMPLATE.format(
                gtk=self.qzone_g_tk,
                t=random.random(),
                dest_user=dest_user_qq,
                user=self.user_qq,
            )
        else:
            url = self.ALBUM_LIST_URL_WITH_PAGE_TEMPLATE.format(
                gtk=self.qzone_g_tk,
                t=random.random(),
                dest_user=dest_user_qq,
                user=self.user_qq,
                pageStart=pageStart,
                pageNum=pageNum,
                fn=0
            )        
        if APP_CONFIG["is_api_debug"]:
            self._emit_log(f"正在从以下地址获取相册: {url}")

        data = self._access_qzone_api(url)
        if APP_CONFIG["is_api_debug"]:
            dump = json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
            self._emit_log(f"相册 API 响应数据: {dump}")

        if not data or not data.get("data"):
            return albums

        album_data = data["data"]
        if self.total_albums == 0:
            self.total_albums = album_data.get("albumsInUser", 0)
        if "albumListModeSort" in album_data:  # 普通视图
            album_list = album_data["albumListModeSort"]
        elif "albumListModeClass" in album_data:  # 列表视图
            album_list = [
                item
                for d in album_data["albumListModeClass"]
                for item in d.get("albumList", [])
            ]
        elif "albumList" in album_data:
            album_list = album_data["albumList"]
        else:
            album_list = []

        if album_list:
            for album in album_list:
                albums.append(
                    QzoneAlbum(
                        uid=album["id"],
                        name=album["name"],
                        count=album["total"],
                    )
                )
        # 兼容旧版API格式
        elif "albumlist" in album_data:
            for album in album_data["albumlist"]:
                albums.append(
                    QzoneAlbum(
                        uid=album["albumid"],  # 字段名称可能不同
                        name=album["name"],
                        count=album.get("total", album.get("picnum", 0)),
                    )
                )

        if APP_CONFIG["is_api_debug"]:
            self._emit_log(f"找到的相册: {albums}")
        return albums

    def get_photos_from_album(
        self, dest_user_qq: str, album: QzoneAlbum
    ) -> list[QzonePhoto]:
        """从特定相册获取所有照片。"""
        photos = []
        page_start = 0
        page_num_to_fetch = 500

        while True:
            if self.is_stopped_func():
                self._emit_log(f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 的后续页面。")
                break

            url = self.PHOTO_LIST_URL_TEMPLATE.format(
                gtk=self.qzone_g_tk,
                t=random.random(),
                dest_user=dest_user_qq,
                user=self.user_qq,
                album_id=album.uid,
                pageStart=page_start,
                pageNum=page_num_to_fetch,
            )
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(f"正在从以下地址获取照片: {url}")

            data = self._access_qzone_api(url)
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(
                    f"相册 '{album.name}' (页码起点 {page_start}) 的照片列表 API 响应: {json.dumps(data, indent=2, ensure_ascii=False)}"
                )

            if not data or not data.get("data"):
                if data and data.get("code", 0) != 0:  # 检查 API 错误代码
                    self._emit_log(
                        f"相册 '{album.name}' API 错误: code {data.get('code')}, message: {data.get('message')}, subcode: {data.get('subcode')}"
                    )
                break

            api_data_section = data["data"]
            total_in_album = api_data_section.get("totalInAlbum", 0)
            photos_in_page = api_data_section.get(
                "totalInPage", 0
            )

            if total_in_album == 0:
                self._emit_log(f"相册 '{album.name}' (ID: {album.uid}) 为空或没有可访问的照片。")
                break

            photo_list_data = api_data_section.get("photoList")
            if not photo_list_data:
                if (
                    photos_in_page == 0 and page_start > 0
                ):
                    self._emit_log(
                        f"在相册 '{album.name}' 中，页码起点 {page_start} 之后未找到更多照片。"
                    )
                elif photos_in_page == 0 and page_start == 0:
                    self._emit_log(f"在相册 '{album.name}' 的第一页未找到照片。")
                break

            for photo_data in photo_list_data:
                if self.is_stopped_func():
                    self._emit_log(f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 中的剩余照片。")
                    return photos
                # 优先使用 'raw' 获取原始图片，备选 'url' 或 'sloc' (小图位置)
                pic_url = (
                    photo_data.get("raw")
                    or photo_data.get("url")
                    or photo_data.get("custom_url")
                )
                if not pic_url and "lloc" in photo_data:
                    pic_url = photo_data["lloc"]
                if not pic_url and "sloc" in photo_data:
                    pic_url = photo_data["sloc"]

                if not pic_url:
                    if APP_CONFIG["is_api_debug"]:
                        self._emit_log(
                            f"跳过没有 URL 的照片: {photo_data.get('name')}, 数据: {photo_data}"
                        )
                    continue

                photos.append(
                    QzonePhoto(
                        url=pic_url,
                        name=photo_data.get(
                            "name", "untitled"
                        ).strip(),
                        album_name=album.name,
                        is_video=bool(
                            photo_data.get("is_video", False)
                            or photo_data.get("phototype") == "video"
                        ),
                    )
                )

            if len(photos) >= total_in_album:
                break
            if photos_in_page == 0:
                break

            page_start += photos_in_page

        return photos

    def download_all_photos_for_user(self, dest_user_qq: str):
        """下载目标用户所有可访问的照片。"""
        from core.downloader import download_all_photos_for_user
        download_all_photos_for_user(self, dest_user_qq)