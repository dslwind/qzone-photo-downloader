"""
工具函数模块
"""

import os
import requests

from config.config_manager import APP_CONFIG, is_path_valid, sanitize_filename_component, get_save_directory


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