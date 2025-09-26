"""
GUI下载工作线程模块
"""

import traceback
import logging
from PyQt6.QtCore import QThread, pyqtSignal

from core.qzone_manager import QzonePhotoManager

logger = logging.getLogger(__name__)


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
        # 保存上一次使用的QzonePhotoManager实例，用于复用cookie
        self.previous_qzone_manager = None

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
            
            # 检查是否可以复用之前的cookie
            reuse_cookie = False
            if (self.previous_qzone_manager and 
                self.previous_qzone_manager.user_qq == self.main_user_qq and
                self.previous_qzone_manager.cookies):
                
                self.log_signal.emit("检测到已存在的登录信息，正在验证cookie有效性...")
                if self.previous_qzone_manager._check_cookie_validity():
                    # 复用之前的QzonePhotoManager
                    self.qzone_manager = QzonePhotoManager(self.main_user_qq, log_signal=self.log_signal, is_stopped_func=self.is_stopped)
                    self.qzone_manager._set_cookies_and_gtk(
                        self.previous_qzone_manager.cookies, 
                        str(self.previous_qzone_manager.qzone_g_tk)  # 确保g_tk是字符串类型
                    )
                    reuse_cookie = True
                    self.log_signal.emit("之前的cookie仍然有效，直接使用。")
                else:
                    self.log_signal.emit("之前的cookie已失效，需要重新登录。")
            
            # 如果不能复用cookie，则创建新的QzonePhotoManager并登录
            if not reuse_cookie:
                self.qzone_manager = QzonePhotoManager(self.main_user_qq, log_signal=self.log_signal, is_stopped_func=self.is_stopped)
                if not self.is_stopped():
                    self.qzone_manager._login_and_get_cookies()
            
            if not self.is_stopped() and self.qzone_manager:
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
                    if self.qzone_manager:  # 确保qzone_manager不为None
                        self.qzone_manager.download_all_photos_for_user(target_qq_str)
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
                self.log_signal.emit("下载已停止。")
                logger.info("下载已停止。")

        except Exception as e:
            self.log_signal.emit(f"下载过程中发生关键错误: {e}")
            self.log_signal.emit(traceback.format_exc())
            logger.exception("下载过程中发生关键错误。")
        finally:
            # 保存当前的QzonePhotoManager实例，供下次使用
            if self.qzone_manager:
                self.previous_qzone_manager = self.qzone_manager
            self.finished_signal.emit("All")