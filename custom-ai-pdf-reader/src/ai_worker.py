from PySide6.QtCore import QThread, Signal

from src.ollama_service import (
    OllamaError,
    summarize_document,
    summarize_text,
)


class SummaryWorker(QThread):
    finished_summary = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        model,
        text,
        whole_document=False,
        parent=None,
    ):
        super().__init__(parent)

        self.model = model
        self.text = text
        self.whole_document = whole_document

    def run(self):
        try:
            if self.whole_document:
                def update_progress(current, total):
                    self.progress.emit(
                        f"Summarizing section {current} of {total}..."
                    )

                summary = summarize_document(
                    model=self.model,
                    text=self.text,
                    progress_callback=update_progress,
                )

            else:
                self.progress.emit(
                    "Generating summary..."
                )

                summary = summarize_text(
                    model=self.model,
                    text=self.text,
                )

        except OllamaError as error:
            self.failed.emit(str(error))
            return

        except Exception as error:
            self.failed.emit(
                f"Unexpected AI error: {error}"
            )
            return

        self.finished_summary.emit(summary)