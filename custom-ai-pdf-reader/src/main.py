import sys
from datetime import datetime
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QImage, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QTabWidget, QTextEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,QMenu,
)

from PySide6.QtCore import (
    Qt,
    QRectF,
    QSize,
    Signal,
)

from PySide6.QtWidgets import (
    QComboBox,
    QProgressBar,
)
from src.ollama_service import (
    OllamaError,
    get_available_models,
    summarize_document,
    summarize_text,
)
from src.ai_worker import SummaryWorker
from src.embedded_image_service import get_page_images, save_image_bytes
from src.night_mode_service import apply_night_mode
from src.pdf_page_view import PDFPageView
from src.pdf_service import open_pdf, render_page, search_document
from src.storage_service import load_document_data, save_document_data


class PDFTab(QWidget):
    status_message = Signal(str, int)
    zoom_changed = Signal(str)
    page_changed = Signal(int)

    def __init__(self, file_path):
        super().__init__()
        self.pdf_path = Path(file_path)
        self.document = None
        self.document_id = None
        self.current_page = 0
        self.zoom_dpi = 120
        self.fit_width = True
        self.night_mode = False
        self.search_results = []
        self.search_index = 0
        self.bookmarks = []
        self.notes = []
        self.annotations = []
        self.selected_text = ""
        self.selected_word_rectangles = []
        self.annotation_mode = "select"
        self.original_pixmap = None

        self.page_view = PDFPageView()
        self.page_view.selection_finished.connect(self.handle_text_selection)
        self.page_view.clicked.connect(self.handle_view_click)
        self.page_view.next_page_requested.connect(self.show_next_page)
        self.page_view.previous_page_requested.connect(self.show_previous_page)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page_view)
        self.load()

    def load(self):
        self.document = open_pdf(str(self.pdf_path))
        self.document_id = str(self.pdf_path.resolve())
        saved = load_document_data(self.document_id, self.pdf_path)
        last_page = saved.get("last_page", 0)
        self.current_page = last_page if 0 <= last_page < self.document.page_count else 0
        self.bookmarks = saved.get("bookmarks", [])
        self.notes = saved.get("notes", [])
        self.annotations = saved.get("annotations", [])
        self.render_current_page()

    def save_data(self):
        if self.document is not None:
            save_document_data(
                document_id=self.document_id,
                pdf_path=self.pdf_path,
                bookmarks=self.bookmarks,
                notes=self.notes,
                annotations=self.annotations,
                last_page=self.current_page,
            )

    @staticmethod
    def pil_to_qimage(image):
        if image.mode != "RGB":
            image = image.convert("RGB")
        return QImage(
            image.tobytes("raw", "RGB"),
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()

    @staticmethod
    def get_annotation_rectangles(annotation):
        return annotation.get("rectangles") or ([annotation["rect"]] if annotation.get("rect") else [])

    def draw_saved_annotations(self, image):
        draw = ImageDraw.Draw(image, "RGBA")
        scale = self.zoom_dpi / 72
        for annotation in self.annotations:
            if annotation.get("page_number") != self.current_page:
                continue
            for x0, y0, x1, y1 in self.get_annotation_rectangles(annotation):
                left, top, right, bottom = x0 * scale, y0 * scale, x1 * scale, y1 * scale
                kind = annotation.get("type")
                if kind == "highlight":
                    draw.rectangle([left, top, right, bottom], fill=(20, 184, 166, 90))
                elif kind == "underline":
                    draw.line([left, bottom - 2, right, bottom - 2], fill=(80, 160, 255, 255), width=max(2, int(scale * 2)))
                elif kind == "strikeout":
                    middle = (top + bottom) / 2
                    draw.line([left, middle, right, middle], fill=(240, 80, 80, 255), width=max(2, int(scale * 2)))

    def render_current_page(self):
        if self.document is None:
            return
        search_highlights = None
        if self.search_results:
            result = self.search_results[self.search_index]
            if result["page_number"] == self.current_page:
                search_highlights = result["rectangles"]
        try:
            image = render_page(
                document=self.document,
                page_number=self.current_page,
                dpi=self.zoom_dpi,
                highlight_rectangles=search_highlights,
            )
        except Exception as error:
            self.status_message.emit(f"Could not render page: {error}", 5000)
            return
        self.draw_saved_annotations(image)
        if self.night_mode:
            image = apply_night_mode(image)
        self.original_pixmap = QPixmap.fromImage(self.pil_to_qimage(image))
        self.update_page_display()
        zoom = "Fit" if self.fit_width else f"{round(self.zoom_dpi / 120 * 100)}%"
        self.zoom_changed.emit(zoom)
        self.status_message.emit(f"Page {self.current_page + 1} / {self.document.page_count} | Zoom {zoom}", 3000)

    def update_page_display(self):
        if self.original_pixmap is None:
            return
        if self.fit_width:
            width = max(self.page_view.viewport().width() - 24, 100)
            pixmap = self.original_pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        else:
            pixmap = self.original_pixmap
        self.page_view.set_page_pixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_width:
            self.update_page_display()

    def change_page(self, page_number):
        if self.document is None or not 0 <= page_number < self.document.page_count:
            return
        self.current_page = page_number
        self.save_data()
        self.render_current_page()
        self.page_view.verticalScrollBar().setValue(self.page_view.verticalScrollBar().minimum())
        self.page_view.horizontalScrollBar().setValue(self.page_view.horizontalScrollBar().minimum())
        self.page_changed.emit(page_number)

    def show_previous_page(self):
        self.change_page(self.current_page - 1)

    def show_next_page(self):
        self.change_page(self.current_page + 1)

    def zoom_in(self):
        maximum_dpi = 300
        zoom_step = 12

        if self.zoom_dpi < maximum_dpi:
            self.fit_width = False

            self.zoom_dpi = min(
                maximum_dpi,
                self.zoom_dpi + zoom_step,
            )

            self.render_current_page()

    def zoom_out(self):
        minimum_dpi = 24
        zoom_step = 12

        if self.zoom_dpi > minimum_dpi:
            self.fit_width = False

            self.zoom_dpi = max(
                minimum_dpi,
                self.zoom_dpi - zoom_step,
            )

            self.render_current_page()

    def enable_fit_width(self):
        self.fit_width = True
        self.update_page_display()
        self.zoom_changed.emit("Fit")

    def reset_zoom(self):
        self.fit_width = False
        self.zoom_dpi = 120
        self.render_current_page()

    def toggle_night_mode(self, enabled):
        self.night_mode = enabled
        self.render_current_page()
        self.status_message.emit("Night mode enabled." if enabled else "Day mode enabled.", 2500)

    def run_search(self, query):
        query = query.strip()
        if not query:
            self.search_results = []
            self.search_index = 0
            self.render_current_page()
            return
        self.search_results = search_document(self.document, query)
        self.search_index = 0
        if not self.search_results:
            self.status_message.emit(f"No results for '{query}'.", 3000)
            self.render_current_page()
            return
        self.show_current_search_result()

    def show_current_search_result(self):
        if not self.search_results:
            return
        result = self.search_results[self.search_index]
        self.change_page(result["page_number"])
        self.status_message.emit(f"Result {self.search_index + 1} / {len(self.search_results)} - Page {result['page_number'] + 1}", 4000)

    def show_next_result(self):
        if self.search_results:
            self.search_index = (self.search_index + 1) % len(self.search_results)
            self.show_current_search_result()

    def show_previous_result(self):
        if self.search_results:
            self.search_index = (self.search_index - 1) % len(self.search_results)
            self.show_current_search_result()

    def set_mode(self, mode):
        self.annotation_mode = mode
        messages = {
            "select": "Selection mode: drag to select text, Ctrl+C to copy.",
            "highlight": "Highlight mode: drag over text.",
            "underline": "Underline mode: drag over text.",
            "strikeout": "Strike mode: drag over text.",
            "eraser": "Eraser mode: click an annotation to delete it.",
            "image": "Image mode: drag around a picture to save it.",
        }
        self.status_message.emit(messages.get(mode, ""), 4000)

    def scene_rect_to_pdf_rect(self, rect):
        display_width = self.page_view.pixmap_item.pixmap().width()
        if not display_width or self.original_pixmap is None:
            return None
        image_scale = self.original_pixmap.width() / display_width
        pdf_scale = self.zoom_dpi / 72
        return pymupdf.Rect(
            rect.left() * image_scale / pdf_scale,
            rect.top() * image_scale / pdf_scale,
            rect.right() * image_scale / pdf_scale,
            rect.bottom() * image_scale / pdf_scale,
        )

    def handle_text_selection(self, rect):
        if self.document is None or self.original_pixmap is None:
            return
        if self.annotation_mode == "eraser":
            self.erase_annotations_in_rect(rect)
            return
        if self.annotation_mode == "image":
            self.save_region_as_image(rect)
            return
        selection = self.scene_rect_to_pdf_rect(rect)
        if selection is None:
            return
        words = self.document[self.current_page].get_text("words", sort=True)
        selected_words = []
        selected_rectangles = []
        for x0, y0, x1, y1, text, *_ in words:
            if pymupdf.Rect(x0, y0, x1, y1).intersects(selection):
                selected_words.append(text)
                selected_rectangles.append([x0, y0, x1, y1])
        self.selected_text = " ".join(selected_words)
        self.selected_word_rectangles = selected_rectangles
        if not self.selected_text:
            self.status_message.emit("No selectable text found in this area.", 3000)
            self.page_view.clear_selection()
            return
        if self.annotation_mode in {"highlight", "underline", "strikeout"}:
            self.add_annotation(self.annotation_mode)
        else:
            self.status_message.emit(f"Selected: {self.selected_text[:120]} (Ctrl+C to copy)", 5000)

    def handle_view_click(self, position):
        if self.annotation_mode == "eraser":
            self.erase_annotations_in_rect(QRectF(position.x() - 4, position.y() - 4, 8, 8))

    def add_annotation(self, annotation_type):
        if not self.selected_word_rectangles:
            return
        self.annotations.append({
            "page_number": self.current_page,
            "rectangles": self.selected_word_rectangles,
            "type": annotation_type,
            "text": self.selected_text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        self.save_data()
        self.selected_text = ""
        self.selected_word_rectangles = []
        self.page_view.clear_selection()
        self.render_current_page()

    def erase_annotations_in_rect(self, rect):
        selection = self.scene_rect_to_pdf_rect(rect)
        if selection is None:
            return
        matches = []
        for index, annotation in enumerate(self.annotations):
            if annotation.get("page_number") != self.current_page:
                continue
            if any(pymupdf.Rect(item).intersects(selection) for item in self.get_annotation_rectangles(annotation)):
                matches.append(index)
        if not matches:
            self.status_message.emit("No annotation found in the selected area.", 3000)
            return
        for index in reversed(matches):
            self.annotations.pop(index)
        self.save_data()
        self.page_view.clear_selection()
        self.render_current_page()
        self.status_message.emit(f"Deleted {len(matches)} annotation(s).", 3000)

    def save_region_as_image(self, rect):
        selection = self.scene_rect_to_pdf_rect(rect)
        if selection is None:
            return
        page = self.document[self.current_page]
        clip = selection & page.rect
        if clip.is_empty or clip.width < 3 or clip.height < 3:
            self.status_message.emit("Selected area is too small.", 3000)
            return
        suggested = f"{self.pdf_path.stem}_page{self.current_page + 1}_image.png"
        filename, _ = QFileDialog.getSaveFileName(self, "Save image", str(Path.home() / suggested), "PNG image (*.png);;JPEG image (*.jpg)")
        if not filename:
            self.page_view.clear_selection()
            return
        if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
            filename += ".png"
        try:
            pixmap = page.get_pixmap(clip=clip, dpi=300)
            Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).save(filename)
            self.status_message.emit(f"Image saved: {Path(filename).name}", 5000)
        except Exception as error:
            self.status_message.emit(f"Could not save image: {error}", 5000)
        self.page_view.clear_selection()

    def copy_selected_text(self):
        if not self.selected_text:
            self.status_message.emit("Drag-select text on the page first.", 2500)
            return
        QGuiApplication.clipboard().setText(self.selected_text)
        self.status_message.emit(f"Copied: {self.selected_text[:80]}", 3000)

    def get_current_page_text(self):
        if self.document is None:
            return ""

        page = self.document[self.current_page]

        return page.get_text(
            "text",
            sort=True,
        ).strip()


    def get_document_text(self):
        if self.document is None:
            return ""

        page_texts = []

        for page_number in range(self.document.page_count):
            page = self.document[page_number]

            text = page.get_text(
                "text",
                sort=True,
            ).strip()

            if text:
                page_texts.append(
                    f"\n\n--- PAGE {page_number + 1} ---\n{text}"
                )

        return "".join(page_texts).strip()


class PDFReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Pro")
        self.resize(1400, 900)
        self.create_toolbar()
        self.create_docks()

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.new_tab_button = QToolButton()
        self.new_tab_button.setText("+")
        self.new_tab_button.clicked.connect(self.open_pdf_file)
        self.tabs.setCornerWidget(self.new_tab_button, Qt.Corner.TopRightCorner)
        self.setCentralWidget(self.tabs)

        self.create_shortcuts()
        self.apply_stylesheet()
        self.set_tools_enabled(False)
        self.statusBar().showMessage("Open a PDF to begin. (Ctrl+O)")

    def create_toolbar(self):
        toolbar = QToolBar("Main toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.open_button = QToolButton(text="Open")
        self.open_button.clicked.connect(self.open_pdf_file)
        toolbar.addWidget(self.open_button)
        toolbar.addSeparator()

        self.prev_button = QToolButton(text="< Prev")
        self.prev_button.clicked.connect(lambda: self.tab_call("show_previous_page"))
        toolbar.addWidget(self.prev_button)
        self.next_button = QToolButton(text="Next >")
        self.next_button.clicked.connect(lambda: self.tab_call("show_next_page"))
        toolbar.addWidget(self.next_button)
        self.page_input = QSpinBox()
        self.page_input.setRange(1, 1)
        self.page_input.setFixedWidth(70)
        self.page_input.editingFinished.connect(self.go_to_page)
        toolbar.addWidget(self.page_input)
        self.total_pages_label = QLabel("/ -")
        toolbar.addWidget(self.total_pages_label)
        toolbar.addSeparator()

        self.zoom_out_button = QToolButton(text="-")
        self.zoom_out_button.clicked.connect(lambda: self.tab_call("zoom_out"))
        toolbar.addWidget(self.zoom_out_button)
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setFixedWidth(48)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.zoom_label)
        self.zoom_in_button = QToolButton(text="+")
        self.zoom_in_button.clicked.connect(lambda: self.tab_call("zoom_in"))
        toolbar.addWidget(self.zoom_in_button)
        self.fit_width_button = QToolButton(text="Fit Width")
        self.fit_width_button.clicked.connect(lambda: self.tab_call("enable_fit_width"))
        toolbar.addWidget(self.fit_width_button)
        self.reset_zoom_button = QToolButton(text="100%")
        self.reset_zoom_button.clicked.connect(lambda: self.tab_call("reset_zoom"))
        toolbar.addWidget(self.reset_zoom_button)
        self.night_mode_button = QToolButton(text="Night")
        self.night_mode_button.setCheckable(True)
        self.night_mode_button.toggled.connect(self.toggle_night_mode)
        toolbar.addWidget(self.night_mode_button)
        toolbar.addSeparator()

        toolbar.addSeparator()

        self.select_button = QToolButton()
        self.select_button.setText("Select")
        self.select_button.setCheckable(True)
        self.select_button.setChecked(True)

        self.highlight_button = QToolButton()
        self.highlight_button.setText("Highlight")
        self.highlight_button.setCheckable(True)

        self.underline_button = QToolButton()
        self.underline_button.setText("Underline")
        self.underline_button.setCheckable(True)

        self.strikeout_button = QToolButton()
        self.strikeout_button.setText("Strike")
        self.strikeout_button.setCheckable(True)

        self.eraser_button = QToolButton()
        self.eraser_button.setText("Eraser")
        self.eraser_button.setCheckable(True)

        self.image_button = QToolButton()
        self.image_button.setText("Snapshot")
        self.image_button.setCheckable(True)

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)

        for button in (
            self.select_button,
            self.highlight_button,
            self.underline_button,
            self.strikeout_button,
            self.eraser_button,
            self.image_button,
        ):
            self.tool_group.addButton(button)

        self.select_button.clicked.connect(
            lambda: self.set_tool_mode("select")
        )
        self.highlight_button.clicked.connect(
            lambda: self.set_tool_mode("highlight")
        )
        self.underline_button.clicked.connect(
            lambda: self.set_tool_mode("underline")
        )
        self.strikeout_button.clicked.connect(
            lambda: self.set_tool_mode("strikeout")
        )
        self.eraser_button.clicked.connect(
            lambda: self.set_tool_mode("eraser")
        )
        self.image_button.clicked.connect(
            lambda: self.set_tool_mode("image")
        )

        self.tools_menu = QMenu(self)

        self.tools_menu.addAction(
            "Select text",
            lambda: self.activate_tool("select")
        )

        self.tools_menu.addSeparator()

        self.tools_menu.addAction(
            "Highlight",
            lambda: self.activate_tool("highlight")
        )

        self.tools_menu.addAction(
            "Underline",
            lambda: self.activate_tool("underline")
        )

        self.tools_menu.addAction(
            "Strike through",
            lambda: self.activate_tool("strikeout")
        )

        self.tools_menu.addSeparator()

        self.tools_menu.addAction(
            "Eraser",
            lambda: self.activate_tool("eraser")
        )

        self.tools_button = QToolButton()
        self.tools_button.setText("Tools")
        self.tools_button.setMenu(self.tools_menu)
        self.tools_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.tools_button.setToolTip(
            "Select, highlight, underline, strike, and erase tools"
        )

        toolbar.addWidget(self.tools_button)

        self.images_menu = QMenu(self)

        self.images_menu.addAction(
            "Snapshot selected area",
            lambda: self.activate_tool("image")
        )

        self.images_menu.addAction(
            "Extract embedded images",
            self.open_embedded_images_dialog,
        )

        self.images_button = QToolButton()
        self.images_button.setText("Images")
        self.images_button.setMenu(self.images_menu)
        self.images_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self.images_button.setToolTip(
            "Save a snapshot or extract original images"
        )

        toolbar.addWidget(self.images_button)

        toolbar.addSeparator()

        self.search_toggle_button = QToolButton()
        self.search_toggle_button.setText("Search")
        self.search_toggle_button.setToolTip(
            "Show or hide PDF search (Ctrl+F)"
        )
        self.search_toggle_button.clicked.connect(
            self.toggle_search_bar
        )

        toolbar.addWidget(self.search_toggle_button)

        menu = self.menuBar().addMenu("File")
        open_action = QAction("Open PDF", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_pdf_file)
        menu.addAction(open_action)
        close_action = QAction("Close Tab", self)
        close_action.setShortcut(QKeySequence("Ctrl+W"))
        close_action.triggered.connect(self.close_current_tab)
        menu.addAction(close_action)
        menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        menu.addAction(exit_action)
        self.view_menu = self.menuBar().addMenu("View")
        self.search_toolbar = QToolBar("Search")
        self.search_toolbar.setMovable(False)
        self.search_toolbar.setVisible(False)

        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.search_toolbar)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(
            "Search in this PDF..."
        )
        self.search_input.setMinimumWidth(280)
        self.search_input.returnPressed.connect(self.run_search)

        self.search_button = QToolButton()
        self.search_button.setText("Find")
        self.search_button.clicked.connect(self.run_search)

        self.prev_result_button = QToolButton()
        self.prev_result_button.setText("Previous")
        self.prev_result_button.clicked.connect(
            lambda: self.tab_call("show_previous_result")
        )

        self.next_result_button = QToolButton()
        self.next_result_button.setText("Next")
        self.next_result_button.clicked.connect(
            lambda: self.tab_call("show_next_result")
        )

        self.close_search_button = QToolButton()
        self.close_search_button.setText("Close")
        self.close_search_button.clicked.connect(
            self.hide_search_bar
        )

        self.search_toolbar.addWidget(QLabel("Find:"))
        self.search_toolbar.addWidget(self.search_input)
        self.search_toolbar.addWidget(self.search_button)
        self.search_toolbar.addWidget(self.prev_result_button)
        self.search_toolbar.addWidget(self.next_result_button)
        self.search_toolbar.addWidget(self.close_search_button)

    def create_docks(self):
        self.thumbnails_dock = QDockWidget("Thumbnails", self)
        self.thumbnails_list = QListWidget()
        self.thumbnails_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails_list.setIconSize(QSize(110, 150))
        self.thumbnails_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails_list.setSpacing(12)
        self.thumbnails_list.itemClicked.connect(self.open_thumbnail)
        self.thumbnails_dock.setWidget(self.thumbnails_list)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumbnails_dock)

        self.bookmarks_dock = QDockWidget("Bookmarks", self)
        bookmark_widget = QWidget()
        bookmark_layout = QVBoxLayout(bookmark_widget)
        self.bookmark_label_input = QLineEdit()
        self.bookmark_label_input.setPlaceholderText("Bookmark label")
        self.add_bookmark_button = QPushButton("Add bookmark")
        self.bookmark_list = QListWidget()
        self.delete_bookmark_button = QPushButton("Delete selected")
        for widget in (self.bookmark_label_input, self.add_bookmark_button, self.bookmark_list, self.delete_bookmark_button):
            bookmark_layout.addWidget(widget)
        self.bookmarks_dock.setWidget(bookmark_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.bookmarks_dock)
        self.tabifyDockWidget(self.thumbnails_dock, self.bookmarks_dock)
        self.thumbnails_dock.raise_()
        self.add_bookmark_button.clicked.connect(self.add_bookmark)
        self.delete_bookmark_button.clicked.connect(self.delete_selected_bookmark)
        self.bookmark_list.itemDoubleClicked.connect(self.open_bookmark)

        self.tools_dock = QDockWidget("Tools", self)
        self.tools_tabs = QTabWidget()
        self.metadata_label = QLabel("Open a PDF to see its details.")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout(metadata_widget)
        metadata_layout.addWidget(self.metadata_label)
        self.tools_tabs.addTab(metadata_widget, "Metadata")

        notes_widget = QWidget()
        notes_layout = QVBoxLayout(notes_widget)
        self.note_input = QTextEdit()
        self.note_input.setPlaceholderText("Write your note here...")
        self.add_note_button = QPushButton("Save note")
        self.note_list = QListWidget()
        self.delete_note_button = QPushButton("Delete selected")
        for widget in (self.note_input, self.add_note_button, self.note_list, self.delete_note_button):
            notes_layout.addWidget(widget)
        self.tools_tabs.addTab(notes_widget, "Notes")
        ai_widget = QWidget()
        ai_layout = QVBoxLayout(ai_widget)

        ai_info = QLabel(
            "Summarize the current page, selected text, "
            "or the whole PDF using a local Ollama model."
        )
        ai_info.setWordWrap(True)

        self.ai_model_combo = QComboBox()

        self.ai_scope_combo = QComboBox()
        self.ai_scope_combo.addItems([
            "Current page",
            "Selected text",
            "Whole PDF",
        ])

        self.refresh_models_button = QPushButton(
            "Refresh models"
        )

        self.summarize_button = QPushButton(
            "Summarize"
        )

        self.ai_status_label = QLabel("")

        self.ai_output = QTextEdit()
        self.ai_output.setReadOnly(True)
        self.ai_output.setPlaceholderText(
            "Your AI summary will appear here..."
        )

        self.copy_ai_button = QPushButton(
            "Copy summary"
        )

        self.save_ai_note_button = QPushButton(
            "Save summary as note"
        )

        ai_layout.addWidget(ai_info)
        ai_layout.addWidget(QLabel("Model:"))
        ai_layout.addWidget(self.ai_model_combo)
        ai_layout.addWidget(QLabel("Scope:"))
        ai_layout.addWidget(self.ai_scope_combo)
        ai_layout.addWidget(self.refresh_models_button)
        ai_layout.addWidget(self.summarize_button)
        ai_layout.addWidget(self.ai_status_label)
        ai_layout.addWidget(self.ai_output)
        ai_layout.addWidget(self.copy_ai_button)
        ai_layout.addWidget(self.save_ai_note_button)

        self.tools_tabs.addTab(ai_widget, "AI Hub")
        self.tools_dock.setWidget(self.tools_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.tools_dock)
        self.add_note_button.clicked.connect(self.add_note)
        self.delete_note_button.clicked.connect(self.delete_selected_note)
        self.note_list.itemDoubleClicked.connect(self.open_note)
        self.refresh_models_button.clicked.connect(
            self.refresh_ollama_models
        )

        self.summarize_button.clicked.connect(
            self.start_summary
        )

        self.copy_ai_button.clicked.connect(
            self.copy_ai_summary
        )

        self.save_ai_note_button.clicked.connect(
            self.save_ai_summary_as_note
        )
        self.view_menu.addAction(self.thumbnails_dock.toggleViewAction())
        self.view_menu.addAction(self.bookmarks_dock.toggleViewAction())
        self.view_menu.addAction(self.tools_dock.toggleViewAction())

    def create_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_Left), self, activated=lambda: self.tab_call("show_previous_page"))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self, activated=lambda: self.tab_call("show_next_page"))
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=self.add_bookmark)
        QShortcut(QKeySequence("Ctrl++"), self, activated=lambda: self.tab_call("zoom_in"))
        QShortcut(QKeySequence("Ctrl+-"), self, activated=lambda: self.tab_call("zoom_out"))
        QShortcut(QKeySequence.StandardKey.Copy, self, activated=self.copy_selected_text)

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #1e2430; }
            QWidget { color: #e6e9f0; font-size: 13px; }
            QToolBar { background: #232b3a; border: none; padding: 6px; spacing: 6px; }
            QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 6px 10px; color: #e6e9f0; }
            QToolButton:hover { background: #2f3a4f; }
            QToolButton:checked { background: #14b8a6; color: #062621; font-weight: bold; }
            QPushButton { background: #2f3a4f; border: 1px solid #3a4763; border-radius: 8px; padding: 6px 12px; }
            QPushButton:hover { background: #3a4763; }
            QLineEdit, QSpinBox, QTextEdit { background: #171d29; border: 1px solid #3a4763; border-radius: 8px; padding: 5px 8px; }
            QListWidget { background: #232b3a; border: none; border-radius: 10px; padding: 6px; }
            QListWidget::item:selected { background: #14b8a6; color: #062621; }
            QTabWidget::pane { border: none; background: #1e2430; }
            QTabBar::tab { background: #232b3a; color: #9aa4b5; padding: 8px 16px; margin-right: 4px; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #14b8a6; color: #062621; font-weight: bold; }
            QDockWidget::title { background: #232b3a; padding: 8px; }
            QStatusBar { background: #232b3a; color: #9aa4b5; }
            QMenu {
        background: #232b3a;
        border: 1px solid #3a4763;
        border-radius: 8px;
        padding: 6px;
    }

    QMenu::item {
        padding: 8px 28px 8px 12px;
        border-radius: 5px;
    }

    QMenu::item:selected {
        background: #14b8a6;
        color: #062621;
    }
        """)

    def current_tab(self):
        return self.tabs.currentWidget()

    def tab_call(self, method_name, *args):
        tab = self.current_tab()
        if tab is not None:
            getattr(tab, method_name)(*args)

    def set_tool_mode(self, mode):
        tab = self.current_tab()
        if tab is not None:
            tab.set_mode(mode)

    def activate_tool(self, mode):
        button_map = {
            "select": self.select_button,
            "highlight": self.highlight_button,
            "underline": self.underline_button,
            "strikeout": self.strikeout_button,
            "eraser": self.eraser_button,
            "image": self.image_button,
        }

        button = button_map.get(mode)

        if button is not None:
            button.setChecked(True)

        self.set_tool_mode(mode)

        tool_names = {
            "select": "Select",
            "highlight": "Highlight",
            "underline": "Underline",
            "strikeout": "Strike",
            "eraser": "Eraser",
            "image": "Snapshot",
        }

        self.tools_button.setText(
            tool_names.get(mode, "Tools")
        )


    def toggle_search_bar(self):
        is_visible = not self.search_toolbar.isVisible()

        self.search_toolbar.setVisible(is_visible)

        if is_visible:
            self.search_input.setFocus()
            self.search_input.selectAll()


    def hide_search_bar(self):
        self.search_toolbar.setVisible(False)

    def toggle_night_mode(self, enabled):
        tab = self.current_tab()
        if tab is not None:
            tab.toggle_night_mode(enabled)

    def focus_search(self):
        if self.current_tab() is None:
            return

        self.search_toolbar.setVisible(True)

        self.search_input.setFocus()
        self.search_input.selectAll()

    def go_to_page(self):
        tab = self.current_tab()
        if tab is not None:
            tab.change_page(self.page_input.value() - 1)

    def run_search(self):
        tab = self.current_tab()
        if tab is not None:
            tab.run_search(self.search_input.text())

    def update_zoom_label(self, text):
        self.zoom_label.setText(text)

    def set_tools_enabled(self, enabled):
        widgets = [
            self.prev_button, self.next_button, self.page_input, self.zoom_out_button,
            self.zoom_in_button, self.fit_width_button, self.reset_zoom_button,
            self.night_mode_button,  self.tools_button,
            self.images_button,
            self.search_toggle_button,
            self.search_input,
            self.search_button,
            self.prev_result_button,
            self.next_result_button,
            self.close_search_button,self.thumbnails_list,
            self.bookmark_label_input, self.add_bookmark_button, self.bookmark_list,
            self.delete_bookmark_button, self.note_input, self.add_note_button,
            self.note_list, self.delete_note_button,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)

    def open_pdf_file(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open PDF", str(Path.home()), "PDF files (*.pdf)")
        if filename:
            self.open_pdf_in_new_tab(filename)

    def open_pdf_in_new_tab(self, filename):
        try:
            tab = PDFTab(filename)
        except Exception as error:
            QMessageBox.critical(self, "Could not open PDF", str(error))
            return
        tab.status_message.connect(self.statusBar().showMessage)
        tab.zoom_changed.connect(self.update_zoom_label)
        tab.page_changed.connect(self.on_tab_page_changed)
        index = self.tabs.addTab(tab, tab.pdf_path.name)
        self.tabs.setCurrentIndex(index)
        self.set_tools_enabled(True)
        self.refresh_ollama_models()

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if tab is not None:
            tab.save_data()
            if tab.document is not None:
                tab.document.close()
        self.tabs.removeTab(index)
        if self.tabs.count() == 0:
            self.set_tools_enabled(False)
            self.thumbnails_list.clear()
            self.bookmark_list.clear()
            self.note_list.clear()
            self.metadata_label.setText("Open a PDF to see its details.")
            self.total_pages_label.setText("/ -")
            self.zoom_label.setText("Fit")
            self.setWindowTitle("PDF Pro")

    def close_current_tab(self):
        if self.tabs.currentIndex() >= 0:
            self.close_tab(self.tabs.currentIndex())

    def on_tab_page_changed(self, page):
        tab = self.current_tab()
        if tab is None or tab.document is None:
            return
        self.page_input.blockSignals(True)
        self.page_input.setValue(page + 1)
        self.page_input.blockSignals(False)
        self.thumbnails_list.blockSignals(True)
        self.thumbnails_list.setCurrentRow(page)
        self.thumbnails_list.blockSignals(False)

    def on_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if tab is None or tab.document is None:
            return
        self.set_tools_enabled(True)
        self.page_input.blockSignals(True)
        self.page_input.setRange(1, tab.document.page_count)
        self.page_input.setValue(tab.current_page + 1)
        self.page_input.blockSignals(False)
        self.total_pages_label.setText(f"/ {tab.document.page_count}")
        self.night_mode_button.blockSignals(True)
        self.night_mode_button.setChecked(tab.night_mode)
        self.night_mode_button.blockSignals(False)
        mapping = {
            "select": self.select_button, "highlight": self.highlight_button,
            "underline": self.underline_button, "strikeout": self.strikeout_button,
            "eraser": self.eraser_button, "image": self.image_button,
        }
        mapping.get(tab.annotation_mode, self.select_button).setChecked(True)
        self.zoom_label.setText("Fit" if tab.fit_width else f"{round(tab.zoom_dpi / 120 * 100)}%")
        self.build_thumbnails()
        self.refresh_metadata()
        self.refresh_bookmarks()
        self.refresh_notes()
        self.setWindowTitle(f"PDF Pro - {tab.pdf_path.name}")

    def build_thumbnails(self):
        self.thumbnails_list.clear()
        tab = self.current_tab()
        if tab is None:
            return
        for page_number in range(tab.document.page_count):
            pix = tab.document[page_number].get_pixmap(dpi=24)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
            item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), f"P{page_number + 1}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbnails_list.addItem(item)
        self.thumbnails_list.setCurrentRow(tab.current_page)

    def open_thumbnail(self, item):
        tab = self.current_tab()
        if tab is not None:
            tab.change_page(self.thumbnails_list.row(item))

    def open_embedded_images_dialog(self):
        tab = self.current_tab()
        if tab is None or tab.document is None:
            return
        images = get_page_images(tab.document, tab.current_page)
        if not images:
            QMessageBox.information(self, "No embedded images", "No original embedded raster images were found on this page.\n\nUse the Image tool for charts, diagrams, or a custom page area.")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Embedded images - Page {tab.current_page + 1}")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        info = QLabel(f"Found {len(images)} embedded image(s). Select an image, then save it without reducing quality.")
        info.setWordWrap(True)
        layout.addWidget(info)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        selected = {"image": None}
        buttons = []

        def choose(image_info, button):
            selected["image"] = image_info
            for card in buttons:
                card.setStyleSheet("")
            button.setStyleSheet("border: 3px solid #14b8a6; border-radius: 8px;")

        for index, image_info in enumerate(images):
            preview = QPixmap()
            preview.loadFromData(image_info["bytes"])
            image_label = QLabel("Preview unavailable")
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            if not preview.isNull():
                image_label.setPixmap(preview.scaled(170, 130, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            details = QLabel(f"Image {index + 1}\n{image_info['width']} x {image_info['height']}\n.{image_info['extension'].upper()}")
            details.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card = QPushButton()
            card.setFixedSize(195, 190)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(8, 8, 8, 8)
            card_layout.addWidget(image_label)
            card_layout.addWidget(details)
            card.clicked.connect(lambda checked=False, item=image_info, button=card: choose(item, button))
            buttons.append(card)
            grid.addWidget(card, index // 3, index % 3)

        scroll.setWidget(grid_widget)
        layout.addWidget(scroll)
        button_box = QDialogButtonBox()
        save_selected_button = button_box.addButton("Save selected", QDialogButtonBox.ButtonRole.AcceptRole)
        save_all_button = button_box.addButton("Save all", QDialogButtonBox.ButtonRole.ActionRole)
        close_button = button_box.addButton(QDialogButtonBox.StandardButton.Close)
        layout.addWidget(button_box)
        def save_selected():
            image_info = selected["image"]

            if image_info is None:
                QMessageBox.information(
                    dialog,
                    "No image selected",
                    "Click one image preview first.",
                )
                return

            default_name = (
                f"{tab.pdf_path.stem}_"
                f"page{tab.current_page + 1}_"
                f"image_{image_info['xref']}."
                f"{image_info['extension']}"
            )

            filename, _ = QFileDialog.getSaveFileName(
                dialog,
                "Save original embedded image",
                str(Path.home() / default_name),
                "All files (*.*)",
            )

            if not filename:
                return

            try:
                save_image_bytes(image_info, filename)

            except Exception as error:
                QMessageBox.critical(
                    dialog,
                    "Could not save image",
                    str(error),
                )
                return

            QMessageBox.information(
                dialog,
                "Image saved",
                f"Saved original image as:\n{Path(filename).name}",
            )

        def save_all():
            folder = QFileDialog.getExistingDirectory(
                dialog,
                "Choose folder for extracted images",
                str(Path.home()),
            )

            if not folder:
                return

            try:
                for index, image_info in enumerate(images, start=1):
                    filename = (
                        f"{tab.pdf_path.stem}_"
                        f"page{tab.current_page + 1}_"
                        f"image_{index}_xref{image_info['xref']}."
                        f"{image_info['extension']}"
                    )

                    save_image_bytes(
                        image_info,
                        Path(folder) / filename,
                    )

            except Exception as error:
                QMessageBox.critical(
                    dialog,
                    "Could not save images",
                    str(error),
                )
                return

            QMessageBox.information(
                dialog,
                "Images saved",
                f"Saved {len(images)} image(s) to:\n{folder}",
            )

        save_selected_button.clicked.connect(save_selected)
        save_all_button.clicked.connect(save_all)
        close_button.clicked.connect(dialog.close)

        dialog.exec()

        
    def refresh_metadata(self):
        tab = self.current_tab()

        if tab is None or tab.document is None:
            self.metadata_label.setText(
                "Open a PDF to see its details."
            )
            return

        metadata = tab.document.metadata or {}

        self.metadata_label.setText(
            f"<b>Title:</b> "
            f"{metadata.get('title') or '-'}<br><br>"

            f"<b>Author:</b> "
            f"{metadata.get('author') or '-'}<br><br>"

            f"<b>Subject:</b> "
            f"{metadata.get('subject') or '-'}<br><br>"

            f"<b>Creator:</b> "
            f"{metadata.get('creator') or '-'}<br><br>"

            f"<b>Pages:</b> "
            f"{tab.document.page_count}<br><br>"

            f"<b>File:</b> "
            f"{tab.pdf_path.name}"
        )
        

    def refresh_ollama_models(self):
        self.ai_model_combo.clear()

        try:
            models = get_available_models()

        except OllamaError as error:
            self.ai_status_label.setText(str(error))
            return

        if not models:
            self.ai_status_label.setText(
                "No Ollama models found. "
                "Run: ollama pull qwen2.5:3b"
            )
            return

        self.ai_model_combo.addItems(models)

        self.ai_status_label.setText(
            f"Found {len(models)} local model(s)."
        )

    def start_summary(self):
        tab = self.current_tab()

        if tab is None:
            return

        model = self.ai_model_combo.currentText()

        if not model:
            self.ai_status_label.setText(
                "Choose a model first, then click Refresh models."
            )
            return

        scope = self.ai_scope_combo.currentText()

        if scope == "Selected text":
            text = tab.selected_text
            whole_document = False

            if not text:
                self.ai_status_label.setText(
                    "Select text on the PDF first."
                )
                return

        elif scope == "Whole PDF":
            text = tab.get_document_text()
            whole_document = True

        else:
            text = tab.get_current_page_text()
            whole_document = False

        if not text:
            self.ai_status_label.setText(
                "No selectable text was found."
            )
            return

        self.summarize_button.setEnabled(False)
        self.refresh_models_button.setEnabled(False)
        self.ai_output.clear()
        self.ai_status_label.setText(
            "Starting local model..."
        )

        self.summary_worker = SummaryWorker(
            model=model,
            text=text,
            whole_document=whole_document,
            parent=self,
        )

        self.summary_worker.progress.connect(
            self.ai_status_label.setText
        )

        self.summary_worker.finished_summary.connect(
            self.finish_summary
        )

        self.summary_worker.failed.connect(
            self.summary_failed
        )

        self.summary_worker.start()

    def finish_summary(self, summary):
        self.ai_output.setPlainText(summary)
        self.ai_status_label.setText("Summary complete.")
        self.summarize_button.setEnabled(True)
        self.refresh_models_button.setEnabled(True)

    def summary_failed(self, message):
        self.ai_status_label.setText(message)
        self.summarize_button.setEnabled(True)
        self.refresh_models_button.setEnabled(True)

    def copy_ai_summary(self):
        summary = self.ai_output.toPlainText().strip()

        if not summary:
            self.ai_status_label.setText(
                "There is no summary to copy."
            )
            return

        QGuiApplication.clipboard().setText(summary)

        self.ai_status_label.setText(
            "Summary copied to clipboard."
        )

    def save_ai_summary_as_note(self):
        tab = self.current_tab()

        if tab is None:
            return

        summary = self.ai_output.toPlainText().strip()

        if not summary:
            self.ai_status_label.setText(
                "Generate a summary first."
            )
            return

        tab.notes.append({
            "page_number": tab.current_page,
            "text": f"AI Summary:\n\n{summary}",
            "created_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            ),
        })

        tab.save_data()
        self.refresh_notes()

        self.ai_status_label.setText(
            "Summary saved as a note."
        )        

    

    def refresh_bookmarks(self):
        self.bookmark_list.clear()
        tab = self.current_tab()
        if tab is None:
            return
        for index, bookmark in enumerate(tab.bookmarks):
            item = QListWidgetItem(f"Page {bookmark['page_number'] + 1}: {bookmark['label']}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.bookmark_list.addItem(item)

    def add_bookmark(self):
        tab = self.current_tab()
        if tab is None:
            return
        label = self.bookmark_label_input.text().strip() or f"Page {tab.current_page + 1}"
        tab.bookmarks.append({"page_number": tab.current_page, "label": label})
        tab.save_data()
        self.bookmark_label_input.clear()
        self.refresh_bookmarks()

    def open_bookmark(self, item):
        tab = self.current_tab()
        if tab is not None:
            tab.change_page(tab.bookmarks[item.data(Qt.ItemDataRole.UserRole)]["page_number"])

    def delete_selected_bookmark(self):
        tab = self.current_tab()
        selected = self.bookmark_list.selectedItems()
        if tab is None or not selected:
            return
        tab.bookmarks.pop(selected[0].data(Qt.ItemDataRole.UserRole))
        tab.save_data()
        self.refresh_bookmarks()

    def refresh_notes(self):
        self.note_list.clear()
        tab = self.current_tab()
        if tab is None:
            return
        for index, note in enumerate(tab.notes):
            preview = note["text"].replace("\n", " ")[:55]
            item = QListWidgetItem(f"Page {note['page_number'] + 1}: {preview}\n{note['created_at']}")
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.note_list.addItem(item)

    def add_note(self):
        tab = self.current_tab()
        text = self.note_input.toPlainText().strip()
        if tab is None or not text:
            return
        tab.notes.append({"page_number": tab.current_page, "text": text, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")})
        tab.save_data()
        self.note_input.clear()
        self.refresh_notes()

    def open_note(self, item):
        tab = self.current_tab()
        if tab is not None:
            tab.change_page(tab.notes[item.data(Qt.ItemDataRole.UserRole)]["page_number"])

    def delete_selected_note(self):
        tab = self.current_tab()
        selected = self.note_list.selectedItems()
        if tab is None or not selected:
            return
        tab.notes.pop(selected[0].data(Qt.ItemDataRole.UserRole))
        tab.save_data()
        self.refresh_notes()

    def copy_selected_text(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)):
            focus.copy()
        elif self.current_tab() is not None:
            self.current_tab().copy_selected_text()

    def closeEvent(self, event):
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            tab.save_data()
            if tab.document is not None:
                tab.document.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = PDFReaderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
