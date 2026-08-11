import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow


app = QApplication(sys.argv)

window = QMainWindow()

window.setWindowTitle("Custom AI PDF Reader")

window.resize(900, 600)

message = QLabel(
    "Custom AI PDF Reader\n\n"
    "PySide6 desktop environment is working."
)

message.setAlignment(Qt.AlignmentFlag.AlignCenter)

window.setCentralWidget(message)

window.show()

sys.exit(app.exec())