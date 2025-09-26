"""
GUI主窗口模块
"""

import sys
import json
import os
import logging
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                             QLineEdit, QMessageBox, QProgressBar, QPushButton,
                             QTextEdit, QVBoxLayout, QWidget)

from config.config_manager import USER_CONFIG, APP_CONFIG, get_script_directory
from gui.download_worker import DownloadWorker
from gui.gui_logger import GuiLogHandler


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
            with open("config.json", "w", encoding="utf-8") as f:
                json.dump(updated_config, f, indent=4, ensure_ascii=False)
            self.log_output.append(f"配置已保存到 config.json。")
            logger.info(f"配置已保存到 config.json。")
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

        # 传递previous_qzone_manager给新的DownloadWorker实例
        previous_qzone_manager = self.worker_thread.previous_qzone_manager if self.worker_thread else None
        self.worker_thread = DownloadWorker(main_qq, main_pass, dest_qqs)
        self.worker_thread.previous_qzone_manager = previous_qzone_manager
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