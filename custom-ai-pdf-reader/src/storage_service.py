import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = PROJECT_ROOT / "data" / "reader_data.json"


def load_all_reader_data():
    """
    Read all saved reader information from JSON.
    Returns an empty structure if the file does not exist yet.
    """

    if not DATA_PATH.exists():
        return {
            "documents": {}
        }

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)

        if "documents" not in data:
            data["documents"] = {}

        return data

    except json.JSONDecodeError:
        print("Warning: JSON file could not be read. Starting with empty data.")

        return {
            "documents": {}
        }


def save_all_reader_data(data):
    """
    Save all reader information safely to JSON.
    """

    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = DATA_PATH.with_suffix(".tmp")

    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=2,
            ensure_ascii=False
        )

    os.replace(temporary_path, DATA_PATH)


def load_document_data(document_id, pdf_path):
    """
    Load saved information for one PDF document.
    """

    all_data = load_all_reader_data()

    default_data = {
        "file_name": Path(pdf_path).name,
        "bookmarks": [],
        "notes": [],
        "annotations": [],
        "last_page": 0
    }

    saved_data = all_data["documents"].get(document_id)

    if saved_data:
        default_data.update(saved_data)

    return default_data


def save_document_data(
    document_id,
    pdf_path,
    bookmarks,
    notes,
    annotations,
    last_page
):
    all_data = load_all_reader_data()

    all_data["documents"][document_id] = {
        "file_name": Path(pdf_path).name,
        "bookmarks": bookmarks,
        "notes": notes,
        "annotations": annotations,
        "last_page": last_page
    }

    save_all_reader_data(all_data)