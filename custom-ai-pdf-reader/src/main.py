import sys
from datetime import datetime
from pathlib import Path
from PIL import ImageDraw

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import (
    QAction,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from src.pdf_service import (
    get_page_count,
    open_pdf,
    render_page,
    search_document,
)

from src.reader_state import reader_state

from src.storage_service import (
    load_document_data,
    save_document_data,
)


class PDFReaderWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.document = None
        self.pdf_path = None
        self.document_id = None

        self.setWindowTitle("Custom AI PDF Reader")
        self.resize(1250, 850)

        self.create_actions()
        self.create_toolbar()
        self.create_reader_interface()
        self.create_bookmarks_dock()
        self.create_notes_dock()
        self.create_annotations_dock()
        self.create_keyboard_shortcuts()

        self.statusBar().showMessage("Open a PDF to begin.")

    # =====================================================
    # ACTIONS, MENU, TOOLBAR, AND SHORTCUTS
    # =====================================================

    def create_actions(self):
        self.open_action = QAction("Open PDF", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_pdf_file)

        self.exit_action = QAction("Exit", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.exit_action.triggered.connect(self.close)

    def create_toolbar(self):
        toolbar = QToolBar("Reader controls")
        toolbar.setMovable(False)

        self.addToolBar(toolbar)

        toolbar.addAction(self.open_action)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search in PDF...")
        self.search_input.setMinimumWidth(220)

        self.search_button = QPushButton("Search")

        self.previous_result_button = QPushButton("◀ Result")
        self.next_result_button = QPushButton("Result ▶")

        self.search_status = QLabel("")

        self.highlight_button = QPushButton("Highlight")

        self.underline_button = QPushButton("Underline")

        self.strikeout_button = QPushButton("Strike")

        toolbar.addSeparator()
        toolbar.addWidget(self.search_input)
        toolbar.addWidget(self.search_button)
        toolbar.addWidget(self.previous_result_button)
        toolbar.addWidget(self.next_result_button)
        toolbar.addWidget(self.search_status)
        toolbar.addSeparator()

        toolbar.addWidget(self.highlight_button)

        toolbar.addWidget(self.underline_button)

        toolbar.addWidget(self.strikeout_button)

        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        self.view_menu = menu_bar.addMenu("View")

        self.search_button.clicked.connect(self.run_search)

        self.previous_result_button.clicked.connect(
            self.show_previous_result
        )

        self.next_result_button.clicked.connect(
            self.show_next_result
        )

        self.search_input.returnPressed.connect(
            self.run_search
        )

        self.highlight_button.clicked.connect(
            lambda: self.add_annotation("highlight")
        )

        self.underline_button.clicked.connect(
            lambda: self.add_annotation("underline")
        )

        self.strikeout_button.clicked.connect(
            lambda: self.add_annotation("strikeout")
        )

        self.set_search_controls_enabled(False)

    def create_keyboard_shortcuts(self):
        QShortcut(
            QKeySequence(Qt.Key.Key_Left),
            self,
            activated=self.show_previous_page
        )

        QShortcut(
            QKeySequence(Qt.Key.Key_Right),
            self,
            activated=self.show_next_page
        )

        QShortcut(
            QKeySequence("Ctrl+F"),
            self,
            activated=self.focus_search
        )

        QShortcut(
            QKeySequence("Ctrl+B"),
            self,
            activated=self.add_bookmark
        )

        QShortcut(
            QKeySequence("Ctrl++"),
            self,
            activated=self.zoom_in
        )

        QShortcut(
            QKeySequence("Ctrl+-"),
            self,
            activated=self.zoom_out
        )

    def focus_search(self):
        if self.document is None:
            return

        self.search_input.setFocus()
        self.search_input.selectAll()

    # =====================================================
    # MAIN PDF READER AREA
    # =====================================================

    def create_reader_interface(self):
        self.image_label = QLabel(
            "Open a PDF to display its first page."
        )

        self.image_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.image_label.setStyleSheet(
            """
            QLabel {
                background-color: #f3f5f7;
                color: #4a5560;
            }
            """
        )

        self.scroll_area = QScrollArea()

        self.scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.scroll_area.setWidget(
            self.image_label
        )

        self.scroll_area.setWidgetResizable(False)

        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        self.scroll_area.viewport().installEventFilter(
            self
        )

        self.fit_to_window = True

        self.original_pixmap = None

        self.previous_button = QPushButton(
            "◀ Previous"
        )

        self.next_button = QPushButton(
            "Next ▶"
        )

        self.zoom_out_button = QPushButton(
            "− Zoom"
        )

        self.zoom_in_button = QPushButton(
            "+ Zoom"
        )

        self.fit_page_button = QPushButton(
            "Fit page"
        )

        self.page_input = QSpinBox()

        self.page_input.setMinimum(1)
        self.page_input.setMaximum(1)
        self.page_input.setPrefix("Page ")

        self.go_button = QPushButton("Go")

        self.page_label = QLabel("No PDF open")

        self.zoom_label = QLabel(
            "Render: 120 DPI"
        )

        controls = QHBoxLayout()

        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)

        controls.addSpacing(12)

        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.zoom_in_button)
        controls.addWidget(self.fit_page_button)

        controls.addSpacing(12)

        controls.addWidget(self.page_input)
        controls.addWidget(self.go_button)

        controls.addStretch()

        controls.addWidget(self.page_label)

        controls.addSpacing(16)

        controls.addWidget(self.zoom_label)

        root_layout = QVBoxLayout()

        root_layout.setContentsMargins(0, 0, 0, 0)

        root_layout.addWidget(self.scroll_area)

        root_layout.addLayout(controls)

        central_widget = QWidget()

        central_widget.setLayout(root_layout)

        self.setCentralWidget(central_widget)

        self.previous_button.clicked.connect(
            self.show_previous_page
        )

        self.next_button.clicked.connect(
            self.show_next_page
        )

        self.go_button.clicked.connect(
            self.go_to_page
        )

        self.zoom_out_button.clicked.connect(
            self.zoom_out
        )

        self.zoom_in_button.clicked.connect(
            self.zoom_in
        )

        self.fit_page_button.clicked.connect(
            self.fit_page_to_window
        )

        self.set_reader_controls_enabled(False)

    def set_reader_controls_enabled(self, enabled):
        self.previous_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)

        self.zoom_out_button.setEnabled(enabled)
        self.zoom_in_button.setEnabled(enabled)
        self.fit_page_button.setEnabled(enabled)

        self.page_input.setEnabled(enabled)
        self.go_button.setEnabled(enabled)

    # =====================================================
    # BOOKMARKS SIDEBAR
    # =====================================================

    def create_bookmarks_dock(self):
        self.bookmarks_dock = QDockWidget(
            "Bookmarks",
            self
        )

        self.bookmarks_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        dock_content = QWidget()

        dock_layout = QVBoxLayout()

        instructions = QLabel(
            "Add a bookmark for the current page."
        )

        instructions.setWordWrap(True)

        self.bookmark_label_input = QLineEdit()

        self.bookmark_label_input.setPlaceholderText(
            "Example: Important result"
        )

        self.add_bookmark_button = QPushButton(
            "☆ Add bookmark"
        )

        self.delete_bookmark_button = QPushButton(
            "Delete selected"
        )

        self.bookmark_list = QListWidget()

        dock_layout.addWidget(instructions)
        dock_layout.addWidget(self.bookmark_label_input)
        dock_layout.addWidget(self.add_bookmark_button)
        dock_layout.addWidget(self.bookmark_list)
        dock_layout.addWidget(self.delete_bookmark_button)

        dock_content.setLayout(dock_layout)

        self.bookmarks_dock.setWidget(dock_content)

        self.addDockWidget(
            Qt.DockWidgetArea.LeftDockWidgetArea,
            self.bookmarks_dock
        )

        self.add_bookmark_button.clicked.connect(
            self.add_bookmark
        )

        self.delete_bookmark_button.clicked.connect(
            self.delete_selected_bookmark
        )

        self.bookmark_list.itemDoubleClicked.connect(
            self.open_bookmark
        )

        self.view_menu.addAction(
            self.bookmarks_dock.toggleViewAction()
        )

        self.set_bookmark_controls_enabled(False)

    def set_bookmark_controls_enabled(self, enabled):
        self.bookmark_label_input.setEnabled(enabled)
        self.add_bookmark_button.setEnabled(enabled)
        self.delete_bookmark_button.setEnabled(enabled)
        self.bookmark_list.setEnabled(enabled)

    def refresh_bookmarks(self):
        self.bookmark_list.clear()

        for index, bookmark in enumerate(
            reader_state["bookmarks"]
        ):
            page_number = bookmark["page_number"]
            label = bookmark["label"]

            item = QListWidgetItem(
                f"Page {page_number + 1}: {label}"
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                index
            )

            self.bookmark_list.addItem(item)

    def add_bookmark(self):
        if self.document is None:
            return

        current_page = reader_state["current_page"]

        label = self.bookmark_label_input.text().strip()

        if not label:
            label = f"Page {current_page + 1}"

        already_exists = any(
            bookmark["page_number"] == current_page
            and bookmark["label"] == label
            for bookmark in reader_state["bookmarks"]
        )

        if already_exists:
            QMessageBox.information(
                self,
                "Bookmark already exists",
                "A bookmark with this label already exists "
                "for the current page."
            )

            return

        reader_state["bookmarks"].append({
            "page_number": current_page,
            "label": label
        })

        self.save_current_reader_data()

        self.bookmark_label_input.clear()

        self.refresh_bookmarks()

        self.statusBar().showMessage(
            f"Saved bookmark for page {current_page + 1}.",
            3000
        )

    def open_bookmark(self, item):
        bookmark_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        bookmark = reader_state["bookmarks"][
            bookmark_index
        ]

        self.change_page(bookmark["page_number"])

    def delete_selected_bookmark(self):
        selected_items = self.bookmark_list.selectedItems()

        if not selected_items:
            QMessageBox.information(
                self,
                "No bookmark selected",
                "Select a bookmark from the list first."
            )

            return

        item = selected_items[0]

        bookmark_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        bookmark = reader_state["bookmarks"][
            bookmark_index
        ]

        answer = QMessageBox.question(
            self,
            "Delete bookmark",
            (
                f"Delete bookmark:\n\n"
                f"Page {bookmark['page_number'] + 1}: "
                f"{bookmark['label']}?"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        reader_state["bookmarks"].pop(bookmark_index)

        self.save_current_reader_data()

        self.refresh_bookmarks()

        self.statusBar().showMessage(
            "Bookmark deleted.",
            3000
        )

    # =====================================================
    # NOTES SIDEBAR
    # =====================================================

    def create_notes_dock(self):
        self.notes_dock = QDockWidget(
            "Notes",
            self
        )

        self.notes_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        dock_content = QWidget()

        dock_layout = QVBoxLayout()

        instructions = QLabel(
            "Write a note for the current page."
        )

        instructions.setWordWrap(True)

        self.note_input = QTextEdit()

        self.note_input.setPlaceholderText(
            "Write your note here..."
        )

        self.note_input.setMinimumHeight(120)

        self.add_note_button = QPushButton(
            "Save note"
        )

        self.delete_note_button = QPushButton(
            "Delete selected"
        )

        self.note_list = QListWidget()

        dock_layout.addWidget(instructions)
        dock_layout.addWidget(self.note_input)
        dock_layout.addWidget(self.add_note_button)
        dock_layout.addWidget(self.note_list)
        dock_layout.addWidget(self.delete_note_button)

        dock_content.setLayout(dock_layout)

        self.notes_dock.setWidget(dock_content)

        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self.notes_dock
        )

        self.add_note_button.clicked.connect(
            self.add_note
        )

        self.delete_note_button.clicked.connect(
            self.delete_selected_note
        )

        self.note_list.itemDoubleClicked.connect(
            self.open_note
        )

        self.view_menu.addAction(
            self.notes_dock.toggleViewAction()
        )

        self.set_note_controls_enabled(False)

    def create_annotations_dock(self):
        self.annotations_dock = QDockWidget(
            "Annotations",
            self
        )

        self.annotations_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
        )

        dock_content = QWidget()

        dock_layout = QVBoxLayout()

        instructions = QLabel(
            "Search text, then choose Highlight, "
            "Underline, or Strike."
        )

        instructions.setWordWrap(True)

        self.annotation_list = QListWidget()

        self.delete_annotation_button = QPushButton(
            "Delete selected"
        )

        dock_layout.addWidget(instructions)

        dock_layout.addWidget(self.annotation_list)

        dock_layout.addWidget(
            self.delete_annotation_button
        )

        dock_content.setLayout(dock_layout)

        self.annotations_dock.setWidget(
            dock_content
        )

        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea,
            self.annotations_dock
        )

        self.annotation_list.itemDoubleClicked.connect(
            self.open_annotation
        )

        self.delete_annotation_button.clicked.connect(
            self.delete_selected_annotation
        )

        self.view_menu.addAction(
            self.annotations_dock.toggleViewAction()
        )

        self.set_annotation_controls_enabled(False)

    def set_annotation_controls_enabled(self, enabled):
        self.annotation_list.setEnabled(enabled)

        self.delete_annotation_button.setEnabled(enabled)


    def refresh_annotations(self):
        self.annotation_list.clear()

        for index, annotation in enumerate(
            reader_state["annotations"]
        ):
            page_number = annotation["page_number"]

            annotation_type = annotation["type"]

            selected_text = annotation["text"]

            created_at = annotation["created_at"]

            preview = selected_text.replace("\n", " ").strip()

            if len(preview) > 45:
                preview = preview[:45] + "..."

            item = QListWidgetItem(
                f"{annotation_type.title()} — "
                f"Page {page_number + 1}\n"
                f"{preview}\n"
                f"{created_at}"
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                index
            )

            self.annotation_list.addItem(item)


    def open_annotation(self, item):
        annotation_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        annotation = reader_state["annotations"][
            annotation_index
        ]

        self.change_page(
            annotation["page_number"]
        )


    def delete_selected_annotation(self):
        selected_items = self.annotation_list.selectedItems()

        if not selected_items:
            QMessageBox.information(
                self,
                "No annotation selected",
                "Select an annotation from the list first."
            )

            return

        item = selected_items[0]

        annotation_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        annotation = reader_state["annotations"][
            annotation_index
        ]

        answer = QMessageBox.question(
            self,
            "Delete annotation",
            (
                f"Delete this {annotation['type']} "
                f"annotation from page "
                f"{annotation['page_number'] + 1}?"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        reader_state["annotations"].pop(
            annotation_index
        )

        self.save_current_reader_data()

        self.refresh_annotations()

        self.refresh_reader()

        self.statusBar().showMessage(
            "Annotation deleted.",
            3000
    )

    def set_note_controls_enabled(self, enabled):
        self.note_input.setEnabled(enabled)
        self.add_note_button.setEnabled(enabled)
        self.delete_note_button.setEnabled(enabled)
        self.note_list.setEnabled(enabled)

    def refresh_notes(self):
        self.note_list.clear()

        for index, note in enumerate(reader_state["notes"]):
            page_number = note["page_number"]
            note_text = note["text"]
            created_at = note["created_at"]

            preview = note_text.replace("\n", " ").strip()

            if len(preview) > 55:
                preview = preview[:55] + "..."

            item = QListWidgetItem(
                f"Page {page_number + 1}: {preview}\n"
                f"{created_at}"
            )

            item.setData(
                Qt.ItemDataRole.UserRole,
                index
            )

            self.note_list.addItem(item)

    def add_note(self):
        if self.document is None:
            return

        note_text = self.note_input.toPlainText().strip()

        if not note_text:
            QMessageBox.information(
                self,
                "Empty note",
                "Write a note before saving."
            )

            return

        current_page = reader_state["current_page"]

        reader_state["notes"].append({
            "page_number": current_page,
            "text": note_text,
            "created_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
        })

        self.save_current_reader_data()

        self.note_input.clear()

        self.refresh_notes()

        self.statusBar().showMessage(
            f"Saved note for page {current_page + 1}.",
            3000
        )

    def open_note(self, item):
        note_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        note = reader_state["notes"][note_index]

        self.change_page(note["page_number"])

    def delete_selected_note(self):
        selected_items = self.note_list.selectedItems()

        if not selected_items:
            QMessageBox.information(
                self,
                "No note selected",
                "Select a note from the list first."
            )

            return

        item = selected_items[0]

        note_index = item.data(
            Qt.ItemDataRole.UserRole
        )

        note = reader_state["notes"][note_index]

        preview = note["text"].replace("\n", " ").strip()

        if len(preview) > 100:
            preview = preview[:100] + "..."

        answer = QMessageBox.question(
            self,
            "Delete note",
            (
                f"Delete this note from page "
                f"{note['page_number'] + 1}?\n\n"
                f"{preview}"
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        reader_state["notes"].pop(note_index)

        self.save_current_reader_data()

        self.refresh_notes()

        self.statusBar().showMessage(
            "Note deleted.",
            3000
        )

    # =====================================================
    # OPEN PDF AND SAVE DATA
    # =====================================================

    def open_pdf_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open PDF",
            str(Path.home()),
            "PDF files (*.pdf)"
        )

        if not file_name:
            return

        try:
            new_document = open_pdf(file_name)

        except Exception as error:
            QMessageBox.critical(
                self,
                "Could not open PDF",
                str(error)
            )

            return

        if self.document is not None:
            self.save_current_reader_data()

            self.document.close()

        self.document = new_document

        self.pdf_path = Path(file_name)

        self.document_id = str(
            self.pdf_path.resolve()
        )

        saved_data = load_document_data(
            document_id=self.document_id,
            pdf_path=self.pdf_path
        )

        last_page = saved_data.get("last_page", 0)

        if not 0 <= last_page < get_page_count(
            self.document
        ):
            last_page = 0

        reader_state["current_page"] = last_page
        reader_state["zoom_dpi"] = 120
        reader_state["search_results"] = []
        reader_state["search_index"] = 0
        reader_state["annotations"] = []

        reader_state["bookmarks"] = saved_data.get(
            "bookmarks",
            []
        )

        reader_state["notes"] = saved_data.get(
            "notes",
            []
        )
        reader_state["annotations"] = saved_data.get(
            "annotations",
            []
        )

        self.page_input.setMaximum(
            get_page_count(self.document)
        )

        self.setWindowTitle(
            f"Custom AI PDF Reader — {self.pdf_path.name}"
        )

        self.set_reader_controls_enabled(True)

        self.set_bookmark_controls_enabled(True)

        self.set_note_controls_enabled(True)

        self.set_annotation_controls_enabled(True)

        self.set_search_controls_enabled(True)

        self.refresh_reader()

        self.refresh_bookmarks()

        self.refresh_notes()

        self.refresh_annotations()

        self.statusBar().showMessage(
            f"Opened {self.pdf_path.name}"
        )

    def save_current_reader_data(self):
        if self.document is None:
            return

        save_document_data(
            document_id=self.document_id,
            pdf_path=self.pdf_path,
            bookmarks=reader_state["bookmarks"],
            notes=reader_state["notes"],
            annotations=reader_state["annotations"],
            last_page=reader_state["current_page"]
        )

    # =====================================================
    # SEARCH WITH HIGHLIGHTS
    # =====================================================

    def set_search_controls_enabled(self, enabled):
        self.search_input.setEnabled(enabled)
        self.search_button.setEnabled(enabled)
        self.previous_result_button.setEnabled(enabled)
        self.next_result_button.setEnabled(enabled)
        self.highlight_button.setEnabled(enabled)
        self.underline_button.setEnabled(enabled)
        self.strikeout_button.setEnabled(enabled)

    def run_search(self):
        if self.document is None:
            return

        query = self.search_input.text().strip()

        if not query:
            reader_state["search_results"] = []
            reader_state["search_index"] = 0

            self.search_status.setText("Enter search text.")

            self.refresh_reader()

            return

        reader_state["search_results"] = search_document(
            self.document,
            query
        )

        reader_state["search_index"] = 0

        if not reader_state["search_results"]:
            self.search_status.setText("No results.")

            self.refresh_reader()

            return

        self.show_current_search_result()

    def show_current_search_result(self):
        results = reader_state["search_results"]

        if not results:
            return

        result = results[reader_state["search_index"]]

        reader_state["current_page"] = result["page_number"]

        self.save_current_reader_data()

        self.search_status.setText(
            f"Result {reader_state['search_index'] + 1} "
            f"/ {len(results)} "
            f"— Page {result['page_number'] + 1}"
        )

        self.refresh_reader()

    def show_next_result(self):
        results = reader_state["search_results"]

        if not results:
            self.search_status.setText(
                "Search for text first."
            )

            return

        reader_state["search_index"] = (
            reader_state["search_index"] + 1
        ) % len(results)

        self.show_current_search_result()

    def show_previous_result(self):
        results = reader_state["search_results"]

        if not results:
            self.search_status.setText(
                "Search for text first."
            )

            return

        reader_state["search_index"] = (
            reader_state["search_index"] - 1
        ) % len(results)

        self.show_current_search_result()

    def add_annotation(self, annotation_type):
        if self.document is None:
            return

        results = reader_state["search_results"]

        if not results:
            QMessageBox.information(
                self,
                "Search required",
                "Search for text and select a result first."
            )

            return

        current_result = results[
            reader_state["search_index"]
        ]

        search_text = self.search_input.text().strip()

        rectangles = []

        for rect in current_result["rectangles"]:
            rectangles.append([
                rect.x0,
                rect.y0,
                rect.x1,
                rect.y1
            ])

        new_annotation = {
            "page_number": current_result["page_number"],
            "rectangles": rectangles,
            "type": annotation_type,
            "text": search_text,
            "created_at": datetime.now().strftime(
                "%Y-%m-%d %H:%M"
            )
        }

        reader_state["annotations"].append(
            new_annotation
        )

        self.save_current_reader_data()

        self.refresh_annotations()

        self.change_page(
            current_result["page_number"]
        )

        self.statusBar().showMessage(
            f"Saved {annotation_type} annotation.",
            3000
        )

    # =====================================================
    # RENDER PDF PAGE
    # =====================================================

    def refresh_reader(self):
        if self.document is None:
            return

        current_page = reader_state["current_page"]

        dpi = reader_state["zoom_dpi"]

        search_highlights = None

        results = reader_state["search_results"]

        if results:
            current_result = results[
                reader_state["search_index"]
            ]

            if current_result["page_number"] == current_page:
                search_highlights = current_result[
                    "rectangles"
                ]

        try:
            image = render_page(
                document=self.document,
                page_number=current_page,
                dpi=dpi,
                highlight_rectangles=search_highlights
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "Could not render page",
                str(error)
            )

            return

        self.draw_saved_annotations(
            image,
            current_page,
            dpi
        )

        qimage = self.pil_to_qimage(image)

        self.original_pixmap = QPixmap.fromImage(qimage)

        self.update_page_display()

        total_pages = get_page_count(self.document)

        self.page_input.setValue(current_page + 1)

        self.page_label.setText(
            f"Page {current_page + 1} / {total_pages}"
        )

        self.zoom_label.setText(
            f"Render: {dpi} DPI"
        )

        self.previous_button.setEnabled(
            current_page > 0
        )

        self.next_button.setEnabled(
            current_page < total_pages - 1
        )

    def draw_saved_annotations(
            self,
            image,
            page_number,
            dpi
        ):
            draw = ImageDraw.Draw(image, "RGBA")

            scale = dpi / 72

            for annotation in reader_state["annotations"]:
                if annotation["page_number"] != page_number:
                    continue

                annotation_type = annotation["type"]

                for rectangle in annotation["rectangles"]:
                    x0, y0, x1, y1 = rectangle

                    left = x0 * scale
                    top = y0 * scale
                    right = x1 * scale
                    bottom = y1 * scale

                    if annotation_type == "highlight":
                        draw.rectangle(
                            [left, top, right, bottom],
                            fill=(255, 235, 0, 100)
                        )

                    elif annotation_type == "underline":
                        line_y = bottom - 2

                        draw.line(
                            [left, line_y, right, line_y],
                            fill=(0, 100, 255, 255),
                            width=max(2, int(scale * 2))
                        )

                    elif annotation_type == "strikeout":
                        line_y = (top + bottom) / 2

                        draw.line(
                            [left, line_y, right, line_y],
                            fill=(220, 30, 30, 255),
                            width=max(2, int(scale * 2))
                        )

    def update_page_display(self):
        if self.original_pixmap is None:
            return

        if self.fit_to_window:
            viewport_size = self.scroll_area.viewport().size()

            fitted_pixmap = self.original_pixmap.scaled(
                viewport_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self.image_label.setPixmap(fitted_pixmap)

            self.image_label.setFixedSize(
                fitted_pixmap.size()
            )

        else:
            self.image_label.setPixmap(
                self.original_pixmap
            )

            self.image_label.setFixedSize(
                self.original_pixmap.size()
            )


    def fit_page_to_window(self):
        if self.document is None:
            return

        self.fit_to_window = True

        self.update_page_display()

        self.statusBar().showMessage(
            "Page fitted to window.",
            2500
        )


    def eventFilter(self, watched, event):
        if watched == self.scroll_area.viewport():

            if event.type() == QEvent.Type.Wheel:
                return self.handle_page_wheel_event(event)

        return super().eventFilter(watched, event)


    def handle_page_wheel_event(self, event):
        if self.document is None:
            return False

        vertical_bar = self.scroll_area.verticalScrollBar()

        wheel_delta = event.angleDelta().y()

        at_top = vertical_bar.value() == vertical_bar.minimum()

        at_bottom = (
            vertical_bar.value()
            == vertical_bar.maximum()
        )

        if wheel_delta < 0 and at_bottom:
            if reader_state["current_page"] < (
                get_page_count(self.document) - 1
            ):
                self.change_page(
                    reader_state["current_page"] + 1
                )

                vertical_bar.setValue(
                    vertical_bar.minimum()
                )

                return True

        if wheel_delta > 0 and at_top:
            if reader_state["current_page"] > 0:
                self.change_page(
                    reader_state["current_page"] - 1
                )

                vertical_bar.setValue(
                    vertical_bar.maximum()
                )

                return True

        return False


    def resizeEvent(self, event):
        super().resizeEvent(event)

        if self.fit_to_window:
            self.update_page_display()

    @staticmethod
    def pil_to_qimage(image):
        if image.mode != "RGB":
            image = image.convert("RGB")

        image_data = image.tobytes("raw", "RGB")

        qimage = QImage(
            image_data,
            image.width,
            image.height,
            image.width * 3,
            QImage.Format.Format_RGB888
        )

        return qimage.copy()

    # =====================================================
    # PAGE NAVIGATION AND ZOOM
    # =====================================================

    def change_page(self, new_page):
        if self.document is None:
            return

        total_pages = get_page_count(self.document)

        if not 0 <= new_page < total_pages:
            return

        reader_state["current_page"] = new_page

        self.save_current_reader_data()

        self.refresh_reader()

    def show_previous_page(self):
        if self.document is None:
            return

        self.change_page(
            reader_state["current_page"] - 1
        )

    def show_next_page(self):
        if self.document is None:
            return

        self.change_page(
            reader_state["current_page"] + 1
        )

    def go_to_page(self):
        self.change_page(
            self.page_input.value() - 1
        )

    def zoom_out(self):
        if self.document is None:
            return

        if reader_state["zoom_dpi"] > 72:
            self.fit_to_window = False

            reader_state["zoom_dpi"] -= 24

            self.refresh_reader()

    def zoom_in(self):
        if self.document is None:
            return

        if reader_state["zoom_dpi"] < 240:
            self.fit_to_window = False

            reader_state["zoom_dpi"] += 24

            self.refresh_reader()

    # =====================================================
    # CLOSE APPLICATION
    # =====================================================

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