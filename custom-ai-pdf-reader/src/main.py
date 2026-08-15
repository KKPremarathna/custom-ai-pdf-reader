import sys
from datetime import datetime
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt, QRectF, QSize, Signal
from PySide6.QtGui import (
    QAction, QGuiApplication, QIcon, QImage,
    QKeySequence, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QDockWidget, QFileDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QTabWidget,
    QTextEdit, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

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

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.page_view)
        self.setLayout(layout)

        self.load()

    def load(self):
        self.document = open_pdf(str(self.pdf_path))
        self.document_id = str(self.pdf_path.resolve())
        saved = load_document_data(
            document_id=self.document_id, pdf_path=self.pdf_path,
        )
        last_page = saved.get("last_page", 0)
        if not 0 <= last_page < self.document.page_count:
            last_page = 0
        self.current_page = last_page
        self.bookmarks = saved.get("bookmarks", [])
        self.notes = saved.get("notes", [])
        self.annotations = saved.get("annotations", [])
        self.render_current_page()

    def save_data(self):
        if self.document is None:
            return
        save_document_data(
            document_id=self.document_id,
            pdf_path=self.pdf_path,
            bookmarks=self.bookmarks,
            notes=self.notes,
            annotations=self.annotations,
            last_page=self.current_page,
        )

    def render_current_page(self):
        if self.document is None:
            return
        search_highlights = None
        if self.search_results:
            current_result = self.search_results[self.search_index]
            if current_result["page_number"] == self.current_page:
                search_highlights = current_result["rectangles"]
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
        qimage = self.pil_to_qimage(image)
        self.original_pixmap = QPixmap.fromImage(qimage)
        self.update_page_display()
        percent = round(self.zoom_dpi / 120 * 100)
        zoom_text = "Fit" if self.fit_width else f"{percent}%"
        self.zoom_changed.emit(zoom_text)
        self.status_message.emit(
            f"Page {self.current_page + 1} / {self.document.page_count}"
            f"  |  Zoom {zoom_text}",
            3000,
        )

    def draw_saved_annotations(self, image):
        draw = ImageDraw.Draw(image, "RGBA")
        scale = self.zoom_dpi / 72
        for annotation in self.annotations:
            if annotation["page_number"] != self.current_page:
                continue
            annotation_type = annotation["type"]
            for rectangle in self.get_annotation_rectangles(annotation):
                x0, y0, x1, y1 = rectangle
                left = x0 * scale
                top = y0 * scale
                right = x1 * scale
                bottom = y1 * scale
                if annotation_type == "highlight":
                    draw.rectangle(
                        [left, top, right, bottom],
                        fill=(20, 184, 166, 90),
                    )
                elif annotation_type == "underline":
                    line_y = bottom - 2
                    draw.line(
                        [left, line_y, right, line_y],
                        fill=(80, 160, 255, 255),
                        width=max(2, int(scale * 2)),
                    )
                elif annotation_type == "strikeout":
                    line_y = (top + bottom) / 2
                    draw.line(
                        [left, line_y, right, line_y],
                        fill=(240, 80, 80, 255),
                        width=max(2, int(scale * 2)),
                    )

    def update_page_display(self):
        if self.original_pixmap is None:
            return
        if self.fit_width:
            viewport_width = self.page_view.viewport().width()
            target_width = max(viewport_width - 24, 100)
            fitted = self.original_pixmap.scaledToWidth(
                target_width,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.page_view.set_page_pixmap(fitted)
        else:
            self.page_view.set_page_pixmap(self.original_pixmap)

    @staticmethod
    def pil_to_qimage(image):
        if image.mode != "RGB":
            image = image.convert("RGB")
        image_data = image.tobytes("raw", "RGB")
        qimage = QImage(
            image_data, image.width, image.height,
            image.width * 3, QImage.Format.Format_RGB888,
        )
        return qimage.copy()

    @staticmethod
    def get_annotation_rectangles(annotation):
        rectangles = annotation.get("rectangles")
        if rectangles:
            return rectangles
        single_rect = annotation.get("rect")
        if single_rect:
            return [single_rect]
        return []

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_width:
            self.update_page_display()

    def change_page(self, new_page):
        if self.document is None:
            return
        if not 0 <= new_page < self.document.page_count:
            return
        self.current_page = new_page
        self.save_data()
        self.render_current_page()
        self.page_view.verticalScrollBar().setValue(
            self.page_view.verticalScrollBar().minimum()
        )
        self.page_view.horizontalScrollBar().setValue(
            self.page_view.horizontalScrollBar().minimum()
        )
        self.page_changed.emit(new_page)

    def show_previous_page(self):
        self.change_page(self.current_page - 1)

    def show_next_page(self):
        self.change_page(self.current_page + 1)

    def zoom_in(self):
        if self.zoom_dpi < 240:
            self.fit_width = False
            self.zoom_dpi += 24
            self.render_current_page()

    def zoom_out(self):
        if self.zoom_dpi > 72:
            self.fit_width = False
            self.zoom_dpi -= 24
            self.render_current_page()

    def enable_fit_width(self):
        self.fit_width = True
        self.update_page_display()
        self.zoom_changed.emit("Fit")
        self.status_message.emit("Fit width enabled.", 2500)

    def reset_zoom(self):
        self.fit_width = False
        self.zoom_dpi = 120
        self.render_current_page()

    def run_search(self, query):
        if self.document is None:
            return
        query = query.strip()
        if not query:
            self.search_results = []
            self.search_index = 0
            self.status_message.emit("Enter search text.", 3000)
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
        self.status_message.emit(
            f"Result {self.search_index + 1} / {len(self.search_results)}"
            f" - Page {result['page_number'] + 1}",
            4000,
        )

    def show_next_result(self):
        if not self.search_results:
            self.status_message.emit("Search for text first.", 3000)
            return
        self.search_index = (self.search_index + 1) % len(self.search_results)
        self.show_current_search_result()

    def show_previous_result(self):
        if not self.search_results:
            self.status_message.emit("Search for text first.", 3000)
            return
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
            "image": "Image mode: drag a box around a picture to save it.",
        }
        self.status_message.emit(messages.get(mode, ""), 4000)

    def scene_rect_to_pdf_rect(self, selection_rect):
        dpi = self.zoom_dpi
        display_width = self.page_view.pixmap_item.pixmap().width()
        original_width = self.original_pixmap.width()
        if display_width == 0:
            return None
        display_scale = original_width / display_width
        pdf_scale = dpi / 72
        return pymupdf.Rect(
            selection_rect.left() * display_scale / pdf_scale,
            selection_rect.top() * display_scale / pdf_scale,
            selection_rect.right() * display_scale / pdf_scale,
            selection_rect.bottom() * display_scale / pdf_scale,
        )

    def handle_text_selection(self, selection_rect):
        if self.document is None or self.original_pixmap is None:
            return
        if self.annotation_mode == "eraser":
            self.erase_annotations_in_rect(selection_rect)
            return
        if self.annotation_mode == "image":
            self.save_region_as_image(selection_rect)
            return
        selection_pdf_rect = self.scene_rect_to_pdf_rect(selection_rect)
        if selection_pdf_rect is None:
            return
        page = self.document[self.current_page]
        words = page.get_text("words", sort=True)
        selected_words = []
        selected_rectangles = []
        for word in words:
            x0, y0, x1, y1, text, *_ = word
            word_rect = pymupdf.Rect(x0, y0, x1, y1)
            if word_rect.intersects(selection_pdf_rect):
                selected_words.append(text)
                selected_rectangles.append([x0, y0, x1, y1])
        self.selected_text = " ".join(selected_words)
        self.selected_word_rectangles = selected_rectangles
        if not self.selected_text:
            self.status_message.emit(
                "No selectable text found in this area.", 3000
            )
            self.page_view.clear_selection()
            return
        if self.annotation_mode in {"highlight", "underline", "strikeout"}:
            self.add_annotation(self.annotation_mode)
            return
        self.status_message.emit(
            f"Selected: {self.selected_text[:120]}  (Ctrl+C to copy)",
            5000,
        )

    def handle_view_click(self, scene_position):
        if self.document is None or self.original_pixmap is None:
            return
        if self.annotation_mode != "eraser":
            return
        click_rect = QRectF(
            scene_position.x() - 4,
            scene_position.y() - 4,
            8, 8,
        )
        self.erase_annotations_in_rect(click_rect)

    def save_region_as_image(self, selection_rect):
        selection_pdf_rect = self.scene_rect_to_pdf_rect(selection_rect)
        if selection_pdf_rect is None:
            return

        page = self.document[self.current_page]
        clip = selection_pdf_rect & page.rect

        if clip.is_empty or clip.width < 3 or clip.height < 3:
            self.status_message.emit(
                "Selected area is too small.", 3000
            )
            self.page_view.clear_selection()
            return

        suggested_name = (
            f"{self.pdf_path.stem}_page{self.current_page + 1}_image.png"
        )

        file_name, _ = QFileDialog.getSaveFileName(
            self,
            "Save image",
            str(Path.home() / suggested_name),
            "PNG image (*.png);;JPEG image (*.jpg)",
        )

        if not file_name:
            self.page_view.clear_selection()
            return

        if not file_name.lower().endswith((".png", ".jpg", ".jpeg")):
            file_name += ".png"

        try:
            pixmap = page.get_pixmap(clip=clip, dpi=300)
            image = Image.frombytes(
                "RGB",
                (pixmap.width, pixmap.height),
                pixmap.samples,
            )
            image.save(file_name)
        except Exception as error:
            self.status_message.emit(
                f"Could not save image: {error}", 5000
            )
            self.page_view.clear_selection()
            return

        self.page_view.clear_selection()
        self.status_message.emit(
            f"Image saved: {Path(file_name).name}", 5000
        )

    def erase_annotations_in_rect(self, selection_rect):
        selection_pdf_rect = self.scene_rect_to_pdf_rect(selection_rect)
        if selection_pdf_rect is None:
            return
        matching_indexes = []
        for index, annotation in enumerate(self.annotations):
            if annotation["page_number"] != self.current_page:
                continue
            for rectangle in self.get_annotation_rectangles(annotation):
                annotation_rect = pymupdf.Rect(rectangle)
                if annotation_rect.intersects(selection_pdf_rect):
                    matching_indexes.append(index)
                    break
        if not matching_indexes:
            self.status_message.emit(
                "No annotation found in the selected area.", 3000
            )
            self.page_view.clear_selection()
            return
        for index in reversed(matching_indexes):
            self.annotations.pop(index)
        self.save_data()
        self.render_current_page()
        self.page_view.clear_selection()
        self.status_message.emit(
            f"Deleted {len(matching_indexes)} annotation(s).", 3000
        )

    def add_annotation(self, annotation_type):
        if self.document is None:
            return
        if not self.selected_word_rectangles:
            self.status_message.emit("Drag-select text first.", 3000)
            return
        new_annotation = {
            "page_number": self.current_page,
            "rectangles": self.selected_word_rectangles,
            "type": annotation_type,
            "text": self.selected_text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.annotations.append(new_annotation)
        self.save_data()
        self.selected_text = ""
        self.selected_word_rectangles = []
        self.page_view.clear_selection()
        self.render_current_page()
        self.status_message.emit(
            f"Saved {annotation_type} annotation.", 3000
        )

    def copy_selected_text(self):
        if not self.selected_text:
            self.status_message.emit(
                "Drag-select text on the page first.", 2500
            )
            return
        QGuiApplication.clipboard().setText(self.selected_text)
        self.status_message.emit(
            f"Copied: {self.selected_text[:80]}", 3000
        )


class PDFReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_tool_mode = "select"
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
        self.new_tab_button.setToolTip("Open PDF in a new tab (Ctrl+O)")
        self.new_tab_button.clicked.connect(self.open_pdf_file)
        self.tabs.setCornerWidget(
            self.new_tab_button, Qt.Corner.TopRightCorner
        )

        self.setCentralWidget(self.tabs)

        self.create_shortcuts()
        self.apply_stylesheet()
        self.set_tools_enabled(False)
        self.statusBar().showMessage("Open a PDF to begin. (Ctrl+O)")

    def create_toolbar(self):
        toolbar = QToolBar("Main toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self.open_button = QToolButton()
        self.open_button.setText("Open")
        self.open_button.setToolTip("Open PDF (Ctrl+O)")
        self.open_button.clicked.connect(self.open_pdf_file)
        toolbar.addWidget(self.open_button)

        toolbar.addSeparator()

        self.prev_button = QToolButton()
        self.prev_button.setText("< Prev")
        self.prev_button.clicked.connect(
            lambda: self.tab_call("show_previous_page")
        )
        toolbar.addWidget(self.prev_button)

        self.next_button = QToolButton()
        self.next_button.setText("Next >")
        self.next_button.clicked.connect(
            lambda: self.tab_call("show_next_page")
        )
        toolbar.addWidget(self.next_button)

        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_input.setFixedWidth(70)
        self.page_input.editingFinished.connect(self.go_to_page)
        toolbar.addWidget(self.page_input)

        self.total_pages_label = QLabel("/ -")
        toolbar.addWidget(self.total_pages_label)

        toolbar.addSeparator()

        self.zoom_out_button = QToolButton()
        self.zoom_out_button.setText("-")
        self.zoom_out_button.setToolTip("Zoom out (Ctrl+-)")
        self.zoom_out_button.clicked.connect(
            lambda: self.tab_call("zoom_out")
        )
        toolbar.addWidget(self.zoom_out_button)

        self.zoom_label = QLabel("Fit")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setFixedWidth(48)
        toolbar.addWidget(self.zoom_label)

        self.zoom_in_button = QToolButton()
        self.zoom_in_button.setText("+")
        self.zoom_in_button.setToolTip("Zoom in (Ctrl++)")
        self.zoom_in_button.clicked.connect(
            lambda: self.tab_call("zoom_in")
        )
        toolbar.addWidget(self.zoom_in_button)

        self.fit_width_button = QToolButton()
        self.fit_width_button.setText("Fit Width")
        self.fit_width_button.clicked.connect(
            lambda: self.tab_call("enable_fit_width")
        )
        toolbar.addWidget(self.fit_width_button)

        self.reset_zoom_button = QToolButton()
        self.reset_zoom_button.setText("100%")
        self.reset_zoom_button.setToolTip("Reset zoom")
        self.reset_zoom_button.clicked.connect(
            lambda: self.tab_call("reset_zoom")
        )
        toolbar.addWidget(self.reset_zoom_button)

        toolbar.addSeparator()

        self.select_button = QToolButton()
        self.select_button.setText("Select")
        self.select_button.setCheckable(True)
        self.select_button.setChecked(True)
        self.select_button.setToolTip("Select text, Ctrl+C to copy")

        self.highlight_button = QToolButton()
        self.highlight_button.setText("Highlight")
        self.highlight_button.setCheckable(True)
        self.highlight_button.setToolTip("Drag over text to highlight")

        self.underline_button = QToolButton()
        self.underline_button.setText("Underline")
        self.underline_button.setCheckable(True)
        self.underline_button.setToolTip("Drag over text to underline")

        self.strikeout_button = QToolButton()
        self.strikeout_button.setText("Strike")
        self.strikeout_button.setCheckable(True)
        self.strikeout_button.setToolTip("Drag over text to strike through")

        self.eraser_button = QToolButton()
        self.eraser_button.setText("Eraser")
        self.eraser_button.setCheckable(True)
        self.eraser_button.setToolTip("Click an annotation to delete it")

        self.image_button = QToolButton()
        self.image_button.setText("Image")
        self.image_button.setCheckable(True)
        self.image_button.setToolTip(
            "Drag a box around a picture to save it as an image"
        )

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
            toolbar.addWidget(button)

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

        toolbar.addSeparator()

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search in PDF...  (Ctrl+F)")
        self.search_input.setFixedWidth(200)
        self.search_input.returnPressed.connect(self.run_search)
        toolbar.addWidget(self.search_input)

        self.search_button = QToolButton()
        self.search_button.setText("Search")
        self.search_button.clicked.connect(self.run_search)
        toolbar.addWidget(self.search_button)

        self.prev_result_button = QToolButton()
        self.prev_result_button.setText("<")
        self.prev_result_button.setToolTip("Previous result")
        self.prev_result_button.clicked.connect(
            lambda: self.tab_call("show_previous_result")
        )
        toolbar.addWidget(self.prev_result_button)

        self.next_result_button = QToolButton()
        self.next_result_button.setText(">")
        self.next_result_button.setToolTip("Next result")
        self.next_result_button.clicked.connect(
            lambda: self.tab_call("show_next_result")
        )
        toolbar.addWidget(self.next_result_button)

        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("File")

        open_action = QAction("Open PDF", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_pdf_file)
        file_menu.addAction(open_action)

        close_tab_action = QAction("Close Tab", self)
        close_tab_action.setShortcut(QKeySequence("Ctrl+W"))
        close_tab_action.triggered.connect(self.close_current_tab)
        file_menu.addAction(close_tab_action)

        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        self.view_menu = menu_bar.addMenu("View")

    def create_docks(self):
        self.thumbnails_dock = QDockWidget("Thumbnails", self)
        self.thumbnails_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.thumbnails_list = QListWidget()
        self.thumbnails_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.thumbnails_list.setIconSize(QSize(110, 150))
        self.thumbnails_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.thumbnails_list.setMovement(QListWidget.Movement.Static)
        self.thumbnails_list.setSpacing(12)
        self.thumbnails_list.itemClicked.connect(self.open_thumbnail)
        self.thumbnails_dock.setWidget(self.thumbnails_list)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.thumbnails_dock
        )

        self.bookmarks_dock = QDockWidget("Bookmarks", self)
        self.bookmarks_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        bookmarks_content = QWidget()
        bookmarks_layout = QVBoxLayout()
        bookmarks_hint = QLabel("Bookmark the current page. (Ctrl+B)")
        bookmarks_hint.setWordWrap(True)
        self.bookmark_label_input = QLineEdit()
        self.bookmark_label_input.setPlaceholderText(
            "Example: Important result"
        )
        self.add_bookmark_button = QPushButton("Add bookmark")
        self.bookmark_list = QListWidget()
        self.delete_bookmark_button = QPushButton("Delete selected")
        bookmarks_layout.addWidget(bookmarks_hint)
        bookmarks_layout.addWidget(self.bookmark_label_input)
        bookmarks_layout.addWidget(self.add_bookmark_button)
        bookmarks_layout.addWidget(self.bookmark_list)
        bookmarks_layout.addWidget(self.delete_bookmark_button)
        bookmarks_content.setLayout(bookmarks_layout)
        self.bookmarks_dock.setWidget(bookmarks_content)
        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea, self.bookmarks_dock
        )

        self.tabifyDockWidget(self.thumbnails_dock, self.bookmarks_dock)
        self.thumbnails_dock.raise_()

        self.add_bookmark_button.clicked.connect(self.add_bookmark)
        self.delete_bookmark_button.clicked.connect(
            self.delete_selected_bookmark
        )
        self.bookmark_list.itemDoubleClicked.connect(self.open_bookmark)

        self.tools_dock = QDockWidget("Tools", self)
        self.tools_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.tools_tabs = QTabWidget()

        metadata_widget = QWidget()
        metadata_layout = QVBoxLayout()
        self.metadata_label = QLabel("Open a PDF to see its details.")
        self.metadata_label.setWordWrap(True)
        self.metadata_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        metadata_layout.addWidget(self.metadata_label)
        metadata_widget.setLayout(metadata_layout)
        self.tools_tabs.addTab(metadata_widget, "Metadata")

        notes_widget = QWidget()
        notes_layout = QVBoxLayout()
        notes_hint = QLabel("Write a note for the current page.")
        notes_hint.setWordWrap(True)
        self.note_input = QTextEdit()
        self.note_input.setPlaceholderText("Write your note here...")
        self.note_input.setMinimumHeight(110)
        self.add_note_button = QPushButton("Save note")
        self.note_list = QListWidget()
        self.delete_note_button = QPushButton("Delete selected")
        notes_layout.addWidget(notes_hint)
        notes_layout.addWidget(self.note_input)
        notes_layout.addWidget(self.add_note_button)
        notes_layout.addWidget(self.note_list)
        notes_layout.addWidget(self.delete_note_button)
        notes_widget.setLayout(notes_layout)
        self.tools_tabs.addTab(notes_widget, "Notes")

        ai_widget = QWidget()
        ai_layout = QVBoxLayout()
        ai_info = QLabel(
            "Ask questions about this PDF, generate summaries, "
            "and chat with your document.\n\n"
            "AI features are coming soon."
        )
        ai_info.setWordWrap(True)
        self.ai_input = QTextEdit()
        self.ai_input.setPlaceholderText("Ask something about this PDF...")
        self.ai_input.setEnabled(False)
        self.ai_button = QPushButton("Ask AI")
        self.ai_button.setEnabled(False)
        ai_layout.addWidget(ai_info)
        ai_layout.addWidget(self.ai_input)
        ai_layout.addWidget(self.ai_button)
        ai_widget.setLayout(ai_layout)
        self.tools_tabs.addTab(ai_widget, "AI Hub")

        self.tools_dock.setWidget(self.tools_tabs)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.tools_dock
        )

        self.add_note_button.clicked.connect(self.add_note)
        self.delete_note_button.clicked.connect(self.delete_selected_note)
        self.note_list.itemDoubleClicked.connect(self.open_note)

        self.view_menu.addAction(self.thumbnails_dock.toggleViewAction())
        self.view_menu.addAction(self.bookmarks_dock.toggleViewAction())
        self.view_menu.addAction(self.tools_dock.toggleViewAction())

    def create_shortcuts(self):
        QShortcut(
            QKeySequence(Qt.Key.Key_Left), self,
            activated=lambda: self.tab_call("show_previous_page"),
        )
        QShortcut(
            QKeySequence(Qt.Key.Key_Right), self,
            activated=lambda: self.tab_call("show_next_page"),
        )
        QShortcut(
            QKeySequence("Ctrl+F"), self, activated=self.focus_search,
        )
        QShortcut(
            QKeySequence("Ctrl+B"), self, activated=self.add_bookmark,
        )
        QShortcut(
            QKeySequence("Ctrl++"), self,
            activated=lambda: self.tab_call("zoom_in"),
        )
        QShortcut(
            QKeySequence("Ctrl+-"), self,
            activated=lambda: self.tab_call("zoom_out"),
        )
        QShortcut(
            QKeySequence.StandardKey.Copy, self,
            activated=self.copy_selected_text,
        )

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow, QDialog { background-color: #1e2430; }
            QWidget { color: #e6e9f0; font-size: 13px; }
            QToolBar {
                background: #232b3a; border: none;
                padding: 6px; spacing: 6px;
            }
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 8px;
                padding: 6px 10px;
                color: #e6e9f0;
            }
            QToolButton:hover { background: #2f3a4f; }
            QToolButton:checked {
                background: #14b8a6; color: #062621; font-weight: bold;
            }
            QToolButton:disabled { color: #5b6472; }
            QPushButton {
                background: #2f3a4f;
                border: 1px solid #3a4763;
                border-radius: 8px;
                padding: 6px 12px;
            }
            QPushButton:hover { background: #3a4763; }
            QPushButton:pressed { background: #14b8a6; color: #062621; }
            QPushButton:disabled { color: #5b6472; background: #262e3d; }
            QLineEdit, QSpinBox, QTextEdit {
                background: #171d29;
                border: 1px solid #3a4763;
                border-radius: 8px;
                padding: 5px 8px;
                selection-background-color: #14b8a6;
            }
            QLineEdit:focus, QSpinBox:focus, QTextEdit:focus {
                border: 1px solid #14b8a6;
            }
            QListWidget {
                background: #232b3a; border: none;
                border-radius: 10px; padding: 6px;
            }
            QListWidget::item { border-radius: 6px; padding: 6px; }
            QListWidget::item:selected {
                background: #14b8a6; color: #062621;
            }
            QListWidget::item:hover { background: #2f3a4f; }
            QTabWidget::pane { border: none; background: #1e2430; }
            QTabBar::tab {
                background: #232b3a; color: #9aa4b5;
                padding: 8px 16px; margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            QTabBar::tab:selected {
                background: #14b8a6; color: #062621; font-weight: bold;
            }
            QTabBar::tab:hover:!selected { background: #2f3a4f; }
            QDockWidget { color: #e6e9f0; font-weight: bold; }
            QDockWidget::title { background: #232b3a; padding: 8px; }
            QStatusBar { background: #232b3a; color: #9aa4b5; }
            QMenuBar { background: #232b3a; }
            QMenuBar::item:selected { background: #14b8a6; color: #062621; }
            QMenu { background: #232b3a; border: 1px solid #3a4763; }
            QMenu::item:selected { background: #14b8a6; color: #062621; }
            QScrollBar:vertical { background: #1e2430; width: 12px; }
            QScrollBar::handle:vertical {
                background: #3a4763; border-radius: 6px; min-height: 30px;
            }
            QScrollBar::handle:vertical:hover { background: #14b8a6; }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
            QScrollBar:horizontal { background: #1e2430; height: 12px; }
            QScrollBar::handle:horizontal {
                background: #3a4763; border-radius: 6px; min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover { background: #14b8a6; }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal { width: 0; }
            QLabel { color: #e6e9f0; }
        """)

    def current_tab(self):
        return self.tabs.currentWidget()

    def tab_call(self, method_name, *args):
        tab = self.current_tab()
        if tab is not None:
            getattr(tab, method_name)(*args)

    def focus_search(self):
        if self.current_tab() is None:
            return
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

    def set_tool_mode(self, mode):
        self.current_tool_mode = mode
        tab = self.current_tab()
        if tab is not None:
            tab.set_mode(mode)

    def sync_tool_buttons(self, tab):
        mapping = {
            "select": self.select_button,
            "highlight": self.highlight_button,
            "underline": self.underline_button,
            "strikeout": self.strikeout_button,
            "eraser": self.eraser_button,
            "image": self.image_button,
        }
        button = mapping.get(tab.annotation_mode, self.select_button)
        button.setChecked(True)

    def set_tools_enabled(self, enabled):
        widgets = [
            self.prev_button, self.next_button, self.page_input,
            self.zoom_out_button, self.zoom_in_button,
            self.fit_width_button, self.reset_zoom_button,
            self.select_button, self.highlight_button,
            self.underline_button, self.strikeout_button,
            self.eraser_button, self.image_button,
            self.search_input, self.search_button,
            self.prev_result_button, self.next_result_button,
            self.bookmark_label_input, self.add_bookmark_button,
            self.bookmark_list, self.delete_bookmark_button,
            self.note_input, self.add_note_button,
            self.note_list, self.delete_note_button,
            self.thumbnails_list,
        ]
        for widget in widgets:
            widget.setEnabled(enabled)

    def update_zoom_label(self, text):
        self.zoom_label.setText(text)

    def on_tab_page_changed(self, page):
        tab = self.current_tab()
        if tab is None or tab.document is None:
            return
        if page >= tab.document.page_count:
            return
        self.page_input.blockSignals(True)
        self.page_input.setValue(page + 1)
        self.page_input.blockSignals(False)
        self.thumbnails_list.blockSignals(True)
        self.thumbnails_list.setCurrentRow(page)
        self.thumbnails_list.blockSignals(False)

    def open_pdf_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, "Open PDF", str(Path.home()), "PDF files (*.pdf)",
        )
        if not file_name:
            return
        self.open_pdf_in_new_tab(file_name)

    def open_pdf_in_new_tab(self, file_name):
        try:
            tab = PDFTab(file_name)
        except Exception as error:
            QMessageBox.critical(self, "Could not open PDF", str(error))
            return
        tab.status_message.connect(self.statusBar().showMessage)
        tab.zoom_changed.connect(self.update_zoom_label)
        tab.page_changed.connect(self.on_tab_page_changed)
        index = self.tabs.addTab(tab, tab.pdf_path.name)
        self.tabs.setCurrentIndex(index)
        self.set_tools_enabled(True)

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
        index = self.tabs.currentIndex()
        if index >= 0:
            self.close_tab(index)

    def on_tab_changed(self, index):
        tab = self.tabs.widget(index)
        if tab is None or tab.document is None:
            return
        self.set_tools_enabled(True)
        self.page_input.blockSignals(True)
        self.page_input.setMaximum(tab.document.page_count)
        self.page_input.setValue(tab.current_page + 1)
        self.page_input.blockSignals(False)
        self.total_pages_label.setText(f"/ {tab.document.page_count}")
        self.sync_tool_buttons(tab)
        percent = round(tab.zoom_dpi / 120 * 100)
        self.zoom_label.setText(
            "Fit" if tab.fit_width else f"{percent}%"
        )
        self.build_thumbnails()
        self.refresh_metadata()
        self.refresh_bookmarks()
        self.refresh_notes()
        self.setWindowTitle(f"PDF Pro - {tab.pdf_path.name}")

    def build_thumbnails(self):
        self.thumbnails_list.clear()
        tab = self.current_tab()
        if tab is None or tab.document is None:
            return
        for page_number in range(tab.document.page_count):
            page = tab.document[page_number]
            pix = page.get_pixmap(dpi=24)
            qimage = QImage(
                pix.samples, pix.width, pix.height, pix.stride,
                QImage.Format.Format_RGB888,
            ).copy()
            icon = QIcon(QPixmap.fromImage(qimage))
            item = QListWidgetItem(icon, f"P{page_number + 1}")
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.thumbnails_list.addItem(item)
        self.thumbnails_list.blockSignals(True)
        self.thumbnails_list.setCurrentRow(tab.current_page)
        self.thumbnails_list.blockSignals(False)

    def open_thumbnail(self, item):
        tab = self.current_tab()
        if tab is not None:
            tab.change_page(self.thumbnails_list.row(item))

    def refresh_metadata(self):
        tab = self.current_tab()
        if tab is None or tab.document is None:
            self.metadata_label.setText("Open a PDF to see its details.")
            return
        meta = tab.document.metadata or {}
        created = meta.get("creationDate") or ""
        if created.startswith("D:") and len(created) >= 10:
            created = f"{created[2:6]}-{created[6:8]}-{created[8:10]}"
        lines = [
            f"<b>Title:</b> {meta.get('title') or '-'}",
            f"<b>Author:</b> {meta.get('author') or '-'}",
            f"<b>Subject:</b> {meta.get('subject') or '-'}",
            f"<b>Creator:</b> {meta.get('creator') or '-'}",
            f"<b>Created:</b> {created or '-'}",
            f"<b>Pages:</b> {tab.document.page_count}",
            f"<b>File:</b> {tab.pdf_path.name}",
        ]
        self.metadata_label.setText("<br><br>".join(lines))

    def refresh_bookmarks(self):
        self.bookmark_list.clear()
        tab = self.current_tab()
        if tab is None:
            return
        for index, bookmark in enumerate(tab.bookmarks):
            item = QListWidgetItem(
                f"Page {bookmark['page_number'] + 1}: {bookmark['label']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.bookmark_list.addItem(item)

    def add_bookmark(self):
        tab = self.current_tab()
        if tab is None:
            return
        label = self.bookmark_label_input.text().strip()
        if not label:
            label = f"Page {tab.current_page + 1}"
        already_exists = any(
            b["page_number"] == tab.current_page and b["label"] == label
            for b in tab.bookmarks
        )
        if already_exists:
            QMessageBox.information(
                self, "Bookmark already exists",
                "A bookmark with this label already exists "
                "for the current page.",
            )
            return
        tab.bookmarks.append({
            "page_number": tab.current_page,
            "label": label,
        })
        tab.save_data()
        self.bookmark_label_input.clear()
        self.refresh_bookmarks()
        self.statusBar().showMessage(
            f"Saved bookmark for page {tab.current_page + 1}.", 3000
        )

    def open_bookmark(self, item):
        tab = self.current_tab()
        if tab is None:
            return
        bookmark = tab.bookmarks[item.data(Qt.ItemDataRole.UserRole)]
        tab.change_page(bookmark["page_number"])

    def delete_selected_bookmark(self):
        tab = self.current_tab()
        if tab is None:
            return
        selected = self.bookmark_list.selectedItems()
        if not selected:
            QMessageBox.information(
                self, "No bookmark selected",
                "Select a bookmark from the list first.",
            )
            return
        index = selected[0].data(Qt.ItemDataRole.UserRole)
        bookmark = tab.bookmarks[index]
        answer = QMessageBox.question(
            self, "Delete bookmark",
            f"Delete bookmark:\n\n"
            f"Page {bookmark['page_number'] + 1}: {bookmark['label']}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        tab.bookmarks.pop(index)
        tab.save_data()
        self.refresh_bookmarks()
        self.statusBar().showMessage("Bookmark deleted.", 3000)

    def refresh_notes(self):
        self.note_list.clear()
        tab = self.current_tab()
        if tab is None:
            return
        for index, note in enumerate(tab.notes):
            preview = note["text"].replace("\n", " ").strip()
            if len(preview) > 55:
                preview = preview[:55] + "..."
            item = QListWidgetItem(
                f"Page {note['page_number'] + 1}: {preview}\n"
                f"{note['created_at']}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.note_list.addItem(item)

    def add_note(self):
        tab = self.current_tab()
        if tab is None:
            return
        note_text = self.note_input.toPlainText().strip()
        if not note_text:
            QMessageBox.information(
                self, "Empty note", "Write a note before saving."
            )
            return
        tab.notes.append({
            "page_number": tab.current_page,
            "text": note_text,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })
        tab.save_data()
        self.note_input.clear()
        self.refresh_notes()
        self.statusBar().showMessage(
            f"Saved note for page {tab.current_page + 1}.", 3000
        )

    def open_note(self, item):
        tab = self.current_tab()
        if tab is None:
            return
        note = tab.notes[item.data(Qt.ItemDataRole.UserRole)]
        tab.change_page(note["page_number"])

    def delete_selected_note(self):
        tab = self.current_tab()
        if tab is None:
            return
        selected = self.note_list.selectedItems()
        if not selected:
            QMessageBox.information(
                self, "No note selected",
                "Select a note from the list first.",
            )
            return
        index = selected[0].data(Qt.ItemDataRole.UserRole)
        note = tab.notes[index]
        preview = note["text"].replace("\n", " ").strip()
        if len(preview) > 100:
            preview = preview[:100] + "..."
        answer = QMessageBox.question(
            self, "Delete note",
            f"Delete this note from page {note['page_number'] + 1}?\n\n"
            f"{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        tab.notes.pop(index)
        tab.save_data()
        self.refresh_notes()
        self.statusBar().showMessage("Note deleted.", 3000)

    def copy_selected_text(self):
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QTextEdit)):
            focus.copy()
            return
        tab = self.current_tab()
        if tab is not None:
            tab.copy_selected_text()

    def closeEvent(self, event):
        for index in range(self.tabs.count()):
            tab = self.tabs.widget(index)
            if tab is not None:
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