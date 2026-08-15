from PIL import Image, ImageOps


def apply_night_mode(image):
    """Return a dark PDF page with inverted page colours.

    The input is a Pillow Image produced by the PDF renderer. The returned
    image is always RGB so it is compatible with the existing Qt conversion.
    """
    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image).convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")

    return ImageOps.invert(image)
