import json

from src import storage_service


def test_loads_empty_data_when_file_does_not_exist(
    monkeypatch,
    tmp_path
):
    temporary_data_path = tmp_path / "reader_data.json"

    monkeypatch.setattr(
        storage_service,
        "DATA_PATH",
        temporary_data_path
    )

    data = storage_service.load_all_reader_data()

    assert data == {
        "documents": {}
    }


def test_saves_and_loads_all_reader_data(
    monkeypatch,
    tmp_path
):
    temporary_data_path = tmp_path / "reader_data.json"

    monkeypatch.setattr(
        storage_service,
        "DATA_PATH",
        temporary_data_path
    )

    original_data = {
        "documents": {
            "example-document": {
                "file_name": "example.pdf",
                "bookmarks": [],
                "notes": [],
                "last_page": 4
            }
        }
    }

    storage_service.save_all_reader_data(original_data)

    loaded_data = storage_service.load_all_reader_data()

    assert loaded_data == original_data


def test_load_document_data_returns_defaults(
    monkeypatch,
    tmp_path
):
    temporary_data_path = tmp_path / "reader_data.json"

    monkeypatch.setattr(
        storage_service,
        "DATA_PATH",
        temporary_data_path
    )

    data = storage_service.load_document_data(
        document_id="new-document",
        pdf_path="research-paper.pdf"
    )

    assert data["file_name"] == "research-paper.pdf"
    assert data["bookmarks"] == []
    assert data["notes"] == []
    assert data["last_page"] == 0


def test_saves_bookmarks_notes_and_last_page(
    monkeypatch,
    tmp_path
):
    temporary_data_path = tmp_path / "reader_data.json"

    monkeypatch.setattr(
        storage_service,
        "DATA_PATH",
        temporary_data_path
    )

    bookmarks = [
        {
            "page_number": 2,
            "label": "Important result"
        }
    ]

    notes = [
        {
            "page_number": 5,
            "text": "Review this figure.",
            "created_at": "2026-08-11 15:58"
        }
    ]

    storage_service.save_document_data(
        document_id="test-document",
        pdf_path="test.pdf",
        bookmarks=bookmarks,
        notes=notes,
        last_page=5
    )

    saved_data = storage_service.load_document_data(
        document_id="test-document",
        pdf_path="test.pdf"
    )

    assert saved_data["file_name"] == "test.pdf"
    assert saved_data["bookmarks"] == bookmarks
    assert saved_data["notes"] == notes
    assert saved_data["last_page"] == 5


def test_saved_json_is_valid(
    monkeypatch,
    tmp_path
):
    temporary_data_path = tmp_path / "reader_data.json"

    monkeypatch.setattr(
        storage_service,
        "DATA_PATH",
        temporary_data_path
    )

    storage_service.save_document_data(
        document_id="json-test",
        pdf_path="paper.pdf",
        bookmarks=[],
        notes=[],
        last_page=0
    )

    with open(
        temporary_data_path,
        "r",
        encoding="utf-8"
    ) as file:
        data = json.load(file)

    assert "documents" in data
    assert "json-test" in data["documents"]