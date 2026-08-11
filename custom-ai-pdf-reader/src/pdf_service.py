from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


def open_pdf(pdf_path):
    """
    Open and return a PDF document.
    """

    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(
            f"PDF file was not found: {pdf_path}"
        )

    return pymupdf.open(pdf_path)


def get_page_count(document):
    """
    Return the total number of pages in the open PDF.
    """

    return document.page_count


def render_page(
    document,
    page_number,
    dpi=120,
    highlight_rectangles=None
):
    """
    Render one PDF page as a Pillow image.

    highlight_rectangles can contain search result rectangles
    returned by page.search_for().
    """

    if page_number < 0 or page_number >= document.page_count:
        raise ValueError("Page number is outside the PDF range.")

    page = document[page_number]

    pixmap = page.get_pixmap(
        dpi=dpi,
        alpha=False
    )

    image_bytes = pixmap.tobytes("png")

    image = Image.open(
        BytesIO(image_bytes)
    ).convert("RGB")

    if highlight_rectangles:
        scale = dpi / 72

        draw = ImageDraw.Draw(image, "RGBA")

        for rectangle in highlight_rectangles:
            x0 = rectangle.x0 * scale
            y0 = rectangle.y0 * scale
            x1 = rectangle.x1 * scale
            y1 = rectangle.y1 * scale

            draw.rectangle(
                [x0, y0, x1, y1],
                fill=(255, 235, 59, 90),
                outline=(220, 50, 47, 230),
                width=2
            )

    return image


def search_document(document, query):
    """
    Search every page in a PDF.

    Returns a list such as:
    [
        {
            "page_number": 2,
            "rectangles": [Rect(...), Rect(...)]
        }
    ]
    """

    query = query.strip()

    if not query:
        return []

    results = []

    for page_number in range(document.page_count):
        page = document[page_number]

        rectangles = page.search_for(query)

        if rectangles:
            results.append({
                "page_number": page_number,
                "rectangles": rectangles
            })

    return results