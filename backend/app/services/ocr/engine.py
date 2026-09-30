import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

# Keep model and inference caches in this app's writable local directory.
# This also makes it easy to prewarm/cache models for disconnected inference.
_cache_dir = Path(__file__).resolve().parents[3] / ".cache" / "paddlex"
_cache_dir.mkdir(parents=True, exist_ok=True)
(_cache_dir / "temp").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_cache_dir))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
tempfile.tempdir = str(_cache_dir / "temp")

from paddleocr import PaddleOCR  # noqa: E402


@lru_cache(maxsize=1)
def get_engine() -> PaddleOCR:
    # Models run in this process. The first startup downloads the configured
    # PaddleOCR models; later inference uses the local model cache.
    return PaddleOCR(
        text_detection_model_name="PP-OCRv5_mobile_det",
        text_recognition_model_name="PP-OCRv5_mobile_rec",
        use_doc_orientation_classify=True,
        use_doc_unwarping=False,
        use_textline_orientation=True,
    )


def recognize(image: Any) -> list[dict[str, Any]]:
    results = get_engine().predict(image)
    blocks: list[dict[str, Any]] = []
    for result in results:
        payload = result.json if hasattr(result, "json") else result
        if callable(payload):
            payload = payload()
        payload = payload.get("res", payload) if isinstance(payload, dict) else {}
        texts = payload.get("rec_texts", [])
        scores = payload.get("rec_scores", [])
        polygons = payload.get("rec_polys", [])
        for index, text in enumerate(texts):
            clean = str(text).strip()
            if not clean:
                continue
            polygon = polygons[index].tolist() if index < len(polygons) and hasattr(polygons[index], "tolist") else []
            blocks.append({"text": clean, "confidence": float(scores[index]) if index < len(scores) else 0.5, "polygon": polygon})
    return blocks
