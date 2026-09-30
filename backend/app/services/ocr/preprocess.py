from io import BytesIO
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


class InvalidImage(ValueError):
    pass


def _deskew_if_needed(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=70, minLineLength=max(80, rgb.shape[1] // 8), maxLineGap=18)
    if lines is None:
        return rgb
    angles = []
    for line in lines[:, 0, :]:
        x1, y1, x2, y2 = map(int, line)
        angle = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if abs(angle) <= 12 and np.hypot(x2 - x1, y2 - y1) >= rgb.shape[1] * 0.12:
            angles.append(angle)
    if not angles:
        return rgb
    angle = float(np.median(angles))
    if abs(angle) < 0.7 or abs(angle) > 12:
        return rgb
    height, width = rgb.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    corrected = cv2.warpAffine(rgb, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return corrected


def decode_and_prepare(data: bytes) -> np.ndarray:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image_context = Image.open(BytesIO(data))
        with image_context as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise InvalidImage("Upload a JPG, PNG or WEBP image.")
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((2600, 2600), Image.Resampling.LANCZOS)
            rgb = np.asarray(image)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise InvalidImage("We couldn’t read that image. Try another photo.") from None

    if rgb.size == 0 or min(rgb.shape[:2]) < 80:
        raise InvalidImage("The image is too small. Choose a clearer photo of the card.")

    # Keep original colors. Apply gentle CLAHE only when luminance contrast is low.
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    lightness, a, b = cv2.split(lab)
    if float(lightness.std()) < 38:
        lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
        if float(lightness.std()) < 24:
            lightness = cv2.fastNlMeansDenoising(lightness, None, h=3, templateWindowSize=7, searchWindowSize=21)
        rgb = cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2RGB)
    return np.ascontiguousarray(_deskew_if_needed(rgb))


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
