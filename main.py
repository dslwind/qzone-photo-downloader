import errno
import json
import os
import random
import re
import shutil
import sys
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# --- 配置信息 ---
APP_CONFIG = {
    "max_workers": 10,  # 并行下载线程数量
    "timeout_init": 30,  # 请求初始超时时间 (秒)
    "max_attempts": 3,  # 下载失败后最大重试次数
    "is_api_debug": True,  # 是否打印 API 请求 URL 和响应内容
    "exclude_albums": [],  # 需要排除不下载的相册名称列表
    "download_path": "qzone_photo",  # 下载路径（相对于脚本位置）
}

USER_CONFIG = {
    "main_user_qq": "123456",  # 替换为您的 QQ 号码
    "main_user_pass": "",  # 建议留空以进行手动登录
    "dest_users_qq": ["123456",],  # 替换为目标 QQ 号码（字符串列表）
}

# --- 命名元组 ---
# QQ空间相册对象，包含相册ID, 相册名, 照片数量
QzoneAlbum = namedtuple("QzoneAlbum", ["uid", "name", "count"])
# QQ空间照片对象，包含照片链接, 照片名, 所属相册名, 是否为视频
QzonePhoto = namedtuple("QzonePhoto", ["url", "name", "album_name", "is_video"])


# --- 工具函数---
def get_script_directory() -> str:
    """获取脚本文件所在的绝对路径。"""
    return os.path.dirname(os.path.realpath(__file__))


def is_path_valid(pathname: str) -> bool:
    """
    检查给定路径名在当前操作系统中是否（可能）有效。
    主要依赖 os.path.normpath 和一次 os.lstat 调用。
    它旨在捕获明显的无效路径，例如包含空字符、名称过长或无效字符（由 lstat 检测）。

    注意：如果路径的某个部分不存在（导致 ENOENT），此函数可能无法捕获
    后续路径组件中的无效名称，因为 os.lstat 会因 ENOENT 而首先失败。
    """
    # 1. 初始类型和空值检查
    if not isinstance(pathname, str) or not pathname:
        return False

    # 2. 检查空字符（在路径组件中通常无效）
    if "\0" in pathname:
        return False

    # 3. 尝试规范化路径
    try:
        normalized_pathname = os.path.normpath(pathname)
        # 如果规范化后路径为空字符串（例如，原始路径本身就是问题，或 normpath 的罕见行为），则视为无效。
        # 初始的 `if not pathname:` 已处理输入为空字符串的情况。
        # 此处检查确保 normpath 返回的是一个非空字符串。
        if not normalized_pathname:
            return False
    except (
        ValueError
    ):  # 例如，Windows 上的 normpath 可能会对包含嵌入空字符的路径引发 ValueError
        return False
    except Exception:  # normpath 期间的其他特定于操作系统的错误（不太可能，但作为防护）
        return False

    # 4. 尝试对整个规范化路径执行 lstat
    try:
        os.lstat(normalized_pathname)
        return True  # 如果 lstat 成功，路径有效
    except OSError as exc:
        # 如果文件或路径组件不存在 (ENOENT)，我们假设名称本身仍然可能是有效的。
        # 函数的目的是检查名称的有效性，而不是路径的存在性。
        if exc.errno == errno.ENOENT:
            return True
        # 以下错误明确表示名称/路径本身存在问题
        elif (
            hasattr(exc, "winerror") and exc.winerror == 123
        ):  # ERROR_INVALID_NAME (Windows)
            return False
        elif exc.errno in [errno.ENAMETOOLONG, errno.ELOOP]:  # 名称过长或符号链接循环
            return False
        elif exc.errno == errno.EINVAL:  # 无效参数
            # 特殊处理 Windows 上的驱动器号（例如 "C:"）。
            # os.lstat("C:") 在 Windows 上会引发 EINVAL，但我们认为 "C:" 是一个有效的路径前缀。
            drive, tail = os.path.splitdrive(normalized_pathname)
            if os.name == "nt" and drive == normalized_pathname and not tail:
                # 这确实是一个驱动器号，例如 "C:" (normalized_pathname == "C:")
                return True
            else:
                # 其他 EINVAL 情况（或非 Windows 系统上的 EINVAL）表示路径无效。
                return False
        else:
            # 其他 OSError（例如 EACCES - 权限问题）不一定意味着名称无效，
            # 但为了简化和安全起见，我们将它们视为路径无效。
            return False
    except Exception:  # 捕获 lstat 期间的任何其他非 OSError 异常（不太可能）
        return False


def sanitize_filename_component(name_component: str) -> str:
    """安全处理文件名组件，替换所有非法字符为下划线

    参数:
        name_component: 需要处理的原始文件名组件

    返回:
        处理后的安全字符串
    """
    if not isinstance(name_component, str):
        raise TypeError("输入必须是字符串类型")

    # 定义正则表达式模式，匹配各种操作系统中的非法文件名字符
    illegal_chars = r'[\/\\:*?"<>|\0]'  # 包含路径分隔符和其他特殊字符

    # 使用单个正则替换所有非法字符
    return re.sub(illegal_chars, "_", name_component)


# --- 核心逻辑 ---
def get_save_directory(user_qq: str) -> str:
    """确定给定用户的照片保存目录"""
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
        print(f"[网络错误] 尝试下载 {url} 时出错: {e}")
        raise


def save_photo_worker(args: tuple) -> None:
    """
    工作函数，用于下载并保存单张照片。
    在线程池中运行。
    """
    session, user_qq, album_index, album_name, photo_index, photo = args

    album_save_path = os.path.join(
        get_save_directory(user_qq), sanitize_filename_component(album_name.strip())
    )
    if not os.path.exists(album_save_path):
        try:
            os.makedirs(album_save_path, exist_ok=True)
        except OSError as e:
            print(f"[错误] 无法创建目录 {album_save_path}: {e}")
            return

    photo_name_sanitized = sanitize_filename_component(photo.name)
    base_filename = f"{photo_index}_{photo_name_sanitized}"
    if photo.is_video:
        base_filename = f"{photo_index}_{photo_name_sanitized}_视频缩略图"

    final_filename = f"{base_filename}.jpeg"
    full_photo_path = os.path.join(album_save_path, final_filename)

    if not is_path_valid(full_photo_path):
        print(f"[警告] 原始文件名无效: {final_filename}。将使用随机名称。")
        final_filename = f"random_name_{album_index}_{photo_index}.jpeg"
        full_photo_path = os.path.join(album_save_path, final_filename)
        if not is_path_valid(full_photo_path):  # 仍然无效
            print(f"[错误] 备用文件名也无效: {final_filename}。跳过照片: {photo.url}")
            return

    if os.path.exists(full_photo_path):
        print(
            f"[本地已存在] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')"
        )
        return

    url = photo.url.replace("\\", "")  # 清理 URL
    attempts = 0
    current_timeout = APP_CONFIG["timeout_init"]

    print(f"[开始下载] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')")

    while attempts < APP_CONFIG["max_attempts"]:
        try:
            response = download_photo_network_helper(session, url, current_timeout)
            response.raise_for_status()  # 对错误的响应 (4xx 或 5xx) 引发 HTTPError

            with open(full_photo_path, "wb") as f:
                f.write(response.content)
            print(
                f"[下载成功] 相册 '{album_name}', 照片 {photo_index + 1}。尝试次数: {attempts + 1}, 超时时间: {current_timeout}s"
            )
            return  # 下载成功
        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ) as e:
            attempts += 1
            current_timeout += 5
            print(
                f"[重试下载] 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}, 新超时时间: {current_timeout}s。错误: {e}"
            )
        except requests.exceptions.HTTPError as e:
            print(
                f"[HTTP 错误] 下载 {url} 失败 (相册 '{album_name}', 照片 {photo_index + 1})。状态码: {e.response.status_code}。中止下载此照片。"
            )
            return  # 对于像 404, 403 这样的 HTTP 错误不进行重试
        except Exception as e:  # 捕获任何其他意外错误
            attempts += 1  # 暂时将其视为可重试的错误
            print(
                f"[意外错误] 重试下载 {url}, 相册 '{album_name}', 照片 {photo_index + 1}。尝试 {attempts}/{APP_CONFIG['max_attempts']}。错误: {e}"
            )

    print(
        f"[下载失败] 用户: {user_qq}, 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}') URL: {photo.url} (尝试 {APP_CONFIG['max_attempts']} 次后)"
    )


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

    # 获取照片列表的API URL模板
    PHOTO_LIST_URL_TEMPLATE = (
        "https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"
        "cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=4&hostUin={dest_user}"
        "&topicId={album_id}&noTopic=0&uin={user}&pageStart={pageStart}&pageNum={pageNum}"
        "&skipCmtCount=0&singleurl=1&batchId=&notice=0&appid=4&inCharset=utf-8&outCharset=utf-8"
        "&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1&question=&answer="
        "&callbackFun=shine0&callback=shine0_Callback"
    )

    def __init__(self, user_qq: str, password: str):
        self.user_qq = str(user_qq)
        self.password = password
        self.cookies = {}
        self.session = requests.Session()  # 使用会话进行后续请求
        self.qzone_g_tk = ""
        self._login_and_get_cookies()

    def _login_and_get_cookies(self):
        """使用 Selenium 登录 QQ 空间以获取必要的 cookie。"""
        driver_name = "chromedriver.exe" if sys.platform == "win32" else "chromedriver"

        # 1. 优先从脚本目录查找
        local_path = os.path.join(get_script_directory(), driver_name)
        if os.path.exists(local_path):
            driver_path = local_path
        # 2. 从系统PATH查找
        else:
            driver_path = driver_name if shutil.which(driver_name) else None

        print("正在尝试启动 Chrome 进行登录...")
        options = webdriver.ChromeOptions()
        # 如果需要，添加任何选项，例如：无头模式、用户代理
        # options.add_argument('--headless')
        # options.add_argument('--disable-gpu')
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-blink-features")

        # options.add_argument("--disable-extensions")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--lang=zh-CN")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        # 使用 Service 对象指定 ChromeDriver路径
        service = ChromeService(executable_path=driver_path)
        try:
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
            print(f"启动 ChromeDriver 失败。请确保它在您的 PATH 或脚本目录中: {e}")
            print(f"尝试使用的驱动路径: {driver_path}")
            print(
                "您可以从以下地址下载 ChromeDriver: https://googlechromelabs.github.io/chrome-for-testing"
            )
            sys.exit(1)

        driver.get("https://user.qzone.qq.com")
        print("请在浏览器窗口中登录 QQ 空间。脚本将在登录后继续...")

        # 等待登录
        LOGIN_TIMEOUT = 300  # 最大等待时间(秒)

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
            print(f"错误: {LOGIN_TIMEOUT}秒内未检测到成功登录")
            print("建议：1) 确保网络正常 2) 可能需要手动处理验证码")
            driver.quit()
            sys.exit(1)
        except Exception as e:
            print(f"登录过程中发生意外错误: {e}")
            driver.quit()
            sys.exit(1)

        # 获取 cookie
        selenium_cookies = driver.get_cookies()
        if not selenium_cookies:
            print("获取 cookie 失败。登录可能失败或 cookie 无法访问。")
            driver.quit()
            sys.exit(1)

        self.cookies = {c["name"]: c["value"] for c in selenium_cookies}

        # 使用这些 cookie 更新请求会话
        for cookie_name, cookie_value in self.cookies.items():
            self.session.cookies.set(cookie_name, cookie_value)

        p_skey = self.cookies.get("p_skey") or self.cookies.get("skey")
        if not p_skey:
            print("错误: 在 cookie 中未找到 'p_skey' 或 'skey'。无法计算 g_tk。")
            # 打印可用的cookie键，方便调试
            print("可用的 cookies:", list(self.cookies.keys()))
            driver.quit()
            sys.exit(1)

        self.qzone_g_tk = self._calculate_g_tk(p_skey)
        print("成功获取 cookie 和 g_tk。")
        if APP_CONFIG["is_api_debug"]:
            print(f"cookie: {self.cookies}")
            print(f"g_tk: {self.qzone_g_tk}")

        driver.quit()

    def _calculate_g_tk(self, p_skey: str) -> int:
        """根据 p_skey 计算 g_tk。"""
        hash_val = 5381
        for char in p_skey:
            hash_val += (hash_val << 5) + ord(char)
        return hash_val & 0x7FFFFFFF

    def _access_qzone_api(self, url: str, timeout_seconds: int = None) -> dict:
        """访问 QQ 空间 API 端点并解析 JSONP 响应。"""
        if timeout_seconds is None:
            timeout_seconds = APP_CONFIG["timeout_init"]

        try:
            # 使用带 cookie 的会话进行请求
            response = self.session.get(url, timeout=timeout_seconds)
            response.raise_for_status()  # 检查 HTTP 错误
        except requests.exceptions.RequestException as e:
            print(f"API 请求失败，URL: {url}: {e}")
            return {}

        text_content = response.text
        # 清理 JSONP 包装器："shine0_Callback(...);" 或类似格式
        if text_content.startswith("shine0_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("shine0_Callback(") : -2]
        elif text_content.startswith("_Callback(") and text_content.endswith(");"):
            # 某些 API 可能使用此格式
            json_str = text_content[len("_Callback(") : -2]
        else:
            # 如果没有已知的包装器，则尝试直接解析；如果看起来像错误，则记录日志
            if APP_CONFIG["is_api_debug"]:
                # 记录内容开头部分
                print(
                    f"意外的 API 响应格式 (没有已知的 JSONP 包装器): {text_content[:200]}"
                )
            json_str = text_content  # 假设它可能是纯 JSON

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"JSON 解码失败，响应内容: {json_str[:200]}... 错误: {e}")
            if APP_CONFIG["is_api_debug"]:
                print(f"有问题的完整 JSON 字符串: {json_str}")
            return {}

    def get_albums(self, dest_user_qq: str) -> list[QzoneAlbum]:
        """获取给定用户的相册列表。"""
        albums = []
        url = self.ALBUM_LIST_URL_TEMPLATE.format(
            gtk=self.qzone_g_tk,
            t=random.random(),
            dest_user=dest_user_qq,
            user=self.user_qq,
        )
        if APP_CONFIG["is_api_debug"]:
            print(f"正在从以下地址获取相册: {url}")

        data = self._access_qzone_api(url)
        if APP_CONFIG["is_api_debug"]:
            dump = json.dumps(
                data,
                indent=2,
                ensure_ascii=False,  # ensure_ascii=False 以正确显示中文
            )
            print(f"相册 API 响应数据: {dump}")

        if not data or not data.get("data"):
            return albums

        album_data = data["data"]
        if "albumListModeSort" in album_data:  # 普通视图
            album_list = album_data["albumListModeSort"]
        elif "albumListModeClass" in album_data:  # 列表视图
            album_list = [
                item
                for d in album_data["albumListModeClass"]
                for item in d.get("albumList", [])
            ]
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
            print(f"找到的相册: {albums}")
        return albums

    def get_photos_from_album(
        self, dest_user_qq: str, album: QzoneAlbum
    ) -> list[QzonePhoto]:
        """从特定相册获取所有照片。"""
        photos = []
        page_start = 0
        page_num_to_fetch = 500  # QQ空间 API 每页限制数量

        while True:
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
                print(f"正在从以下地址获取照片: {url}")

            data = self._access_qzone_api(url)
            if APP_CONFIG["is_api_debug"]:
                print(
                    f"相册 '{album.name}' (页码起点 {page_start}) 的照片列表 API 响应: {json.dumps(data, indent=2, ensure_ascii=False)}"
                )

            if not data or not data.get("data"):
                if data and data.get("code", 0) != 0:  # 检查 API 错误代码
                    print(
                        f"相册 '{album.name}' API 错误: code {data.get('code')}, message: {data.get('message')}, subcode: {data.get('subcode')}"
                    )
                break  # 没有更多数据或发生错误

            api_data_section = data["data"]
            total_in_album = api_data_section.get("totalInAlbum", 0)  # 相册中的总照片数
            photos_in_page = api_data_section.get(
                "totalInPage", 0
            )  # 当前响应中的照片数量

            if total_in_album == 0:  # 相册为空
                print(f"相册 '{album.name}' (ID: {album.uid}) 为空或没有可访问的照片。")
                break

            photo_list_data = api_data_section.get("photoList")
            if not photo_list_data:  # 此页面没有照片，或已到相册末尾
                if (
                    photos_in_page == 0 and page_start > 0
                ):  # 如果不是第一页且没有照片，则表示已到达末尾
                    print(
                        f"在相册 '{album.name}' 中，页码起点 {page_start} 之后未找到更多照片。"
                    )
                elif photos_in_page == 0 and page_start == 0:
                    print(f"在相册 '{album.name}' 的第一页未找到照片。")
                break

            for photo_data in photo_list_data:
                # 优先使用 'raw' 获取原始图片，备选 'url' 或 'sloc' (小图位置)
                pic_url = (
                    photo_data.get("raw")
                    or photo_data.get("url")
                    or photo_data.get("custom_url")
                )
                if not pic_url and "lloc" in photo_data:  # 大图位置
                    pic_url = photo_data["lloc"]
                if not pic_url and "sloc" in photo_data:  # 小图位置，最后选择
                    pic_url = photo_data["sloc"]

                if not pic_url:
                    if APP_CONFIG["is_api_debug"]:
                        print(
                            f"跳过没有 URL 的照片: {photo_data.get('name')}, 数据: {photo_data}"
                        )
                    continue

                photos.append(
                    QzonePhoto(
                        url=pic_url,
                        name=photo_data.get(
                            "name", "untitled"
                        ).strip(),  # 照片名，默认为'untitled'并去除首尾空格
                        album_name=album.name,  # 将相册名称添加到照片元组中以便于追溯
                        is_video=bool(
                            photo_data.get("is_video", False)
                            or photo_data.get("phototype") == "video"
                        ),  # 判断是否为视频
                    )
                )

            if len(photos) >= total_in_album:  # 已获取所有照片
                break
            if photos_in_page == 0:  # 此页未返回照片
                break

            page_start += photos_in_page  # 根据接收到的照片数量正确前进页码

        return photos

    def download_all_photos_for_user(self, dest_user_qq: str):
        """下载目标用户所有可访问的照片。"""
        albums = self.get_albums(dest_user_qq)
        if not albums:
            print(f"未找到用户 {dest_user_qq} 的相册或无法访问。")
            return

        print(f"为用户 {dest_user_qq} 找到 {len(albums)} 个相册:")
        for i, album_item in enumerate(albums):
            print(
                f"  {i+1}. {album_item.name} (ID: {album_item.uid}, 照片数量: {album_item.count})"
            )

        all_photo_tasks = []
        user_save_dir = get_save_directory(dest_user_qq)
        if not os.path.exists(user_save_dir):
            os.makedirs(user_save_dir, exist_ok=True)

        for album_index, album in enumerate(albums):
            if album.name in APP_CONFIG["exclude_albums"]:
                print(f"跳过排除的相册: '{album.name}'")
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
                    print(f"为相册 '{album.name}' 创建目录时出错: {e}。跳过此相册。")
                    continue

            print(f"\n正在获取相册 '{album.name}' 的照片 (预计 {album.count} 张)...")
            photos_in_album = self.get_photos_from_album(dest_user_qq, album)
            print(
                f"为相册 '{album.name}' 找到 {len(photos_in_album)} 个照片条目。准备下载。"
            )

            for photo_idx, photo_item in enumerate(photos_in_album):
                all_photo_tasks.append(
                    (
                        self.session,
                        dest_user_qq,
                        album_index,
                        album.name,
                        photo_idx,
                        photo_item,
                    )
                )

        if not all_photo_tasks:
            print(f"没有为用户 {dest_user_qq} 下载的照片。")
            return

        print(
            f"\n开始下载 {len(all_photo_tasks)} 张照片，使用 {APP_CONFIG['max_workers']} 个线程..."
        )
        with ThreadPoolExecutor(max_workers=APP_CONFIG["max_workers"]) as executor:
            # map 会运行任务并收集结果 (在这种情况下是 None)
            list(executor.map(save_photo_worker, all_photo_tasks))
            # 使用 list() 来确保所有任务完成后再继续

        print(f"\n完成处理用户 {dest_user_qq} 的所有照片。")


def main():
    """脚本主入口点。"""
    # --- 用户配置 ---
    main_user_qq = USER_CONFIG["main_user_qq"]
    main_user_pass = USER_CONFIG["main_user_pass"]
    dest_users_qq = USER_CONFIG["dest_users_qq"]

    # --- 全局应用配置覆盖 (可选) ---
    # 如果特定运行需要，您可以在此处覆盖 APP_CONFIG 的部分内容
    # 示例:
    # APP_CONFIG["max_workers"] = 10
    # APP_CONFIG["timeout_init"] = 45
    # APP_CONFIG["is_api_debug"] = True
    # APP_CONFIG["exclude_albums"] = ["旧照片", "随拍"]

    if main_user_qq == "123456":  # 检查是否使用了默认的QQ号
        print("请在脚本中更新 'main_user_qq' 和 'dest_users_qq'。")
        return

    try:
        qzone_manager = QzonePhotoManager(main_user_qq, main_user_pass)
    except Exception as e:
        print(f"初始化 QzonePhotoManager 失败: {e}")
        return

    print("登录过程已完成 (或已启动手动登录)。")

    for target_qq in dest_users_qq:
        target_qq_str = str(target_qq)  # 确保是字符串
        print(f"\n--- 正在处理用户: {target_qq_str} ---")
        try:
            qzone_manager.download_all_photos_for_user(target_qq_str)
        except Exception as e:
            print(f"处理用户 {target_qq_str} 时发生意外错误: {e}")
            import traceback

            traceback.print_exc()  # 打印堆栈跟踪以进行调试
        print(f"--- 完成处理用户: {target_qq_str} ---")

    print("\n所有指定用户处理完毕。")


if __name__ == "__main__":
    main()
