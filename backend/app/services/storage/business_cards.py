import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import boto3

from app.core.config import settings


class StagedUploadMissing(Exception):
    pass


class BusinessCardStorage:
    def __init__(self) -> None:
        self.root = settings.private_storage_dir.resolve()
        self.staging = self.root / "staging"
        self.staging.mkdir(parents=True, exist_ok=True)
        self.provider = settings.storage_provider.lower()
        self.s3 = None
        if self.provider == "s3":
            if not settings.storage_bucket:
                raise RuntimeError("STORAGE_BUCKET is required when STORAGE_PROVIDER=s3")
            self.s3 = boto3.client(
                "s3", endpoint_url=settings.storage_endpoint or None,
                aws_access_key_id=settings.storage_access_key or None,
                aws_secret_access_key=settings.storage_secret_key or None,
            )
        elif self.provider != "local":
            raise RuntimeError("STORAGE_PROVIDER must be 'local' or 's3'")

    def stage(self, data: bytes, filename: str, mime_type: str, metadata: dict[str, str] | None = None) -> str:
        self.cleanup_expired_staging()
        token = str(uuid.uuid4())
        (self.staging / f"{token}.upload").write_bytes(data)
        safe_name = Path(filename or "business-card").name
        safe_name = "".join(char for char in safe_name if char.isprintable() and char not in '<>:"|?*')[:255] or "business-card"
        sidecar = {"filename": safe_name, "mime_type": mime_type, **(metadata or {})}
        (self.staging / f"{token}.json").write_text(json.dumps(sidecar), encoding="utf-8")
        return token

    def metadata(self, token: str) -> dict[str, str]:
        image_path = self.staging_path(token)
        metadata_path = image_path.with_suffix(".json")
        if not metadata_path.is_file():
            raise StagedUploadMissing
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def staging_path(self, token: str) -> Path:
        try:
            safe_token = str(uuid.UUID(token))
        except ValueError:
            raise StagedUploadMissing from None
        path = (self.staging / f"{safe_token}.upload").resolve()
        if path.parent != self.staging.resolve() or not path.is_file():
            raise StagedUploadMissing
        if datetime.now(timezone.utc).timestamp() - path.stat().st_mtime > 1800:
            path.unlink(missing_ok=True)
            raise StagedUploadMissing
        return path

    def attach(self, token: str, event_slug: str, lead_code: str, content_type: str) -> tuple[str, int]:
        staged = self.staging_path(token)
        safe_event = re.sub(r"[^A-Za-z0-9_-]", "", event_slug) or "event"
        safe_code = re.sub(r"[^A-Za-z0-9_-]", "", lead_code)
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(content_type, ".img")
        key = f"business-cards/{safe_event}/{datetime.now(timezone.utc):%Y-%m-%d}/{safe_code}/{uuid.uuid4().hex}{suffix}"
        size = staged.stat().st_size
        if self.provider == "s3":
            self.s3.upload_file(str(staged), settings.storage_bucket, key, ExtraArgs={"ContentType": content_type, "ServerSideEncryption": "AES256"})
            staged.unlink(missing_ok=True)
            staged.with_suffix(".json").unlink(missing_ok=True)
            return key, size
        destination = (self.root / key).resolve()
        if self.root not in destination.parents:
            raise ValueError("Invalid private storage path")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staged), str(destination))
        staged.with_suffix(".json").unlink(missing_ok=True)
        return str(destination.relative_to(self.root)), size

    def read(self, storage_path: str) -> bytes:
        if self.provider == "s3":
            result = self.s3.get_object(Bucket=settings.storage_bucket, Key=storage_path)
            return result["Body"].read()
        path = (self.root / storage_path).resolve()
        if self.root not in path.parents or not path.is_file():
            raise FileNotFoundError(storage_path)
        return path.read_bytes()

    def delete(self, storage_path: str) -> None:
        if self.provider == "s3":
            self.s3.delete_object(Bucket=settings.storage_bucket, Key=storage_path)
            return
        path = (self.root / storage_path).resolve()
        if self.root in path.parents:
            path.unlink(missing_ok=True)

    def delete_staged(self, token: str) -> None:
        try:
            path = self.staging_path(token)
        except StagedUploadMissing:
            return
        path.unlink(missing_ok=True)
        path.with_suffix(".json").unlink(missing_ok=True)

    def cleanup_expired_staging(self) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - 1800
        for item in self.staging.glob("*.upload"):
            try:
                if item.stat().st_mtime < cutoff:
                    item.unlink(missing_ok=True)
                    item.with_suffix(".json").unlink(missing_ok=True)
            except OSError:
                continue


storage = BusinessCardStorage()
