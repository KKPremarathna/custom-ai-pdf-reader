import pymupdf
from PIL import Image, ImageDraw


def open_pdf(file_path):
    return pymupdf.open(file_path)


def get_page_count(document):
    return document.page_count


def render_page(
    document,
    page_number,
    dpi=120,
    highlight_rectangles=None,
):
    page = document[page_number]
    pixmap = page.get_pixmap(dpi=dpi)

    image = Image.frombytes(
        "RGB",
        (pixmap.width, pixmap.height),
        pixmap.samples,
    )

    if highlight_rectangles:
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        scale = dpi / 72

        for rect in highlight_rectangles:
            draw.rectangle(
                [
                    rect.x0 * scale,
                    rect.y0 * scale,
                    rect.x1 * scale,
                    rect.y1 * scale,
                ],
                fill=(255, 255, 0, 90),
            )

        image = Image.alpha_composite(
            image.convert("RGBA"),
            overlay,
        ).convert("RGB")

    return image


def search_document(document, query):
    results = []

    for page_number in range(document.page_count):
        page = document[page_number]
        rectangles = page.search_for(query)

        if rectangles:
            results.append({
                "page_number": page_number,
                "rectangles": rectangles,
            })

    return results