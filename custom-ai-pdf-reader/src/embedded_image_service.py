from pathlib import Path


def get_page_images(document, page_number):
    page = document[page_number]
    seen_xrefs = set()
    images = []

    for image_info in page.get_images(full=True):
        xref = image_info[0]

        if xref in seen_xrefs:
            continue

        seen_xrefs.add(xref)

        try:
            extracted = document.extract_image(xref)
        except Exception:
            continue

        image_bytes = extracted.get("image")
        extension = extracted.get("ext", "png").lower()

        if not image_bytes:
            continue

        images.append({
            "xref": xref,
            "bytes": image_bytes,
            "extension": extension,
            "width": extracted.get("width", 0),
            "height": extracted.get("height", 0),
            "colorspace": extracted.get("colorspace", 0),
            "bpc": extracted.get("bpc", 0),
        })

    return images


def save_image_bytes(image_info, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_info["bytes"])
    return output_path
