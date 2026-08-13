import sys
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.pdf_service import get_page_count, open_pdf, render_page
from src.reader_state import reader_state
from src.storage_service import load_document_data, save_document_data


class PDFReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.document = None
        self.pdf_path = None
        self.document_id = None

        self.setWindowTitle("Custom AI PDF Reader")
        self.resize(1100, 800)

        self.create_actions()
        self.create_toolbar()
        self.create_interface()
        self.statusBar().showMessage("Open a PDF to begin.")

    def create_actions(self):
        self.open_action = QAction("Open PDF", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_pdf_file)

        self.exit_action = QAction("Exit", self)
        self.exit_action.setShortcut("Ctrl+Q")
        self.exit_action.triggered.connect(self.close)

    def create_toolbar(self):
        toolbar = QToolBar("Reader controls")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction(self.open_action)

    def create_interface(self):
        self.image_label = QLabel("Open a PDF to display its first page.")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet(
            "QLabel { background-color: #f3f5f7; color: #4a5560; padding: 30px; }"
        )

        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.setWidgetResizable(False)

        self.previous_button = QPushButton("◀ Previous")
        self.next_button = QPushButton("Next ▶")
        self.zoom_out_button = QPushButton("− Zoom")
        self.zoom_in_button = QPushButton("+ Zoom")
        self.go_button = QPushButton("Go")

        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setPrefix("Page ")

        self.page_label = QLabel("No PDF open")
        self.zoom_label = QLabel("Render: 120 DPI")

        control_layout = QHBoxLayout()
        control_layout.addWidget(self.previous_button)
        control_layout.addWidget(self.next_button)
        control_layout.addSpacing(12)
        control_layout.addWidget(self.zoom_out_button)
        control_layout.addWidget(self.zoom_in_button)
        control_layout.addSpacing(12)
        control_layout.addWidget(self.page_input)
        control_layout.addWidget(self.go_button)
        control_layout.addStretch()
        control_layout.addWidget(self.page_label)
        control_layout.addSpacing(16)
        control_layout.addWidget(self.zoom_label)

        root_layout = QVBoxLayout()
        root_layout.addWidget(self.scroll_area)
        root_layout.addLayout(control_layout)

        central_widget = QWidget()
        central_widget.setLayout(root_layout)
        self.setCentralWidget(central_widget)

        self.previous_button.clicked.connect(self.show_previous_page)
        self.next_button.clicked.connect(self.show_next_page)
        self.go_button.clicked.connect(self.go_to_page)
        self.zoom_out_button.clicked.connect(self.zoom_out)
        self.zoom_in_button.clicked.connect(self.zoom_in)

        self.set_reader_controls_enabled(False)

    def set_reader_controls_enabled(self, enabled):
        self.previous_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
        self.zoom_out_button.setEnabled(enabled)
        self.zoom_in_button.setEnabled(enabled)
        self.page_input.setEnabled(enabled)
        self.go_button.setEnabled(enabled)

    def open_pdf_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            str(Path.home()),
            "PDF files (*.pdf)",
        )

        if not file_name:
            return

        try:
            new_document = open_pdf(file_name)
        except Exception as error:
            QMessageBox.critical(self, "Could not open PDF", str(error))
            return

        if self.document is not None:
            self.save_current_reader_data()
            self.document.close()

        self.document = new_document
        self.pdf_path = Path(file_name)
        self.document_id = str(self.pdf_path.resolve())

        saved_data = load_document_data(
            document_id=self.document_id,
            pdf_path=self.pdf_path,
        )

        last_page = saved_data.get("last_page", 0)
        if not 0 <= last_page < get_page_count(self.document):
            last_page = 0

        reader_state["current_page"] = last_page
        reader_state["zoom_dpi"] = 120
        reader_state["search_results"] = []
        reader_state["search_index"] = 0
        reader_state["bookmarks"] = saved_data.get("bookmarks", [])
        reader_state["notes"] = saved_data.get("notes", [])

        self.page_input.setMaximum(get_page_count(self.document))
        self.setWindowTitle(f"Custom AI PDF Reader — {self.pdf_path.name}")
        self.set_reader_controls_enabled(True)
        self.refresh_reader()
        self.statusBar().showMessage(f"Opened {self.pdf_path.name}")

    def save_current_reader_data(self):
        if self.document is None or self.pdf_path is None:
            return

        save_document_data(
            document_id=self.document_id,
            pdf_path=self.pdf_path,
            bookmarks=reader_state["bookmarks"],
            notes=reader_state["notes"],
            last_page=reader_state["current_page"],
        )

    def refresh_reader(self):
        if self.document is None:
            return

        current_page = reader_state["current_page"]
        dpi = reader_state["zoom_dpi"]

        try:
            pil_image = render_page(
                document=self.document,
                page_number=current_page,
                dpi=dpi,
            )
        except Exception as error:
            QMessageBox.critical(self, "Could not render page", str(error))
            return

        qimage = self.pil_to_qimage(pil_image)
        self.image_label.setPixmap(QPixmap.fromImage(qimage))
        self.image_label.resize(qimage.size())

        total_pages = get_page_count(self.document)
        self.page_input.setValue(current_page + 1)
        self.page_label.setText(f"Page {current_page + 1} / {total_pages}")
        self.zoom_label.setText(f"Render: {dpi} DPI")
        self.previous_button.setEnabled(current_page > 0)
        self.next_button.setEnabled(current_page < total_pages - 1)

    @staticmethod
    def pil_to_qimage(image):
        if image.mode != "RGB":
            image = image.convert("RGB")

        data = image.tobytes("raw", "RGB")
        qimage = QImage(
            data,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888,
        )
        return qimage.copy()

    def change_page(self, new_page):
        if self.document is None:
            return

        if not 0 <= new_page < get_page_count(self.document):
            return

        reader_state["current_page"] = new_page
        self.save_current_reader_data()
        self.refresh_reader()

    def show_previous_page(self):
        self.change_page(reader_state["current_page"] - 1)

    def show_next_page(self):
        self.change_page(reader_state["current_page"] + 1)

    def go_to_page(self):
        self.change_page(self.page_input.value() - 1)

    def zoom_out(self):
        if reader_state["zoom_dpi"] > 72:
            reader_state["zoom_dpi"] -= 24
            self.refresh_reader()

    def zoom_in(self):
        if reader_state["zoom_dpi"] < 240:
            reader_state["zoom_dpi"] += 24
            self.refresh_reader()

    def closeEvent(self, event):
        self.save_current_reader_data()
        if self.document is not None:
            self.document.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = PDFReaderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
