"""
QQ空间相册照片下载器 - GUI 入口

基于 PyQt6 的图形界面，所有核心下载逻辑由 core.py 提供。
"""

import json
import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import core
from core import (
    APP_CONFIG,
    CONFIG_FILE,
    USER_CONFIG,
    QzonePhotoManager,
    get_script_directory,
    load_config,
)

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "app.log")
MAX_LOG_SIZE = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 9

os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_file_handler = RotatingFileHandler(
    LOG_FILE, maxBytes=MAX_LOG_SIZE, backupCount=BACKUP_COUNT, encoding="utf-8"
)
_file_handler.setLevel(logging.INFO)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)

_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s"
)
_file_handler.setFormatter(_formatter)
_console_handler.setFormatter(_formatter)

logger.addHandler(_file_handler)
logger.addHandler(_console_handler)

# core 模块的 logger 也沿用同一套 handlers
core.logger.addHandler(_file_handler)
core.logger.addHandler(_console_handler)
core.logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# GuiLogHandler：将 logger 输出路由到 QTextEdit
# ---------------------------------------------------------------------------


class GuiLogHandler(logging.Handler):
    """将 logging 日志消息通过队列安全地追加到 QTextEdit。"""

    def __init__(self, text_widget: QTextEdit):
        super().__init__()
        self.text_widget = text_widget
        self._queue: list[str] = []
        self._timer = QTimer()
        self._timer.timeout.connect(self._flush)
        self._timer.start(100)

    def emit(self, record: logging.LogRecord) -> None:
        self._queue.append(self.format(record))

    def _flush(self) -> None:
        while self._queue:
            msg = self._queue.pop(0)
            self.text_widget.append(msg)
            sb = self.text_widget.verticalScrollBar()
            if sb:
                sb.setValue(sb.maximum())


# ---------------------------------------------------------------------------
# DownloadWorker：后台下载线程
# ---------------------------------------------------------------------------


class DownloadWorker(QThread):
    """在后台线程运行 QQ 空间照片下载，通过信号与 GUI 通信。"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(str)

    def __init__(self, main_user_qq: str, dest_users_qq: list):
        super().__init__()
        self.main_user_qq = main_user_qq
        self.dest_users_qq = dest_users_qq
        self.qzone_manager: QzonePhotoManager | None = None
        self._is_stopped = False
        # 保存上一次的 QzonePhotoManager 实例，用于复用 cookie
        self.previous_qzone_manager: QzonePhotoManager | None = None

    def stop(self) -> None:
        """设置停止标志，请求线程停止。"""
        self._is_stopped = True
        logger.info("下载工作线程收到停止请求。")

    def is_stopped(self) -> bool:
        return self._is_stopped

    def run(self) -> None:
        """线程主体。"""
        final_status = "All"
        had_error = False
        try:
            self.log_signal.emit("正在初始化下载管理器并尝试登录...")

            reuse_cookie = False
            if (
                self.previous_qzone_manager
                and self.previous_qzone_manager.user_qq == self.main_user_qq
                and self.previous_qzone_manager.cookies
            ):
                self.log_signal.emit("检测到已存在的登录信息，正在验证 cookie 有效性...")
                if self.previous_qzone_manager._check_cookie_validity():
                    self.qzone_manager = QzonePhotoManager(
                        self.main_user_qq, self.log_signal, self.is_stopped
                    )
                    self.qzone_manager._set_cookies_and_gtk(
                        self.previous_qzone_manager.cookies,
                        str(self.previous_qzone_manager.qzone_g_tk),
                    )
                    reuse_cookie = True
                    self.log_signal.emit("之前的 cookie 仍然有效，直接使用。")
                else:
                    self.log_signal.emit("之前的 cookie 已失效，需要重新登录。")

            if not reuse_cookie:
                self.qzone_manager = QzonePhotoManager(
                    self.main_user_qq, self.log_signal, self.is_stopped
                )
                if not self.is_stopped():
                    self.qzone_manager._login_and_get_cookies()

            if not self.is_stopped() and self.qzone_manager:
                self.log_signal.emit("登录过程已完成。")
            else:
                self.log_signal.emit("启动前已收到停止请求，跳过登录。")
                logger.info("启动前已收到停止请求，跳过登录。")
                final_status = "Stopped"
                return

            for target_qq in self.dest_users_qq:
                if self.is_stopped():
                    self.log_signal.emit(
                        f"下载任务已停止，跳过用户 {target_qq} 及后续用户。"
                    )
                    break

                target_qq_str = str(target_qq)
                self.log_signal.emit(f"\n--- 正在处理用户: {target_qq_str} ---")
                try:
                    if self.qzone_manager:
                        self.qzone_manager.download_all_photos_for_user(
                            target_qq_str,
                            progress_func=self.progress_signal.emit,
                        )
                except Exception as e:
                    had_error = True
                    self.log_signal.emit(f"处理用户 {target_qq_str} 时发生意外错误: {e}")
                    self.log_signal.emit(traceback.format_exc())
                    logger.exception(f"处理用户 {target_qq_str} 时发生意外错误。")
                self.log_signal.emit(f"--- 完成处理用户: {target_qq_str} ---")
                self.finished_signal.emit(target_qq_str)

            if not self.is_stopped():
                if had_error:
                    self.log_signal.emit("\n下载任务结束，但过程中出现错误，请查看日志。")
                    logger.warning("下载任务结束，但过程中出现错误。")
                    final_status = "Error"
                else:
                    self.log_signal.emit("\n所有指定用户处理完毕。")
                    logger.info("所有指定用户处理完毕。")
            else:
                self.log_signal.emit("下载已停止。")
                logger.info("下载已停止。")
                final_status = "Stopped"

        except Exception as e:
            final_status = "Error"
            self.log_signal.emit(f"下载过程中发生关键错误: {e}")
            self.log_signal.emit(traceback.format_exc())
            logger.exception("下载过程中发生关键错误。")
        finally:
            if self.qzone_manager:
                self.previous_qzone_manager = self.qzone_manager
            self.finished_signal.emit(final_status)


# ---------------------------------------------------------------------------
# QzoneDownloaderGUI：主窗口
# ---------------------------------------------------------------------------


class QzoneDownloaderGUI(QWidget):
    """QQ 空间照片下载器的主 GUI 应用程序。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QQ 空间照片下载器")
        self.setGeometry(100, 100, 800, 600)

        self.worker_thread: DownloadWorker | None = None
        self.total_photos_to_download = 0
        self.downloaded_photos_count = 0

        self._init_ui()
        self._load_initial_config_to_ui()

        # 将 logger 的输出路由到 GUI 的 log_output 控件
        self._gui_log_handler = GuiLogHandler(self.log_output)
        self._gui_log_handler.setFormatter(_formatter)
        logger.addHandler(self._gui_log_handler)
        core.logger.addHandler(self._gui_log_handler)

    def _init_ui(self) -> None:
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
        self.download_path_button.clicked.connect(self._select_download_path)
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
        self.start_button.clicked.connect(self._start_download)
        self.stop_button = QPushButton("停止下载")
        self.stop_button.clicked.connect(self._stop_download)
        self.stop_button.setEnabled(False)
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        main_layout.addLayout(button_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet("background-color: #f0f0f0; border: 1px solid #ccc;")
        main_layout.addWidget(self.log_output)

        self.setLayout(main_layout)

    def _load_initial_config_to_ui(self) -> None:
        """将配置值加载到 UI 字段中。"""
        self.main_qq_input.setText(USER_CONFIG.get("main_user_qq", ""))
        self.dest_qq_input.setText(",".join(str(q) for q in USER_CONFIG.get("dest_users_qq", [])))
        self.download_path_input.setText(
            os.path.join(get_script_directory(), APP_CONFIG.get("download_path", "qzone_photo"))
        )

    def _select_download_path(self) -> None:
        """打开目录对话框以选择下载路径。"""
        current_path = self.download_path_input.text() or get_script_directory()
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "选择下载目录",
            current_path,
            QFileDialog.Option.ShowDirsOnly,
        )
        if selected_dir:
            self.download_path_input.setText(selected_dir)
            APP_CONFIG["download_path"] = os.path.relpath(selected_dir, get_script_directory())

    def _start_download(self) -> None:
        """在单独的线程中启动下载过程。"""
        main_qq = self.main_qq_input.text().strip()
        dest_qqs_str = self.dest_qq_input.text().strip()
        download_path = self.download_path_input.text().strip()

        if main_qq == "123456":
            QMessageBox.warning(self, "输入错误", "主QQ号错误，请输入您的QQ号。")
            return
        if not main_qq or not dest_qqs_str:
            QMessageBox.warning(self, "输入错误", "主QQ号和目标QQ号不能为空。")
            return
        if not download_path:
            QMessageBox.warning(self, "输入错误", "下载路径不能为空。")
            return

        dest_qqs = [qq.strip() for qq in dest_qqs_str.split(",") if qq.strip()]
        if not dest_qqs:
            QMessageBox.warning(self, "输入错误", "目标QQ号列表不能为空。")
            return

        USER_CONFIG["main_user_qq"] = main_qq
        USER_CONFIG["dest_users_qq"] = dest_qqs
        APP_CONFIG["download_path"] = os.path.relpath(download_path, get_script_directory())

        try:
            updated_config = {
                "main_user_qq": USER_CONFIG["main_user_qq"],
                "main_user_pass": USER_CONFIG.get("main_user_pass", ""),
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

        previous_manager = self.worker_thread.previous_qzone_manager if self.worker_thread else None
        self.worker_thread = DownloadWorker(main_qq, dest_qqs)
        self.worker_thread.previous_qzone_manager = previous_manager
        self.worker_thread.log_signal.connect(self._update_log)
        self.worker_thread.progress_signal.connect(self._update_progress)
        self.worker_thread.finished_signal.connect(self._on_download_finished)
        self.worker_thread.start()

    def _stop_download(self) -> None:
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

    def _update_log(self, message: str) -> None:
        """将消息追加到日志输出区域。"""
        self.log_output.append(message)
        sb = self.log_output.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def _update_progress(self, value: int) -> None:
        """
        更新进度条。
        负数表示任务总量；正数 1 表示完成一个任务。
        """
        if value < 0:
            self.total_photos_to_download = abs(value)
            self.progress_bar.setMaximum(self.total_photos_to_download)
            self.progress_bar.setFormat(f"已下载 0 / {self.total_photos_to_download}")
        elif value == 1:
            self.downloaded_photos_count += 1
            if self.total_photos_to_download > 0:
                pct = (self.downloaded_photos_count / self.total_photos_to_download) * 100
                self.progress_bar.setValue(self.downloaded_photos_count)
                self.progress_bar.setFormat(
                    f"已下载 {self.downloaded_photos_count} / "
                    f"{self.total_photos_to_download} ({pct:.1f}%)"
                )
            else:
                self.progress_bar.setFormat(f"已下载 {self.downloaded_photos_count} 张照片")

    def _on_download_finished(self, status: str) -> None:
        """当用户下载完成或所有任务完成时调用。"""
        if status == "All":
            self.log_output.append("所有下载任务已完成。")
            logger.info("所有下载任务已完成。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("完成")
            self.progress_bar.setValue(self.progress_bar.maximum())
        elif status == "Stopped":
            self.log_output.append("下载任务已停止。")
            logger.info("下载任务已停止。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("已停止")
        elif status == "Error":
            self.log_output.append("下载过程中出现错误，请查看日志。")
            logger.warning("下载过程中出现错误，请查看日志。")
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.progress_bar.setFormat("出错")
        else:
            self.log_output.append(f"用户 {status} 的照片下载完成。")
            logger.info(f"用户 {status} 的照片下载完成。")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    load_config(exit_on_error=True)

    app = QApplication(sys.argv)
    gui = QzoneDownloaderGUI()
    gui.show()
    sys.exit(app.exec())
