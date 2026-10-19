"""Dockable status panel: server state, bound port and a live command log."""

try:
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtGui import QTextCursor
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget
except ImportError:  # Nuke 13-15.0 ship PySide2
    from PySide2.QtCore import QObject, Signal
    from PySide2.QtGui import QTextCursor
    from PySide2.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from .constants import ADDON_VERSION, DEFAULT_PORT
from .server import NukeMCPServer

MAX_LOG_LINES = 300


class _LogBridge(QObject):
    """Moves log lines from socket threads to the GUI thread."""
    line = Signal(str)


class NukeMCPPanel(QWidget):
    def __init__(self, port=DEFAULT_PORT, parent=None):
        super().__init__(parent)
        self.setWindowTitle("NukeMCP %s" % ADDON_VERSION)
        self.setMinimumWidth(320)
        self.setMinimumHeight(200)

        self._port = port
        self._server = None
        self._bridge = _LogBridge()
        self._bridge.line.connect(self._append_log)

        self._status_label = QLabel("Stopped")
        self._port_label = QLabel("Port: -")
        self._toggle_btn = QPushButton("Start")
        self._toggle_btn.clicked.connect(self._toggle_server)

        row = QHBoxLayout()
        row.addWidget(self._status_label)
        row.addStretch()
        row.addWidget(self._port_label)
        row.addWidget(self._toggle_btn)

        self._log = QTextEdit()
        self._log.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addLayout(row)
        layout.addWidget(self._log)
        self.setLayout(layout)

    def _toggle_server(self):
        if self._server and self._server._running:
            self._server.stop()
            self._server = None
            self._status_label.setText("Stopped")
            self._port_label.setText("Port: -")
            self._toggle_btn.setText("Start")
            return
        self._server = NukeMCPServer(self._port, log_callback=self._bridge.line.emit)
        try:
            self._server.start()
        except OSError as e:
            self._append_log("Could not start: %s" % e)
            self._server = None
            return
        self._status_label.setText("Running")
        self._port_label.setText("Port: %d" % self._server.port)
        self._toggle_btn.setText("Stop")

    def _append_log(self, msg):
        self._log.append(msg)
        doc = self._log.document()
        extra = doc.blockCount() - MAX_LOG_LINES
        if extra > 0:
            cursor = self._log.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor, extra)
            cursor.removeSelectedText()
