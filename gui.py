import errno
import json
import logging
import os
import random
import re
import sys
import traceback
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler

import requests
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QTextEdit, QVBoxLayout, QWidget)
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

CONFIG_FILE = "config.json"
CONFIG = {}

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 9

if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
)
file_handler.setLevel(logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

def load_config():
    """从配置文件加载配置。"""
    global CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
        logger.info(f"成功从 {CONFIG_FILE} 加载配置。")
    except FileNotFoundError:
        logger.error(f"错误: 配置文件 {CONFIG_FILE} 未找到。请确保它存在。")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logger.error(f"错误: 解析配置文件 {CONFIG_FILE} 失败: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"加载配置文件时发生意外错误: {e}")
        sys.exit(1)

load_config()

APP_CONFIG = {
    "max_workers": CONFIG.get("max_workers", 10),
    "timeout_init": CONFIG.get("timeout_init", 30),
    "max_attempts": CONFIG.get("max_attempts", 3),
    "is_api_debug": CONFIG.get("is_api_debug", True),
    "exclude_albums": CONFIG.get("exclude_albums", []),
    "download_path": CONFIG.get("download_path", "qzone_photo"),
}

USER_CONFIG = {
    "main_user_qq": CONFIG.get("main_user_qq", "123456"),
    "dest_users_qq": CONFIG.get("dest_users_qq", ["123456",]),
}

QzoneAlbum = namedtuple("QzoneAlbum", ["uid", "name", "count"])
QzonePhoto = namedtuple("QzonePhoto", ["url", "name", "album_name", "is_video"])


def get_script_directory() -> str:
    """获取脚本文件所在的绝对路径。"""
    return os.path.dirname(os.path.realpath(__file__))


def is_path_valid(pathname: str) -> bool:
    """
    检查给定路径名在当前操作系统中是否（可能）有效。
    主要依赖 os.path.normpath 和一次 os.lstat 调用。
    """
    if not isinstance(pathname, str) or not pathname:
        return False
    if "\0" in pathname:
        return False
    try:
        normalized_pathname = os.path.normpath(pathname)
        if not normalized_pathname:
            return False
    except ValueError:
        return False
    except Exception:
        return False
    try:
        os.lstat(normalized_pathname)
        return True
    except OSError as exc:
        if exc.errno == errno.ENOENT:
            return True
        elif (
            hasattr(exc, "winerror") and exc.winerror == 123
        ):
            return False
        elif exc.errno in [errno.ENAMETOOLONG, errno.ELOOP]:
            return False
        elif exc.errno == errno.EINVAL:
            drive, tail = os.path.splitdrive(normalized_pathname)
            if os.name == "nt" and drive == normalized_pathname and not tail:
                return True
            else:
                return False
        else:
            return False
    except Exception:
        return False


def sanitize_filename_component(name_component: str) -> str:
    """
    安全处理文件名组件，替换所有非法字符为下划线。
    """
    if not isinstance(name_component, str):
        raise TypeError("输入必须是字符串类型")
    illegal_chars = r'[\/\\:*?"<>|\0]'
    return re.sub(illegal_chars, "_", name_component)


def get_save_directory(user_qq: str) -> str:
    """确定给定用户的照片保存目录。"""
    download_path = APP_CONFIG.get("download_path", "downloads")
    return os.path.join(get_script_directory(), download_path, str(user_qq))


def download_photo_network_helper(
    session: requests.Session, url: str, timeout: int
) -> requests.Response:
    """
    下载照片的辅助函数，如果需要，首先尝试使用会话下载，然后不使用会话下载。
    """
    try:
        if session:
            return session.get(url, timeout=timeout)
        else:
            return requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise ConnectionError(f"[网络错误] 尝试下载 {url} 时出错: {e}") from e


def save_photo_worker(args: tuple) -> None:
    """
    工作函数，用于下载并保存单张照片。
    在线程池中运行。
    """
    session, user_qq, album_index, album_name, photo_index, photo, log_signal, progress_signal, is_stopped_func = args

    if is_stopped_func():
        log_signal.emit(f"[停止] 照片下载任务已停止，跳过：相册 '{album_name}', 照片 {photo_index + 1}")
        logger.info(f"[停止] 照片下载任务已停止，跳过：相册 '{album_name}', 照片 {photo_index + 1}")
        progress_signal.emit(1)
        return

    album_save_path = os.path.join(
        get_save_directory(user_qq), sanitize_filename_component(album_name.strip())
    )
    if not os.path.exists(album_save_path):
        try:
            os.makedirs(album_save_path, exist_ok=True)
        except OSError as e:
            log_signal.emit(f"[错误] 无法创建目录 {album_save_path}: {e}")
            logger.error(f"[错误] 无法创建目录 {album_save_path}: {e}")
            return

    photo_name_sanitized = sanitize_filename_component(photo.name)
    base_filename = f"{photo_index}_{photo_name_sanitized}"
    if photo.is_video:
        base_filename = f"{photo_index}_{photo_name_sanitized}_视频缩略图"

    final_filename = f"{base_filename}.jpeg"
    full_photo_path = os.path.join(album_save_path, final_filename)

    if not is_path_valid(full_photo_path):
        log_signal.emit(f"[警告] 原始文件名无效: {final_filename}。将使用随机名称。")
        logger.warning(f"[警告] 原始文件名无效: {final_filename}。将使用随机名称。")
        final_filename = f"random_name_{album_index}_{photo_index}.jpeg"
        full_photo_path = os.path.join(album_save_path, final_filename)
        if not is_path_valid(full_photo_path):
            log_signal.emit(f"[错误] 备用文件名也无效: {final_filename}。跳过照片: {photo.url}")
            logger.error(f"[错误] 备用文件名也无效: {final_filename}。跳过照片: {photo.url}")
            progress_signal.emit(1)
            return

    if os.path.exists(full_photo_path):
        log_signal.emit(
            f"[本地已存在] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')"
        )
        logger.info(f"[本地已存在] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')")
        progress_signal.emit(1)
        return

    url = photo.url.replace("\\", "")
    attempts = 0
    current_timeout = APP_CONFIG["timeout_init"]

    log_signal.emit(f"[开始下载] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')")
    logger.info(f"[开始下载] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')")

    while attempts < APP_CONFIG["max_attempts"]:
        if is_stopped_func():
            log_signal.emit(f"[停止] 照片下载任务已停止，跳过重试：相册 '{album_name}', 照片 {photo_index + 1}")
            logger.info(f"[停止] 照片下载任务已停止，跳过重试：相册 '{album_name}', 照片 {photo_index + 1}")
            progress_signal.emit(1)
            return

        try:
            response = download_photo_network_helper(session, url, current_timeout)
            response.raise_for_status()

            with open(full_photo_path, "wb") as f:
                f.write(response.content)
            log_signal.emit(
                f"[下载成功] 相册 '{album_name}', 照片 {photo_index + 1}。尝试次数: {attempts + 1}, 超时时间: {current_timeout}s"
            )
            logger.info(f"[下载成功] 相册 '{album_name}', 照片 {photo_index + 1}。尝试次数: {attempts + 1}, 超时时间: {current_timeout}s")
            progress_signal.emit(1)
            return
        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ) as e:
            attempts += 1
            current_timeout += 5
            log_signal.emit(
                f"[重试下载] 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}, 新超时时间: {current_timeout}s。错误: {e}"
            )
            logger.warning(
                f"[重试下载] 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}, 新超时时间: {current_timeout}s。错误: {e}"
            )
        except requests.exceptions.HTTPError as e:
            log_signal.emit(
                f"[HTTP 错误] 下载 {url} 失败 (相册 '{album_name}', 照片 {photo_index + 1})。状态码: {e.response.status_code}。中止下载此照片。"
            )
            logger.error(
                f"[HTTP 错误] 下载 {url} 失败 (相册 '{album_name}', 照片 {photo_index + 1})。状态码: {e.response.status_code}。中止下载此照片。"
            )
            progress_signal.emit(1)
            return
        except Exception as e:
            attempts += 1
            log_signal.emit(
                f"[意外错误] 重试下载 {url}, 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}。错误: {e}"
            )
            logger.error(
                f"[意外错误] 重试下载 {url}, 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}。错误: {e}"
            )

    log_signal.emit(
        f"[下载失败] 用户: {user_qq}, 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}') URL: {photo.url} (尝试 {APP_CONFIG['max_attempts']} 次后)"
    )
    logger.error(
        f"[下载失败] 用户: {user_qq}, 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}') URL: {photo.url} (尝试 {APP_CONFIG['max_attempts']} 次后)"
    )
    progress_signal.emit(1)


class QzonePhotoManager:
    """管理 QQ 空间相册和照片的获取与下载。"""

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

    PHOTO_LIST_URL_TEMPLATE = (
        "https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"
        "cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=4&hostUin={dest_user}"
        "&topicId={album_id}&noTopic=0&uin={user}&pageStart={pageStart}&pageNum={pageNum}"
        "&skipCmtCount=0&singleurl=1&batchId=&notice=0&appid=4&inCharset=utf-8&outCharset=utf-8"
        "&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1&question=&answer="
        "&callbackFun=shine0&callback=shine0_Callback"
    )

    def __init__(self, user_qq: str, log_signal=None, is_stopped_func=None):
        """
        初始化 QzonePhotoManager。
        """
        self.user_qq = str(user_qq)
        self.cookies = {}
        self.session = requests.Session()
        self.qzone_g_tk = ""
        self.log_signal = log_signal
        self.is_stopped_func = is_stopped_func if is_stopped_func is not None else (lambda: False)
        self.total_albums = 0

    def _emit_log(self, message: str):
        """
        如果信号可用，则向 GUI 发送日志消息。
        同时使用 logger 记录消息。
        """
        if self.log_signal:
            self.log_signal.emit(message)  # type: ignore
        logger.info(message)

    def _login_and_get_cookies(self):
        """
        使用 Selenium 登录 QQ 空间以获取必要的 cookie。
        自动下载和设置 ChromeDriver。
        """
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
            logger.exception("启动 ChromeDriver 失败。")
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
            logger.error(f"登录超时或无法确认登录状态 ({LOGIN_TIMEOUT}秒)。")
            driver.quit()
            raise
        except Exception as e:
            self._emit_log(f"登录过程中发生意外错误: {e}")
            logger.exception("登录过程中发生意外错误。")
            driver.quit()
            raise

        selenium_cookies = driver.get_cookies()
        if not selenium_cookies:
            self._emit_log("获取 cookie 失败。登录可能失败或 cookie 无法访问。")
            logger.error("获取 cookie 失败。")
            driver.quit()
            raise Exception("获取 cookie 失败")

        self.cookies = {c["name"]: c["value"] for c in selenium_cookies}

        for cookie_name, cookie_value in self.cookies.items():
            self.session.cookies.set(cookie_name, cookie_value)

        p_skey = self.cookies.get("p_skey") or self.cookies.get("skey")
        if not p_skey:
            self._emit_log("错误: 在 cookie 中未找到 'p_skey' 或 'skey'。无法计算 g_tk。")
            self._emit_log(f"可用的 cookies: {list(self.cookies.keys())}")
            logger.error("在 cookie 中未找到 'p_skey' 或 'skey'。")
            driver.quit()
            raise Exception("无法计算 g_tk")

        self.qzone_g_tk = self._calculate_g_tk(p_skey)
        self._emit_log("成功获取 cookie 和 g_tk。")
        if APP_CONFIG["is_api_debug"]:
            self._emit_log(f"cookie: {self.cookies}")
            self._emit_log(f"g_tk: {self.qzone_g_tk}")
            logger.debug(f"cookie: {self.cookies}, g_tk: {self.qzone_g_tk}")

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
            logger.error(f"API 请求失败，URL: {url}: {e}")
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
                logger.warning(
                    f"意外的 API 响应格式 (没有已知的 JSONP 包装器): {text_content[:200]}"
                )
            json_str = text_content

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            self._emit_log(f"JSON 解码失败，响应内容: {json_str[:200]}... 错误: {e}")
            logger.error(f"JSON 解码失败，响应内容: {json_str[:200]}... 错误: {e}")
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(f"有问题的完整 JSON 字符串: {json_str}")
                logger.debug(f"有问题的完整 JSON 字符串: {json_str}")
            return {}

    def get_albums_by_page(self, dest_user_qq: str) -> list[QzoneAlbum]:
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
            logger.debug(f"正在从以下地址获取相册: {url}")

        data = self._access_qzone_api(url)
        if APP_CONFIG["is_api_debug"]:
            dump = json.dumps(
                data,
                indent=2,
                ensure_ascii=False,
            )
            self._emit_log(f"相册 API 响应数据: {dump}")
            logger.debug(f"相册 API 响应数据: {dump}")

        if not data or not data.get("data"):
            logger.warning(f"获取相册列表失败或没有数据：{data}")
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
        elif "albumlist" in album_data:
            for album in album_data["albumlist"]:
                albums.append(
                    QzoneAlbum(
                        uid=album["albumid"],
                        name=album["name"],
                        count=album.get("total", album.get("picnum", 0)),
                    )
                )

        if APP_CONFIG["is_api_debug"]:
            self._emit_log(f"找到的相册: {albums}")
            logger.debug(f"找到的相册: {albums}")
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
                logger.info(f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 的后续页面。")
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
                logger.debug(f"正在从以下地址获取照片: {url}")

            data = self._access_qzone_api(url)
            if APP_CONFIG["is_api_debug"]:
                self._emit_log(
                    f"相册 '{album.name}' (页码起点 {page_start}) 的照片列表 API 响应: {json.dumps(data, indent=2, ensure_ascii=False)}"
                )
                logger.debug(
                    f"相册 '{album.name}' (页码起点 {page_start}) 的照片列表 API 响应: {json.dumps(data, indent=2, ensure_ascii=False)}"
                )

            if not data or not data.get("data"):
                if data and data.get("code", 0) != 0:
                    self._emit_log(
                        f"相册 '{album.name}' API 错误: code {data.get('code')}, message: {data.get('message')}, subcode: {data.get('subcode')}"
                    )
                    logger.error(
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
                logger.info(f"相册 '{album.name}' (ID: {album.uid}) 为空或没有可访问的照片。")
                break

            photo_list_data = api_data_section.get("photoList")
            if not photo_list_data:
                if (
                    photos_in_page == 0 and page_start > 0
                ):
                    self._emit_log(
                        f"在相册 '{album.name}' 中，页码起点 {page_start} 之后未找到更多照片。"
                    )
                    logger.info(
                        f"在相册 '{album.name}' 中，页码起点 {page_start} 之后未找到更多照片。"
                    )
                elif photos_in_page == 0 and page_start == 0:
                    self._emit_log(f"在相册 '{album.name}' 的第一页未找到照片。")
                    logger.info(f"在相册 '{album.name}' 的第一页未找到照片。")
                break

            for photo_data in photo_list_data:
                if self.is_stopped_func():
                    self._emit_log(f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 中的剩余照片。")
                    logger.info(f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 中的剩余照片。")
                    return photos
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
                        logger.debug(
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

    def download_all_photos_for_user(self, dest_user_qq: str, progress_signal):
        """下载目标用户所有可访问的照片。"""
        albums = self.get_albums_by_page(dest_user_qq)
        if not albums:
            self._emit_log(f"未找到用户 {dest_user_qq} 的相册或无法访问。")
            logger.info(f"未找到用户 {dest_user_qq} 的相册或无法访问。")
            progress_signal.emit(0)  # type: ignore
            return

        self._emit_log(f"为用户 {dest_user_qq} 找到 {len(albums)} 个相册:")
        logger.info(f"为用户 {dest_user_qq} 找到 {len(albums)} 个相册:")
        for i, album_item in enumerate(albums):
            self._emit_log(
                f"  {i+1}. {album_item.name} (ID: {album_item.uid}, 照片数量: {album_item.count})"
            )
            logger.info(
                f"  {i+1}. {album_item.name} (ID: {album_item.uid}, 照片数量: {album_item.count})"
            )

        all_photo_tasks = []
        user_save_dir = get_save_directory(dest_user_qq)
        if not os.path.exists(user_save_dir):
            os.makedirs(user_save_dir, exist_ok=True)

        for album_index, album in enumerate(albums):
            if self.is_stopped_func():
                self._emit_log(f"[停止] 相册处理任务已停止，跳过后续相册。")
                logger.info(f"[停止] 相册处理任务已停止，跳过后续相册。")
                break

            if album.name in APP_CONFIG["exclude_albums"]:
                self._emit_log(f"跳过排除的相册: '{album.name}'")
                logger.info(f"跳过排除的相册: '{album.name}'")
                continue

            album_path = os.path.join(
                user_save_dir,
                sanitize_filename_component(
                    album.name.strip(),
                ),
            )
            if not os.path.exists(album_path):
                try:
                    os.makedirs(album_path, exist_ok=True)
                except OSError as e:
                    self._emit_log(f"为相册 '{album.name}' 创建目录时出错: {e}。跳过此相册。")
                    logger.error(f"为相册 '{album.name}' 创建目录时出错: {e}。跳过此相册。")
                    continue

            self._emit_log(f"\n正在获取相册 '{album.name}' 的照片 (预计 {album.count} 张)...")
            logger.info(f"\n正在获取相册 '{album.name}' 的照片 (预计 {album.count} 张)...")
            photos_in_album = self.get_photos_from_album(dest_user_qq, album)
            self._emit_log(
                f"为相册 '{album.name}' 找到 {len(photos_in_album)} 个照片条目。准备下载。"
            )
            logger.info(
                f"为相册 '{album.name}' 找到 {len(photos_in_album)} 个照片条目。准备下载。"
            )

            for photo_idx, photo_item in enumerate(photos_in_album):
                if self.is_stopped_func():
                    self._emit_log(f"[停止] 照片任务添加已停止，跳过相册 '{album.name}' 中的剩余照片。")
                    logger.info(f"[停止] 照片任务添加已停止，跳过相册 '{album.name}' 中的剩余照片。")
                    break

                all_photo_tasks.append(
                    (
                        self.session,
                        dest_user_qq,
                        album_index,
                        album.name,
                        photo_idx,
                        photo_item,
                        self.log_signal,
                        progress_signal,
                        self.is_stopped_func
                    )
                )

        if not all_photo_tasks:
            self._emit_log(f"没有为用户 {dest_user_qq} 下载的照片。")
            logger.info(f"没有为用户 {dest_user_qq} 下载的照片。")
            progress_signal.emit(0)  # type: ignore
            return

        self._emit_log(
            f"\n开始下载 {len(all_photo_tasks)} 张照片，使用 {APP_CONFIG['max_workers']} 个线程..."
        )
        logger.info(
            f"\n开始下载 {len(all_photo_tasks)} 张照片，使用 {APP_CONFIG['max_workers']} 个线程..."
        )
        progress_signal.emit(-len(all_photo_tasks))  # type: ignore

        with ThreadPoolExecutor(max_workers=APP_CONFIG["max_workers"]) as executor:
            list(executor.map(save_photo_worker, all_photo_tasks))

        if not self.is_stopped_func():
            self._emit_log(f"\n完成处理用户 {dest_user_qq} 的所有照片。")
            logger.info(f"\n完成处理用户 {dest_user_qq} 的所有照片。")


class DownloadWorker(QThread):
    """
    一个 QThread 工作线程，用于在后台运行 QQ 空间照片下载过程。
    发出信号以进行日志记录和进度更新。
    """
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, main_user_qq: str, main_user_pass: str, dest_users_qq: list):
        """
        初始化 DownloadWorker。
        """
        super().__init__()
        self.main_user_qq = main_user_qq
        self.dest_users_qq = dest_users_qq
        self.qzone_manager = None
        self._is_stopped = False

    def stop(self):
        """设置停止标志，请求线程停止。"""
        self._is_stopped = True
        logger.info("下载工作线程收到停止请求。")

    def is_stopped(self):
        """检查线程是否已收到停止请求。"""
        return self._is_stopped

    def run(self):
        """线程的主要执行方法。"""
        try:
            self.log_signal.emit("正在初始化下载管理器并尝试登录...")
            self.qzone_manager = QzonePhotoManager(self.main_user_qq, self.log_signal, self.is_stopped)
            
            if not self.is_stopped():
                self.qzone_manager._login_and_get_cookies()
                self.log_signal.emit("登录过程已完成。")
            else:
                self.log_signal.emit("启动前已收到停止请求，跳过登录。")
                logger.info("启动前已收到停止请求，跳过登录。")
                self.finished_signal.emit("Stopped")
                return

            for target_qq in self.dest_users_qq:
                if self.is_stopped():
                    self.log_signal.emit(f"下载任务已停止，跳过用户 {target_qq} 及后续用户。")
                    logger.info(f"下载任务已停止，跳过用户 {target_qq} 及后续用户。")
                    break

                target_qq_str = str(target_qq)
                self.log_signal.emit(f"\n--- 正在处理用户: {target_qq_str} ---")
                try:
                    self.qzone_manager.download_all_photos_for_user(target_qq_str, self.progress_signal)
                except Exception as e:
                    self.log_signal.emit(f"处理用户 {target_qq_str} 时发生意外错误: {e}")
                    self.log_signal.emit(traceback.format_exc())
                    logger.exception(f"处理用户 {target_qq_str} 时发生意外错误。")
                self.log_signal.emit(f"--- 完成处理用户: {target_qq_str} ---")
                self.finished_signal.emit(target_qq_str)

            if not self.is_stopped():
                self.log_signal.emit("\n所有指定用户处理完毕。")
                logger.info("所有指定用户处理完毕。")
            else:
                self.log_signal.emit("下载已停止。")  # 修复：移除对不存在属性的访问
                logger.info("下载已停止。")

        except Exception as e:
            self.log_signal.emit(f"下载过程中发生关键错误: {e}")
            self.log_signal.emit(traceback.format_exc())
            logger.exception("下载过程中发生关键错误。")
        finally:
            self.finished_signal.emit("All")


class QzoneDownloaderGUI(QWidget):
    """QQ 空间照片下载器的主 GUI 应用程序。"""

    def __init__(self):
        """初始化 GUI 应用程序。"""
        super().__init__()
        self.setWindowTitle("QQ 空间照片下载器")
        self.setGeometry(100, 100, 800, 600)

        self.worker_thread = None
        self.total_photos_to_download = 0
        self.downloaded_photos_count = 0

        self.init_ui()
        self.load_initial_config_to_ui()

        self.gui_logger_handler = GuiLogHandler(self.log_output)
        self.gui_logger_handler.setLevel(logging.INFO)
        self.gui_logger_handler.setFormatter(formatter)
        logger.addHandler(self.gui_logger_handler)

    def init_ui(self):
        """初始化用户界面。"""
        main_layout = QVBoxLayout()

        input_layout = QVBoxLayout()

        self.main_qq_label = QLabel("主QQ号 (用于登录):")
        self.main_qq_input = QLineEdit()
        self.main_qq_input.setPlaceholderText("请输入您的QQ号码")
        input_layout.addWidget(self.main_qq_label)
        input_layout.addWidget(self.main_qq_input)

        self.dest_qq_label = QLabel("目标QQ号 (多个用逗号分隔):")
        self.dest_qq_input = QLineEdit()
        self.dest_qq_input.setPlaceholderText("请输入要下载的QQ号码，例如: 123456,789012")
        input_layout.addWidget(self.dest_qq_label)
        input_layout.addWidget(self.dest_qq_input)

        download_path_layout = QHBoxLayout()
        self.download_path_label = QLabel("下载路径:")
        self.download_path_input = QLineEdit()
        self.download_path_input.setReadOnly(True)
        self.download_path_button = QPushButton("选择目录")
        self.download_path_button.clicked.connect(self.select_download_path)
        download_path_layout.addWidget(self.download_path_label)
        download_path_layout.addWidget(self.download_path_input)
        download_path_layout.addWidget(self.download_path_button)
        input_layout.addLayout(download_path_layout)

        main_layout.addLayout(input_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setFormat("准备中...")
        self.progress_bar.setValue(0)
        main_layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()
        self.start_button = QPushButton("开始下载")
        self.start_button.clicked.connect(self.start_download)
        self.stop_button = QPushButton("停止下载")
        self.stop_button.clicked.connect(self.stop_download)
        self.stop_button.setEnabled(False)

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        main_layout.addLayout(button_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        main_layout.addWidget(self.log_output)

        self.setLayout(main_layout)

    def load_initial_config_to_ui(self):
        """将配置值加载到 UI 字段中。"""
        self.main_qq_input.setText(USER_CONFIG.get("main_user_qq", ""))
        self.dest_qq_input.setText(",".join(USER_CONFIG.get("dest_users_qq", [])))
        self.download_path_input.setText(os.path.join(get_script_directory(), APP_CONFIG.get("download_path", "qzone_photo")))


    def select_download_path(self):
        """打开目录对话框以选择下载路径。"""
        current_path = self.download_path_input.text()
        if not current_path:
            current_path = get_script_directory()

        dir_dialog = QFileDialog(self)
        dir_dialog.setFileMode(QFileDialog.FileMode.Directory)
        dir_dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dir_dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        selected_dir = dir_dialog.getExistingDirectory(self, "选择下载目录", current_path)

        if selected_dir:
            self.download_path_input.setText(selected_dir)
            relative_path = os.path.relpath(selected_dir, get_script_directory())
            APP_CONFIG["download_path"] = relative_path


    def start_download(self):
        """在单独的线程中启动下载过程。"""
        main_qq = self.main_qq_input.text().strip()
        main_pass = ""
        dest_qqs_str = self.dest_qq_input.text().strip()
        download_path = self.download_path_input.text().strip()

        if main_qq == "123456":
            QMessageBox.warning(self, "输入错误", "主QQ号错误，请输入您的QQ号。")
            logger.warning("用户输入错误：用户未输入自己的QQ号。")
            return
        if not main_qq or not dest_qqs_str:
            QMessageBox.warning(self, "输入错误", "主QQ号和目标QQ号不能为空。")
            logger.warning("用户输入错误：主QQ号或目标QQ号为空。")
            return
        if not download_path:
            QMessageBox.warning(self.main_qq_input, "输入错误", "下载路径不能为空。")
            logger.warning("用户输入错误：下载路径为空。")
            return

        try:
            dest_qqs = [qq.strip() for qq in dest_qqs_str.split(",") if qq.strip()]
        except Exception as e:
            QMessageBox.warning(self.main_qq_input, "输入错误", "目标QQ号格式不正确。请用逗号分隔。")
            logger.warning(f"用户输入错误：目标QQ号格式不正确。错误：{e}")
            return

        if not dest_qqs:
            QMessageBox.warning(self.main_qq_input, "输入错误", "目标QQ号列表不能为空。")
            logger.warning("用户输入错误：目标QQ号列表为空。")
            return

        USER_CONFIG["main_user_qq"] = main_qq
        USER_CONFIG["dest_users_qq"] = dest_qqs
        APP_CONFIG["download_path"] = os.path.relpath(download_path, get_script_directory())

        try:
            updated_config = {
                "main_user_qq": USER_CONFIG["main_user_qq"],
                "dest_users_qq": USER_CONFIG["dest_users_qq"],
                "max_workers": APP_CONFIG["max_workers"],
                "timeout_init": APP_CONFIG["timeout_init"],
                "max_attempts": APP_CONFIG["max_attempts"],
                "is_api_debug": APP_CONFIG["is_api_debug"],
                "exclude_albums": APP_CONFIG["exclude_albums"],
                "download_path": APP_CONFIG["download_path"],
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(updated_config, f, indent=4, ensure_ascii=False)
            self.log_output.append(f"配置已保存到 {CONFIG_FILE}。")
            logger.info(f"配置已保存到 {CONFIG_FILE}。")
        except Exception as e:
            self.log_output.append(f"保存配置失败: {e}")
            logger.error(f"保存配置失败: {e}")

        self.log_output.clear()
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("初始化...")
        self.total_photos_to_download = 0
        self.downloaded_photos_count = 0

        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)

        self.log_output.append("开始下载任务...")
        logger.info("开始下载任务...")

        self.worker_thread = DownloadWorker(main_qq, main_pass, dest_qqs)
        self.worker_thread.log_signal.connect(self.update_log)
        self.worker_thread.progress_signal.connect(self.update_progress)
        self.worker_thread.finished_signal.connect(self.on_download_finished)
        self.worker_thread.start()

    def stop_download(self):
        """尝试停止正在进行的下载过程。"""
        if self.worker_thread and self.worker_thread.isRunning():
            self.worker_thread.stop()
            self.log_output.append("下载任务已收到停止请求。正在尝试停止当前操作...")
            logger.info("下载任务已收到停止请求。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("停止中...")
        else:
            self.log_output.append("没有正在运行的下载任务。")
            logger.info("没有正在运行的下载任务。")

    def update_log(self, message: str):
        """将消息附加到日志输出区域。"""
        self.log_output.append(message)
        scrollbar = self.log_output.verticalScrollBar()
        if scrollbar:
            scrollbar.setValue(scrollbar.maximum())

    def update_progress(self, value: int):
        """
        更新进度条。
        如果值为负数，表示任务总数。
        如果值为正数（1），表示一个任务已完成。
        """
        if value < 0:
            self.total_photos_to_download = abs(value)
            self.progress_bar.setMaximum(self.total_photos_to_download)
            self.progress_bar.setFormat(f"已下载 0 / {self.total_photos_to_download}")
        elif value == 1:
            self.downloaded_photos_count += 1
            if self.total_photos_to_download > 0:
                percentage = (self.downloaded_photos_count / self.total_photos_to_download) * 100
                self.progress_bar.setValue(self.downloaded_photos_count)
                self.progress_bar.setFormat(f"已下载 {self.downloaded_photos_count} / {self.total_photos_to_download} ({percentage:.1f}%)")
            else:
                self.progress_bar.setFormat(f"已下载 {self.downloaded_photos_count} 张照片")


    def on_download_finished(self, user_qq_or_all: str):
        """当用户下载完成或所有任务完成时调用。"""
        if user_qq_or_all == "All":
            self.log_output.append("所有下载任务已完成。")
            logger.info("所有下载任务已完成。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("完成")
            self.progress_bar.setValue(self.progress_bar.maximum())
        elif user_qq_or_all == "Stopped":
            self.log_output.append("下载任务已停止。")
            logger.info("下载任务已停止。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("已停止")
        else:
            self.log_output.append(f"用户 {user_qq_or_all} 的照片下载完成。")
            logger.info(f"用户 {user_qq_or_all} 的照片下载完成。")

class GuiLogHandler(logging.Handler):
    """一个自定义的日志处理器，用于将日志消息发送到 PyQt 的 QTextEdit 控件。"""
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.queue = []
        self.timer = QTimer()
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(100)

    def emit(self, record):
        """处理日志记录并将其添加到队列中。"""
        msg = self.format(record)
        self.queue.append(msg)

    def process_queue(self):
        """从队列中获取消息并将其添加到 QTextEdit 中。"""
        while self.queue:
            message = self.queue.pop(0)
            self.text_widget.append(message)
            self.text_widget.verticalScrollBar().setValue(self.text_widget.verticalScrollBar().maximum())

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = QzoneDownloaderGUI()
    gui.show()
    sys.exit(app.exec())
