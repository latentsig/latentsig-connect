from app.services.ocr.engine import get_engine


def main() -> None:
    print("Preparing local PaddleOCR models. First setup needs access to the Paddle model host.")
    get_engine()
    print("Local PaddleOCR models are ready and cached under backend/.cache/paddlex.")


if __name__ == "__main__":
    main()
