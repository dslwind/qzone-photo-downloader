"""
GUI日志处理器模块
"""

import logging
from PyQt6.QtCore import QTimer


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