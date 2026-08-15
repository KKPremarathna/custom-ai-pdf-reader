from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
)


class PDFPageView(QGraphicsView):
    selection_finished = Signal(QRectF)
    clicked = Signal(QPointF)
    next_page_requested = Signal()
    previous_page_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.pixmap_item = QGraphicsPixmapItem()
        self.scene.addItem(self.pixmap_item)

        self.selection_item = QGraphicsRectItem()

        self.selection_item.setPen(
            QPen(
                QColor(0, 120, 255),
                2,
                Qt.PenStyle.DashLine,
            )
        )

        self.selection_item.setBrush(
            QColor(0, 120, 255, 40)
        )

        self.selection_item.setVisible(False)
        self.scene.addItem(self.selection_item)

        self.selection_start = None
        self.selection_end = None

        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

        self.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform
        )

        self.setBackgroundBrush(QColor("#2b2b2b"))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_page_pixmap(self, pixmap):
        self.pixmap_item.setPixmap(pixmap)
        self.scene.setSceneRect(self.pixmap_item.boundingRect())
        self.clear_selection()

    def clear_selection(self):
        self.selection_start = None
        self.selection_end = None
        self.selection_item.setVisible(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_start = self.mapToScene(
                event.position().toPoint()
            )
            self.selection_end = self.selection_start

            self.selection_item.setRect(
                QRectF(
                    self.selection_start,
                    self.selection_end,
                ).normalized()
            )

            self.selection_item.setVisible(True)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.selection_start is not None:
            self.selection_end = self.mapToScene(
                event.position().toPoint()
            )

            selection_rect = QRectF(
                self.selection_start,
                self.selection_end,
            ).normalized()

            self.selection_item.setRect(selection_rect)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.selection_start is not None
        ):
            self.selection_end = self.mapToScene(
                event.position().toPoint()
            )

            selection_rect = QRectF(
                self.selection_start,
                self.selection_end,
            ).normalized()

            release_position = self.selection_end
            self.selection_start = None

            if (
                selection_rect.width() > 4
                and selection_rect.height() > 4
            ):
                self.selection_finished.emit(selection_rect)
            else:
                self.clear_selection()
                self.clicked.emit(release_position)

            event.accept()
            return

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        vertical_bar = self.verticalScrollBar()
        wheel_delta = event.angleDelta().y()

        at_top = vertical_bar.value() <= vertical_bar.minimum()
        at_bottom = vertical_bar.value() >= vertical_bar.maximum()

        if wheel_delta < 0 and at_bottom:
            self.next_page_requested.emit()
            event.accept()
            return

        if wheel_delta > 0 and at_top:
            self.previous_page_requested.emit()
            event.accept()
            return

        super().wheelEvent(event)