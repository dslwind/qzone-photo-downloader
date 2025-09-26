"""
下载器模块
"""

import os
from concurrent.futures import ThreadPoolExecutor

from config.config_manager import (APP_CONFIG, get_save_directory,
                                   sanitize_filename_component)
from core.qzone_manager import QzonePhoto
from utils.helpers import download_photo_network_helper, save_photo_worker


def download_all_photos_for_user(qzone_manager, dest_user_qq: str):
    """下载目标用户所有可访问的照片。
    
    Args:
        qzone_manager: QzonePhotoManager实例
        dest_user_qq (str): 目标用户的QQ号
    """
    # 检查cookie是否有效，如果无效则重新登录
    if not qzone_manager._check_cookie_validity():
        qzone_manager._emit_log("检测到cookie已过期，正在重新登录...")
        try:
            qzone_manager._login_and_get_cookies()
            qzone_manager._emit_log("重新登录成功。")
        except Exception as e:
            qzone_manager._emit_log(f"重新登录失败: {e}")
            return

    albums = qzone_manager.get_albums_by_page(dest_user_qq)
    if not albums:
        qzone_manager._emit_log(f"未找到用户 {dest_user_qq} 的相册或无法访问。")
        return

    qzone_manager._emit_log(f"为用户 {dest_user_qq} 找到 {len(albums)} 个相册:")
    for i, album_item in enumerate(albums):
        qzone_manager._emit_log(
            f"  {i+1}. {album_item.name} (ID: {album_item.uid}, 照片数量: {album_item.count})"
        )

    all_photo_tasks = []
    user_save_dir = get_save_directory(dest_user_qq)
    if not os.path.exists(user_save_dir):
        os.makedirs(user_save_dir, exist_ok=True)

    for album_index, album in enumerate(albums):
        if qzone_manager.is_stopped_func():
            qzone_manager._emit_log(f"[停止] 相册处理任务已停止，跳过后续相册。")
            break

        if album.name in APP_CONFIG["exclude_albums"]:
            qzone_manager._emit_log(f"跳过排除的相册: '{album.name}'")
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
                qzone_manager._emit_log(f"为相册 '{album.name}' 创建目录时出错: {e}。跳过此相册。")
                continue

        qzone_manager._emit_log(f"\n正在获取相册 '{album.name}' 的照片 (预计 {album.count} 张)...")
        photos_in_album = qzone_manager.get_photos_from_album(dest_user_qq, album)
        qzone_manager._emit_log(
            f"为相册 '{album.name}' 找到 {len(photos_in_album)} 个照片条目。准备下载。"
        )

        for photo_idx, photo_item in enumerate(photos_in_album):
            if qzone_manager.is_stopped_func():
                qzone_manager._emit_log(f"[停止] 照片任务添加已停止，跳过相册 '{album.name}' 中的剩余照片。")
                break

            all_photo_tasks.append(
                (
                    qzone_manager.session,
                    dest_user_qq,
                    album_index,
                    album.name,
                    photo_idx,
                    photo_item,
                )
            )

    if not all_photo_tasks:
        qzone_manager._emit_log(f"没有为用户 {dest_user_qq} 下载的照片。")
        return

    qzone_manager._emit_log(
        f"\n开始下载 {len(all_photo_tasks)} 张照片，使用 {APP_CONFIG['max_workers']} 个线程..."
    )
    with ThreadPoolExecutor(max_workers=APP_CONFIG["max_workers"]) as executor:
        # map 会运行任务并收集结果 (在这种情况下是 None)
        list(executor.map(save_photo_worker, all_photo_tasks))
        # 使用 list() 来确保所有任务完成后再继续

    qzone_manager._emit_log(f"\n完成处理用户 {dest_user_qq} 的所有照片。")