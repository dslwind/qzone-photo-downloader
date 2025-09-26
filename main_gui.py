"""
QQ空间相册照片下载器 - GUI版本
"""

import sys

from PyQt6.QtWidgets import QApplication

from gui.main_window import QzoneDownloaderGUI as QzoneDownloaderGUI

if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = QzoneDownloaderGUI()
    gui.show()
    sys.exit(app.exec())