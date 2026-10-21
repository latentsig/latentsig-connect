from io import BytesIO
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImage(ValueError):
    pass


def decode_and_prepare(data: bytes) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image_context = Image.open(BytesIO(data))
            with image_context as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise InvalidImage("Upload a JPG, PNG or WEBP image.")
                if image.width * image.height > 40_000_000:
                    raise InvalidImage("The image resolution is too large. Choose a smaller photo.")
                image = ImageOps.exif_transpose(image).convert("RGB")
                image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
                if min(image.size) < 80:
                    raise InvalidImage("The image is too small. Choose a clearer photo of the card.")
                prepared = BytesIO()
                image.save(prepared, format="JPEG", quality=92, optimize=True)
                return prepared.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("We couldn’t read that image. Try another photo.") from None



def detect_image_mime(data: bytes) -> str:
    try:
        with Image.open(BytesIO(data)) as image:
            actual = image.format
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("We couldn’t read that image. Try another photo.") from None
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}.get(actual or "")
    if mime is None:
        raise InvalidImage("Upload a JPG, PNG or WEBP image.")
    return mime
