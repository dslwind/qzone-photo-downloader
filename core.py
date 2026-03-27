"""
QQ空间相册下载器 - 核心模块

包含所有共享逻辑：配置加载、工具函数、QzonePhotoManager、save_photo_worker。
由 main.py（CLI）和 gui.py（GUI）共同导入使用。
"""

import errno
import json
import json_repair
import logging
import os
import random
import re
import shutil
import sys
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction

import piexif
import requests
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

CONFIG_FILE = "config.json"
CONFIG = {}

APP_CONFIG: dict = {}
USER_CONFIG: dict = {}


def load_config(exit_on_error: bool = True) -> bool:
    """从配置文件加载配置。

    Args:
        exit_on_error: 若为 True，加载失败时调用 sys.exit(1)；
                       若为 False，加载失败时返回 False，由调用方处理。

    Returns:
        bool: 加载成功返回 True，失败且 exit_on_error=False 时返回 False。
    """
    global CONFIG
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            CONFIG = json.load(f)
        logger.info(f"成功从 {CONFIG_FILE} 加载配置。")
    except FileNotFoundError:
        msg = f"错误: 配置文件 {CONFIG_FILE} 未找到。请确保它存在。"
        logger.error(msg)
        if exit_on_error:
            sys.exit(1)
        return False
    except json.JSONDecodeError as e:
        msg = f"错误: 解析配置文件 {CONFIG_FILE} 失败: {e}"
        logger.error(msg)
        if exit_on_error:
            sys.exit(1)
        return False
    except Exception as e:
        msg = f"加载配置文件时发生意外错误: {e}"
        logger.error(msg)
        if exit_on_error:
            sys.exit(1)
        return False

    # 原地更新而非重新赋值，确保所有模块通过 from core import 拿到的引用同步更新
    APP_CONFIG.update({
        "max_workers": CONFIG.get("max_workers", 10),
        "timeout_init": CONFIG.get("timeout_init", 30),
        "max_attempts": CONFIG.get("max_attempts", 3),
        "is_api_debug": CONFIG.get("is_api_debug", True),
        "exclude_albums": [
            name for name in CONFIG.get("exclude_albums", []) if str(name).strip()
        ],
        "download_path": CONFIG.get("download_path", "qzone_photo"),
    })

    USER_CONFIG.update({
        "main_user_qq": CONFIG.get("main_user_qq", "123456"),
        "main_user_pass": CONFIG.get("main_user_pass", ""),
        "dest_users_qq": CONFIG.get("dest_users_qq", ["123456"]),
    })
    return True


# ---------------------------------------------------------------------------
# 命名元组
# ---------------------------------------------------------------------------

QzoneAlbum = namedtuple("QzoneAlbum", ["uid", "name", "count"])
QzonePhoto = namedtuple(
    "QzonePhoto",
    [
        "url",
        "name",
        "album_name",
        "is_video",
        "pic_key",
        "exif_data",   # dict，来自 photo_data["exif"]
        "shoottime",   # str，来自 rawshoottime，含时分秒
        "uploadtime",  # str，来自 uploadtime，含时分秒
        "cameratype",  # str，完整设备名，如 "Apple iPhone 15 Pro Max"
    ],
)

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _str_to_rational(value_str: str) -> tuple | None:
    """将字符串转为 EXIF rational 元组 (分子, 分母)。"""
    if not value_str or not value_str.strip():
        return None
    try:
        s = value_str.strip()
        if "/" in s:
            num, den = s.split("/", 1)
            num, den = int(num), int(den)
            return None if num < 0 or den <= 0 else (num, den)
        frac = Fraction(float(s)).limit_denominator(1_000_000)
        return None if frac < 0 else (frac.numerator, frac.denominator)
    except Exception:
        return None


def _str_to_srational(value_str: str) -> tuple | None:
    """将字符串转为 EXIF signed rational 元组。"""
    if not value_str or not value_str.strip():
        return None
    try:
        s = value_str.strip()
        if "/" in s:
            num, den = s.split("/", 1)
            num, den = int(num), int(den)
            return None if den <= 0 else (num, den)
        frac = Fraction(float(s)).limit_denominator(1_000_000)
        return (frac.numerator, frac.denominator)
    except Exception:
        return None


def _str_to_short(value_str: str) -> int | None:
    """将字符串转为 EXIF SHORT 整数。"""
    if not value_str or not value_str.strip():
        return None
    try:
        v = int(float(value_str.strip()))
        return None if v < 0 else v
    except Exception:
        return None


def _ascii_bytes(s: str) -> bytes:
    """编码为 ASCII bytes，非 ASCII 字符用 ? 替换。"""
    return s.encode("ascii", errors="replace")


def _datetime_str_to_exif(dt_str: str) -> str | None:
    """
    将 API 返回的时间字符串转换为 EXIF 标准格式 "YYYY:MM:DD HH:MM:SS"。
    支持：
      - "2024-11-24 17:42:10"（rawshoottime、uploadtime 格式）
      - "2024:11:24 17:42:10"（exif.originalTime 格式，已是标准格式）
    """
    if not dt_str or not str(dt_str).strip() or str(dt_str).strip() == "0":
        return None
    s = str(dt_str).strip()
    if re.match(r"^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$", s):
        return s
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2}) (\d{2}:\d{2}:\d{2})$", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)} {m.group(4)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}:{m.group(2)}:{m.group(3)} 00:00:00"
    return None


def write_exif_to_photo(
    file_path: str,
    exif_data: dict,
    shoottime: str,
    uploadtime: str,
    cameratype: str = "",
) -> None:
    """
    将 API 返回的元数据回写至 JPEG 文件的 EXIF，并对所有文件类型设置 mtime。

    - EXIF 字段写入仅对 .jpg/.jpeg 有效，出错时静默跳过。
    - 文件修改时间（mtime）对所有文件类型生效。
    """
    if file_path.lower().endswith((".jpg", ".jpeg")):
        try:
            try:
                exif_dict = piexif.load(file_path)
            except Exception:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}}

            zeroth = exif_dict.setdefault("0th", {})
            exif   = exif_dict.setdefault("Exif", {})

            # --- 相机厂商 / 完整型号 ---
            make       = (exif_data.get("make")  or "").strip()
            exif_model = (exif_data.get("model") or "").strip()
            cameratype = (cameratype or "").strip()

            extracted_brand = ""
            if not make and cameratype:
                known_makes = [
                    "Apple", "Samsung", "SONY", "HUAWEI", "Xiaomi", "ASUS",
                    "Google", "OnePlus", "OPPO", "vivo", "Canon", "Nikon",
                    "Fujifilm", "Panasonic", "Leica", "DJI", "GoPro",
                ]
                for brand in known_makes:
                    if cameratype.startswith(brand):
                        extracted_brand = brand
                        make = brand
                        break

            if exif_model:
                zeroth[piexif.ImageIFD.Model] = _ascii_bytes(exif_model)
            elif cameratype:
                model_str = (
                    cameratype[len(extracted_brand):].strip()
                    if extracted_brand
                    else cameratype
                )
                if model_str:
                    zeroth[piexif.ImageIFD.Model] = _ascii_bytes(model_str)

            if make:
                zeroth[piexif.ImageIFD.Make] = _ascii_bytes(make)

            # --- 拍摄时间 → DateTimeOriginal ---
            original_time = _datetime_str_to_exif(exif_data.get("originalTime", ""))
            if original_time:
                exif[piexif.ExifIFD.DateTimeOriginal] = _ascii_bytes(original_time)
            elif shoottime:
                shoot_exif = _datetime_str_to_exif(shoottime)
                if shoot_exif:
                    exif[piexif.ExifIFD.DateTimeOriginal] = _ascii_bytes(shoot_exif)
            else:
                shoot_exif = _datetime_str_to_exif(uploadtime)
                if shoot_exif:
                    exif[piexif.ExifIFD.DateTimeOriginal] = _ascii_bytes(shoot_exif)

            r = _str_to_rational(exif_data.get("exposureTime", ""))
            if r:
                exif[piexif.ExifIFD.ExposureTime] = r

            r = _str_to_rational(exif_data.get("fnumber", ""))
            if r:
                exif[piexif.ExifIFD.FNumber] = r

            iso = _str_to_short(exif_data.get("iso", ""))
            if iso is not None:
                exif[piexif.ExifIFD.ISOSpeedRatings] = iso

            r = _str_to_rational(exif_data.get("focalLength", ""))
            if r:
                exif[piexif.ExifIFD.FocalLength] = r

            flash = _str_to_short(exif_data.get("flash", ""))
            if flash is not None:
                exif[piexif.ExifIFD.Flash] = flash

            em = _str_to_short(exif_data.get("exposureMode", ""))
            if em is not None:
                exif[piexif.ExifIFD.ExposureMode] = em

            ep = _str_to_short(exif_data.get("exposureProgram", ""))
            if ep is not None:
                exif[piexif.ExifIFD.ExposureProgram] = ep

            mm = _str_to_short(exif_data.get("meteringMode", ""))
            if mm is not None:
                exif[piexif.ExifIFD.MeteringMode] = mm

            sr = _str_to_srational(exif_data.get("exposureCompensation", ""))
            if sr is not None:
                exif[piexif.ExifIFD.ExposureBiasValue] = sr

            lens = (exif_data.get("lensModel") or "").strip()
            if lens:
                exif[piexif.ExifIFD.LensModel] = _ascii_bytes(lens)

            exif_bytes = piexif.dump(exif_dict)
            piexif.insert(exif_bytes, file_path)

        except Exception as e:
            logger.warning(f"[EXIF] 回写失败，文件 {file_path}: {e}")

    # 对所有文件类型设置 mtime
    dt_str = (
        _datetime_str_to_exif(exif_data.get("originalTime", ""))
        or _datetime_str_to_exif(shoottime)
        or _datetime_str_to_exif(uploadtime)
    )
    if dt_str:
        try:
            t = time.mktime(time.strptime(dt_str, "%Y:%m:%d %H:%M:%S"))
            os.utime(file_path, (t, t))
        except Exception as e:
            logger.warning(f"[mtime] 写入文件修改日期失败，文件 {file_path}: {e}")


def get_script_directory() -> str:
    """获取脚本文件所在的绝对路径。"""
    return os.path.dirname(os.path.realpath(__file__))


def is_path_valid(pathname: str) -> bool:
    """检查给定路径名在当前操作系统中是否（可能）有效。"""
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
        elif hasattr(exc, "winerror") and exc.winerror == 123:
            return False
        elif exc.errno in [errno.ENAMETOOLONG, errno.ELOOP]:
            return False
        elif exc.errno == errno.EINVAL:
            drive, tail = os.path.splitdrive(normalized_pathname)
            if os.name == "nt" and drive == normalized_pathname and not tail:
                return True
            return False
        else:
            return False
    except Exception:
        return False


def sanitize_filename_component(name_component: str) -> str:
    """安全处理文件名组件，替换所有非法字符为下划线。"""
    if not isinstance(name_component, str):
        raise TypeError("输入必须是字符串类型")
    illegal_chars = r'[\/\\:*?"<>|\0]'
    return re.sub(illegal_chars, "_", name_component)


def _detect_image_extension(content: bytes) -> str:
    """通过文件头魔术字节判断图片格式，返回对应扩展名。"""
    if content[:3] == b"\xff\xd8\xff":
        return ".jpeg"
    if content[:4] == b"\x89PNG":
        return ".png"
    if content[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return ".jpeg"


def get_save_directory(user_qq: str) -> str:
    """确定给定用户的照片保存目录。"""
    download_path = APP_CONFIG.get("download_path", "downloads")
    return os.path.join(get_script_directory(), download_path, str(user_qq))


def download_photo_network_helper(
    request_cookies: dict | None, url: str, timeout: int
) -> requests.Response:
    """
    下载照片的辅助函数：优先携带 cookies 请求，失败时再回退到无 cookies 请求。

    Raises:
        requests.exceptions.RequestException: 当所有网络请求都失败时
    """
    try:
        if request_cookies:
            return requests.get(url, cookies=request_cookies, timeout=timeout)
        return requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as first_error:
        if request_cookies:
            logger.warning(f"[警告] 携带 cookies 下载失败，尝试无 cookies 重试: {first_error}")
            try:
                return requests.get(url, timeout=timeout)
            except requests.exceptions.RequestException as second_error:
                raise ConnectionError(
                    f"[网络错误] 尝试下载 {url} 时出错（cookies/无cookies均失败）: {second_error}"
                ) from first_error
        raise ConnectionError(
            f"[网络错误] 尝试下载 {url} 时出错: {first_error}"
        ) from first_error


def save_photo_worker(args: tuple) -> None:
    """
    工作函数，用于下载并保存单张照片或视频。在线程池中运行。

    args 元组字段：
        request_cookies, user_qq, album_index, album_name, photo_index,
        photo, log_func, progress_func, is_stopped_func, qzone_manager,
        album_id, dest_user_qq
    """
    (
        request_cookies,
        user_qq,
        album_index,
        album_name,
        photo_index,
        photo,
        log_func,       # callable(str)，输出日志
        progress_func,  # callable(int)，更新进度；CLI 模式传 None 或 noop
        is_stopped_func,
        qzone_manager,
        album_id,
        dest_user_qq,
    ) = args

    def _log(msg: str) -> None:
        if log_func:
            log_func(msg)
        logger.info(msg)

    def _progress(n: int) -> None:
        if progress_func:
            progress_func(n)

    if is_stopped_func():
        _log(f"[停止] 照片下载任务已停止，跳过：相册 '{album_name}', 照片 {photo_index + 1}")
        _progress(1)
        return

    album_save_path = os.path.join(
        get_save_directory(user_qq), sanitize_filename_component(album_name.strip())
    )
    if not os.path.exists(album_save_path):
        try:
            os.makedirs(album_save_path, exist_ok=True)
        except OSError as e:
            _log(f"[错误] 无法创建目录 {album_save_path}: {e}")
            return

    photo_name_sanitized = sanitize_filename_component(photo.name)
    base_filename = f"{photo_index}_{photo_name_sanitized}"

    download_url = photo.url
    file_extension = ".jpeg"

    if photo.is_video:
        _log(f"[检测到视频] 正在获取真实视频下载链接: '{photo.name}'")
        video_url = qzone_manager.get_video_download_url(dest_user_qq, album_id, photo.pic_key)

        if video_url:
            download_url = video_url
            file_extension = ".mp4"
            final_filename = f"{base_filename}{file_extension}"
            full_photo_path = os.path.join(album_save_path, final_filename)

            if not is_path_valid(full_photo_path):
                _log(f"[警告] 原始视频文件名无效: {final_filename}。将使用随机名称。")
                final_filename = f"random_name_{album_index}_{photo_index}{file_extension}"
                full_photo_path = os.path.join(album_save_path, final_filename)
                if not is_path_valid(full_photo_path):
                    _log(f"[错误] 备用视频文件名也无效，跳过视频: {photo.url}")
                    _progress(1)
                    return

            if os.path.exists(full_photo_path):
                _log(f"[本地已存在] 相册 '{album_name}', 视频 {photo_index + 1} ('{photo.name}')")
                _progress(1)
                return

            _log(f"[成功] 获取到视频 {base_filename} 下载链接")
        else:
            _log(f"[失败] 无法获取视频 {base_filename} 下载链接，将下载视频封面图代替")
            base_filename = f"{photo_index}_{photo_name_sanitized}_视频封面"
            final_filename = ""
            full_photo_path = ""
    else:
        final_filename = ""
        full_photo_path = ""

    url = download_url.replace("\\", "")
    attempts = 0
    current_timeout = APP_CONFIG["timeout_init"]

    download_type = "视频" if photo.is_video and file_extension == ".mp4" else "照片"
    _log(f"[开始下载] 相册 '{album_name}', {download_type} {photo_index + 1} ('{photo.name}')")

    while attempts < APP_CONFIG["max_attempts"]:
        if is_stopped_func():
            _log(f"[停止] 照片下载任务已停止，跳过重试：相册 '{album_name}', 照片 {photo_index + 1}")
            _progress(1)
            return

        try:
            response = download_photo_network_helper(request_cookies, url, current_timeout)
            response.raise_for_status()

            if not (photo.is_video and file_extension == ".mp4"):
                file_extension = _detect_image_extension(response.content)
                final_filename = f"{base_filename}{file_extension}"
                full_photo_path = os.path.join(album_save_path, final_filename)

                if not is_path_valid(full_photo_path):
                    _log(f"[警告] 原始文件名无效: {final_filename}。将使用随机名称。")
                    final_filename = f"random_name_{album_index}_{photo_index}{file_extension}"
                    full_photo_path = os.path.join(album_save_path, final_filename)
                    if not is_path_valid(full_photo_path):
                        _log(f"[错误] 备用文件名也无效，跳过照片: {photo.url}")
                        _progress(1)
                        return

                if os.path.exists(full_photo_path):
                    _log(f"[本地已存在] 相册 '{album_name}', 照片 {photo_index + 1} ('{photo.name}')")
                    _progress(1)
                    return

            with open(full_photo_path, "wb") as f:
                f.write(response.content)

            write_exif_to_photo(
                full_photo_path,
                photo.exif_data,
                photo.shoottime,
                photo.uploadtime,
                photo.cameratype,
            )

            _log(
                f"[下载成功] 相册 '{album_name}', 照片 {photo_index + 1}。"
                f"尝试次数: {attempts + 1}, 超时时间: {current_timeout}s"
            )
            _progress(1)
            return

        except (
            requests.exceptions.ReadTimeout,
            requests.exceptions.ConnectionError,
        ) as e:
            attempts += 1
            current_timeout += 5
            _log(
                f"[重试下载] 相册 '{album_name}', 照片 {photo_index + 1}。"
                f"尝试 {attempts}/{APP_CONFIG['max_attempts']}, "
                f"新超时时间: {current_timeout}s。错误: {e}"
            )
        except requests.exceptions.HTTPError as e:
            _log(
                f"[HTTP 错误] 下载 {url} 失败 (相册 '{album_name}', 照片 {photo_index + 1})。"
                f"状态码: {e.response.status_code}。中止下载此照片。"
            )
            _progress(1)
            return
        except Exception as e:
            attempts += 1
            _log(
                f"[意外错误] 重试下载 {url}, 相册 '{album_name}', 照片 {photo_index + 1}。"
                f"尝试 {attempts}/{APP_CONFIG['max_attempts']}。错误: {e}"
            )

    _log(
        f"[下载失败] 用户: {user_qq}, 相册 '{album_name}', 照片 {photo_index + 1} "
        f"('{photo.name}') URL: {photo.url} (尝试 {APP_CONFIG['max_attempts']} 次后)"
    )
    _progress(1)


# ---------------------------------------------------------------------------
# QzonePhotoManager
# ---------------------------------------------------------------------------


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
        "&idcNum=4&callbackFun=shine{fn}&mode=2&sortOrder=2"
        "&pageStart={pageStart}&pageNum={pageNum}&callback=shine{fn}_Callback"
    )

    PHOTO_LIST_URL_TEMPLATE = (
        "https://h5.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"
        "cgi_list_photo?g_tk={gtk}&t={t}&mode=0&idcNum=4&hostUin={dest_user}"
        "&topicId={album_id}&noTopic=0&uin={user}&pageStart={pageStart}&pageNum={pageNum}"
        "&skipCmtCount=0&singleurl=1&batchId=&notice=0&appid=4&inCharset=utf-8&outCharset=utf-8"
        "&source=qzone&plat=qzone&outstyle=json&format=jsonp&json_esc=1&question=&answer="
        "&callbackFun=shine0&callback=shine0_Callback"
    )

    VIDEO_DETAIL_URL_TEMPLATE = (
        "https://user.qzone.qq.com/proxy/domain/photo.qzone.qq.com/fcgi-bin/"
        "cgi_floatview_photo_list_v2?g_tk={gtk}&t={t}&topicId={album_id}&picKey={pic_key}"
        "&shootTime=&cmtOrder=1&fupdate=1&plat=qzone&source=qzone&cmtNum=10&likeNum=5"
        "&inCharset=utf-8&outCharset=utf-8&callbackFun=viewer&offset=0&number=15"
        "&uin={user}&hostUin={dest_user}&appid=4&isFirst=1&sortOrder=1&showMode=1"
        "&need_private_comment=1&prevNum=9&postNum=18"
    )

    def __init__(self, user_qq: str, log_signal=None, is_stopped_func=None):
        """
        初始化 QzonePhotoManager。

        Args:
            user_qq:         登录用户的 QQ 号
            log_signal:      可选，PyQt signal（有 .emit(str) 方法），用于 GUI 日志输出
            is_stopped_func: 可选，无参可调用对象，返回 True 时中断操作
        """
        self.user_qq = str(user_qq)
        self.cookies: dict = {}
        self.session = requests.Session()
        self.qzone_g_tk = ""
        self.log_signal = log_signal
        self.is_stopped_func = is_stopped_func if is_stopped_func is not None else (lambda: False)
        self.total_albums = 0

    def _emit_log(self, message: str) -> None:
        """向 GUI 信号和 logger 双路输出日志。"""
        if self.log_signal:
            self.log_signal.emit(message)  # type: ignore[attr-defined]
        logger.info(message)

    def _check_cookie_validity(self) -> bool:
        """通过相册列表 API 验证当前 cookie 是否仍有效。"""
        if not self.cookies or not self.qzone_g_tk:
            self._emit_log("Cookie 或 g_tk 为空，无法验证有效性。")
            return False

        check_url = self.ALBUM_LIST_URL_TEMPLATE.format(
            gtk=self.qzone_g_tk,
            t=random.random(),
            dest_user=self.user_qq,
            user=self.user_qq,
        )
        try:
            response = requests.get(
                check_url, cookies=self.cookies, timeout=APP_CONFIG["timeout_init"]
            )
            response.raise_for_status()
            text = response.text
            json_str = None
            if text.startswith("shine0_Callback(") and text.endswith(");"):
                json_str = text[len("shine0_Callback("):-2]
            elif text.startswith("_Callback(") and text.endswith(");"):
                json_str = text[len("_Callback("):-2]
            if json_str is None:
                self._emit_log("Cookie 验证失败，API 响应格式不正确。")
                return False
            data = json.loads(json_str)
            if data.get("code", -1) == 0:
                self._emit_log("Cookie 验证成功，可以继续使用。")
                return True
            self._emit_log(f"Cookie 验证失败，API 返回错误码: {data.get('code', '未知')}")
            return False
        except Exception as e:
            self._emit_log(f"Cookie 验证过程中发生错误: {e}")
            return False

    def _set_cookies_and_gtk(self, cookies: dict, g_tk: str) -> None:
        """直接注入 cookie 和 g_tk，用于复用已有登录信息。"""
        self.cookies = cookies
        self.qzone_g_tk = g_tk
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value)
        self._emit_log("已设置 cookie 和 g_tk。")

    def _resolve_chromedriver_path(self) -> str:
        """优先级：脚本目录 > 系统 PATH > webdriver_manager 自动下载。"""
        driver_name = "chromedriver.exe" if sys.platform == "win32" else "chromedriver"
        local_path = os.path.join(get_script_directory(), driver_name)
        if os.path.exists(local_path):
            return local_path
        system_driver = shutil.which(driver_name)
        if system_driver:
            return system_driver
        self._emit_log("未在脚本目录或系统 PATH 中找到 ChromeDriver，尝试自动下载匹配版本...")
        return ChromeDriverManager().install()

    def _apply_anti_detection_patches(self, driver: webdriver.Chrome) -> None:
        """尽力应用浏览器伪装设置；失败时仅记录告警。"""
        try:
            driver.execute_cdp_cmd(
                "Network.setUserAgentOverride",
                {
                    "userAgent": driver.execute_script(
                        "return navigator.userAgent"
                    ).replace("Headless", "")
                },
            )
        except Exception as e:
            self._emit_log(f"[警告] 设置 User-Agent 覆盖失败，继续执行: {e}")

        try:
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
            self._emit_log(f"[警告] 注入 webdriver 伪装脚本失败，继续执行: {e}")

    def _login_and_get_cookies(self) -> None:
        """使用 Selenium 打开 QQ 空间，等待用户手动登录后抓取 cookie。"""
        self._emit_log("尝试启动 Chrome 进行登录...")
        options = webdriver.ChromeOptions()
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--lang=zh-CN")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver_path = None
        try:
            driver_path = self._resolve_chromedriver_path()
            service = ChromeService(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            self._apply_anti_detection_patches(driver)
        except Exception as e:
            self._emit_log(f"启动 ChromeDriver 失败。错误: {e}")
            self._emit_log(f"尝试使用的驱动路径: {driver_path}")
            self._emit_log(
                "如果问题仍然存在，请手动下载 ChromeDriver: "
                "https://googlechromelabs.github.io/chrome-for-testing"
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
            self._emit_log(f"错误: {LOGIN_TIMEOUT} 秒内未检测到成功登录")
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
            raise RuntimeError("获取 cookie 失败")

        self.cookies = {c["name"]: c["value"] for c in selenium_cookies}
        for name, value in self.cookies.items():
            self.session.cookies.set(name, value)

        p_skey = self.cookies.get("p_skey") or self.cookies.get("skey")
        if not p_skey:
            self._emit_log("错误: 在 cookie 中未找到 'p_skey' 或 'skey'。无法计算 g_tk。")
            self._emit_log(f"可用的 cookies: {list(self.cookies.keys())}")
            logger.error("在 cookie 中未找到 'p_skey' 或 'skey'。")
            driver.quit()
            raise RuntimeError("无法计算 g_tk")

        self.qzone_g_tk = self._calculate_g_tk(p_skey)
        self._emit_log("成功获取 cookie 和 g_tk。")
        if APP_CONFIG.get("is_api_debug"):
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
            response = requests.get(url, cookies=self.cookies, timeout=timeout_seconds)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            self._emit_log(f"API 请求失败，URL: {url}: {e}")
            return {}

        text_content = response.text
        if text_content.startswith("shine0_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("shine0_Callback("):-2]
        elif text_content.startswith("viewer_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("viewer_Callback("):-2]
        elif text_content.startswith("_Callback(") and text_content.endswith(");"):
            json_str = text_content[len("_Callback("):-2]
        else:
            match = re.match(r"^\w+_Callback\((.*)\);?$", text_content, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                if APP_CONFIG.get("is_api_debug"):
                    self._emit_log(
                        f"意外的 API 响应格式 (没有已知的 JSONP 包装器): {text_content[:200]}"
                    )
                json_str = text_content

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解码失败，尝试修复: {e}")
            try:
                repaired = json_repair.repair_json(json_str, return_objects=True)
                if repaired:
                    logger.info("JSON 修复成功")
                    return repaired
            except Exception as repair_err:
                logger.error(f"JSON 修复也失败: {repair_err}")
            self._emit_log(f"JSON 解码失败，响应内容: {json_str[:200]}... 错误: {e}")
            if APP_CONFIG.get("is_api_debug"):
                self._emit_log(f"有问题的完整 JSON 字符串: {json_str}")
            return {}

    def get_video_download_url(
        self, dest_user_qq: str, album_id: str, pic_key: str
    ) -> str:
        """获取视频的真实下载 URL（MP4）。失败返回空字符串。"""
        url = self.VIDEO_DETAIL_URL_TEMPLATE.format(
            gtk=self.qzone_g_tk,
            t=random.random(),
            album_id=album_id,
            pic_key=pic_key,
            user=self.user_qq,
            dest_user=dest_user_qq,
        )
        if APP_CONFIG.get("is_api_debug"):
            self._emit_log(f"正在获取视频详情: {url}")

        data = self._access_qzone_api(url)
        if APP_CONFIG.get("is_api_debug"):
            self._emit_log(
                f"视频详情 API 响应: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}"
            )

        if not data or not data.get("data"):
            self._emit_log(f"获取视频详情失败，pic_key: {pic_key}")
            return ""

        try:
            photos = data["data"].get("photos", [])
            if not photos:
                self._emit_log("视频详情响应中没有找到 photos 数据")
                return ""

            photo_data = None
            for photo in photos:
                if photo.get("picKey") == pic_key or photo.get("lloc") == pic_key:
                    photo_data = photo
                    break

            if not photo_data:
                for photo in photos:
                    if photo.get("is_video") or photo.get("video_info"):
                        photo_data = photo
                        break

            if not photo_data:
                photo_data = photos[0]

            video_info = photo_data.get("video_info", {})
            if not video_info:
                self._emit_log(
                    f"照片数据中没有 video_info 字段，is_video={photo_data.get('is_video')}"
                )
                return ""

            download_url = video_info.get("download_url", "")
            if download_url:
                self._emit_log(f"成功获取视频下载 URL: {download_url[:100]}...")
                return download_url

            if video_info.get("video_url"):
                self._emit_log("警告: 仅找到 m3u8 格式的视频 URL，当前版本暂不支持下载")
                return ""

            self._emit_log("video_info 中没有可用的下载 URL")
            return ""

        except Exception as e:
            self._emit_log(f"解析视频详情时出错: {e}")
            logger.exception("解析视频详情时出错")
            return ""

    def get_albums_by_page(self, dest_user_qq: str) -> list[QzoneAlbum]:
        """分页获取目标用户的所有相册列表。"""
        self.total_albums = 0
        page_start = 0
        all_albums: list[QzoneAlbum] = []

        while True:
            if self.is_stopped_func():
                self._emit_log("[停止] 相册获取任务已停止。")
                break
            albums = self.get_albums(dest_user_qq, page_start)
            if not albums:
                break
            all_albums.extend(albums)
            page_start += len(albums)
            # 已获取到全部相册（total_albums 首次从 API 中读取）
            if self.total_albums > 0 and page_start >= self.total_albums:
                break

        return all_albums

    def get_albums(
        self, dest_user_qq: str, pageStart: int = 0, pageNum: int = 32
    ) -> list[QzoneAlbum]:
        """获取给定用户指定分页的相册列表。"""
        albums: list[QzoneAlbum] = []
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
                fn=0,
            )

        if APP_CONFIG.get("is_api_debug"):
            self._emit_log(f"正在从以下地址获取相册: {url}")

        data = self._access_qzone_api(url)
        if APP_CONFIG.get("is_api_debug"):
            dump = json.dumps(data, indent=2, ensure_ascii=False)
            self._emit_log(f"相册 API 响应数据: {dump}")

        if not data or not data.get("data"):
            logger.warning(f"获取相册列表失败或没有数据：{data}")
            return albums

        album_data = data["data"]
        if self.total_albums == 0:
            self.total_albums = album_data.get("albumsInUser", 0)

        if "albumListModeSort" in album_data:
            album_list = album_data["albumListModeSort"]
        elif "albumListModeClass" in album_data:
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
                    QzoneAlbum(uid=album["id"], name=album["name"], count=album["total"])
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

        if APP_CONFIG.get("is_api_debug"):
            self._emit_log(f"找到的相册: {albums}")
        return albums

    def get_photos_from_album(
        self, dest_user_qq: str, album: QzoneAlbum
    ) -> list[QzonePhoto]:
        """从特定相册获取所有照片，支持分页。"""
        photos: list[QzonePhoto] = []
        page_start = 0
        page_num_to_fetch = 500

        while True:
            if self.is_stopped_func():
                self._emit_log(
                    f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 的后续页面。"
                )
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
            if APP_CONFIG.get("is_api_debug"):
                self._emit_log(f"正在从以下地址获取照片: {url}")

            data = self._access_qzone_api(url)
            if APP_CONFIG.get("is_api_debug"):
                self._emit_log(
                    f"相册 '{album.name}' (页码起点 {page_start}) 的照片列表 API 响应: "
                    f"{json.dumps(data, indent=2, ensure_ascii=False)}"
                )

            if not data or not data.get("data"):
                if data and data.get("code", 0) != 0:
                    self._emit_log(
                        f"相册 '{album.name}' API 错误: code {data.get('code')}, "
                        f"message: {data.get('message')}, subcode: {data.get('subcode')}"
                    )
                break

            api_data = data["data"]
            total_in_album = api_data.get("totalInAlbum", 0)
            photos_in_page = api_data.get("totalInPage", 0)

            if total_in_album == 0:
                self._emit_log(f"相册 '{album.name}' (ID: {album.uid}) 为空或没有可访问的照片。")
                break

            photo_list_data = api_data.get("photoList")
            if not photo_list_data:
                if photos_in_page == 0 and page_start > 0:
                    self._emit_log(
                        f"在相册 '{album.name}' 中，页码起点 {page_start} 之后未找到更多照片。"
                    )
                elif photos_in_page == 0 and page_start == 0:
                    self._emit_log(f"在相册 '{album.name}' 的第一页未找到照片。")
                break

            for photo_data in photo_list_data:
                if self.is_stopped_func():
                    self._emit_log(
                        f"[停止] 照片获取任务已停止，跳过相册 '{album.name}' 中的剩余照片。"
                    )
                    return photos

                pic_url = (
                    photo_data.get("raw")
                    or photo_data.get("origin_url")
                    or photo_data.get("url")
                    or photo_data.get("custom_url")
                )
                if not pic_url and "lloc" in photo_data:
                    pic_url = photo_data["lloc"]
                if not pic_url and "sloc" in photo_data:
                    pic_url = photo_data["sloc"]

                if not pic_url:
                    if APP_CONFIG.get("is_api_debug"):
                        self._emit_log(
                            f"跳过没有 URL 的照片: {photo_data.get('name')}, 数据: {photo_data}"
                        )
                    continue

                pic_key = photo_data.get("lloc") or photo_data.get("sloc") or ""
                photos.append(
                    QzonePhoto(
                        url=pic_url,
                        name=photo_data.get("name", "untitled").strip(),
                        album_name=album.name,
                        is_video=bool(
                            photo_data.get("is_video", False)
                            or photo_data.get("phototype") == "video"
                        ),
                        pic_key=pic_key,
                        exif_data=photo_data.get("exif", {}),
                        shoottime=photo_data.get("rawshoottime", ""),
                        uploadtime=photo_data.get("uploadtime", ""),
                        cameratype=photo_data.get("cameratype", "").strip(),
                    )
                )

            if len(photos) >= total_in_album or photos_in_page == 0:
                break

            page_start += photos_in_page

        return photos

    def download_all_photos_for_user(
        self,
        dest_user_qq: str,
        progress_func=None,
    ) -> None:
        """
        下载目标用户所有可访问的照片。

        Args:
            dest_user_qq:  目标用户 QQ 号
            progress_func: 可选，callable(int)，接收负数表示任务总量，正数 1 表示完成一个
        """
        albums = self.get_albums_by_page(dest_user_qq)
        if not albums:
            self._emit_log(f"未找到用户 {dest_user_qq} 的相册或无法访问。")
            if progress_func:
                progress_func(0)
            return

        self._emit_log(f"为用户 {dest_user_qq} 找到 {len(albums)} 个相册:")
        for i, album_item in enumerate(albums):
            self._emit_log(
                f"  {i+1}. {album_item.name} (ID: {album_item.uid}, 照片数量: {album_item.count})"
            )

        all_photo_tasks = []
        user_save_dir = get_save_directory(dest_user_qq)
        os.makedirs(user_save_dir, exist_ok=True)

        for album_index, album in enumerate(albums):
            if self.is_stopped_func():
                self._emit_log("[停止] 相册处理任务已停止，跳过后续相册。")
                break

            if album.name in APP_CONFIG.get("exclude_albums", []):
                self._emit_log(f"跳过排除的相册: '{album.name}'")
                continue

            album_path = os.path.join(
                user_save_dir, sanitize_filename_component(album.name.strip())
            )
            try:
                os.makedirs(album_path, exist_ok=True)
            except OSError as e:
                self._emit_log(f"为相册 '{album.name}' 创建目录时出错: {e}。跳过此相册。")
                continue

            self._emit_log(f"\n正在获取相册 '{album.name}' 的照片 (预计 {album.count} 张)...")
            photos_in_album = self.get_photos_from_album(dest_user_qq, album)
            self._emit_log(
                f"为相册 '{album.name}' 找到 {len(photos_in_album)} 个照片条目。准备下载。"
            )

            for photo_idx, photo_item in enumerate(photos_in_album):
                if self.is_stopped_func():
                    self._emit_log(
                        f"[停止] 照片任务添加已停止，跳过相册 '{album.name}' 中的剩余照片。"
                    )
                    break
                all_photo_tasks.append(
                    (
                        dict(self.cookies),
                        dest_user_qq,
                        album_index,
                        album.name,
                        photo_idx,
                        photo_item,
                        self.log_signal.emit if self.log_signal else None,
                        progress_func,
                        self.is_stopped_func,
                        self,
                        album.uid,
                        dest_user_qq,
                    )
                )

        if not all_photo_tasks:
            self._emit_log(f"没有为用户 {dest_user_qq} 下载的照片。")
            if progress_func:
                progress_func(0)
            return

        self._emit_log(
            f"\n开始下载 {len(all_photo_tasks)} 张照片，"
            f"使用 {APP_CONFIG['max_workers']} 个线程..."
        )
        if progress_func:
            progress_func(-len(all_photo_tasks))

        with ThreadPoolExecutor(max_workers=APP_CONFIG["max_workers"]) as executor:
            list(executor.map(save_photo_worker, all_photo_tasks))

        if not self.is_stopped_func():
            self._emit_log(f"\n完成处理用户 {dest_user_qq} 的所有照片。")
