import hashlib
import io
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session
from openpyxl import load_workbook

from app.core.config import settings
from app.core.security import current_user, require_roles
from app.db.models import AuditLog, Event, EventRegistrant, ResearchImportBatch, ResearchImportRow, User, now_utc
from app.db.session import get_db
from app.services.storage.business_cards import storage

router = APIRouter(prefix="/admin", tags=["research imports"])
MANAGERS = ("ADMIN", "MANAGER")
MAX_IMPORT_ROWS = 50000
MAX_IMPORT_CELLS = 2_000_000
ALLOWED_EXTENSIONS = {".xlsx", ".xlsm"}
CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
}


def _clean_name(value: str | None) -> str:
    return Path(value or "research-workbook.xlsx").name[:255]


def _cell_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _header_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").casefold()).strip("_")


def _column(headers: list[str], aliases: tuple[str, ...], contains: tuple[str, ...] = ()) -> int | None:
    keys = [_header_key(header) for header in headers]
    for alias in aliases:
        key = _header_key(alias)
        if key in keys:
            return keys.index(key)
    if contains:
        for index, key in enumerate(keys):
            if all(token in key for token in contains):
                return index
    return None


def _value(values: list[Any], column_index: int | None) -> str | None:
    if column_index is None or column_index >= len(values) or values[column_index] is None:
        return None
    text = str(values[column_index]).strip()
    return text or None


def _parse_workbook(data: bytes) -> tuple[list[dict], list[str], list[dict]]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_vba=False)
    except Exception as exc:
        raise HTTPException(status_code=422, detail="The workbook could not be opened. Use a valid .xlsx or .xlsm file.") from exc
    parsed: list[dict] = []
    summary: list[dict] = []
    workbook_errors: list[dict] = []
    total_cells = 0
    try:
        for worksheet in workbook.worksheets:
            iterator = worksheet.iter_rows(values_only=True)
            first_row_number = 0
            headers_raw = None
            for row_number, row in enumerate(iterator, start=1):
                if any(value is not None and str(value).strip() for value in row):
                    first_row_number, headers_raw = row_number, row
                    break
            if headers_raw is None:
                summary.append({"sheet_name": worksheet.title, "columns": [], "rows": 0, "errors": 0})
                continue

            counts: dict[str, int] = {}
            headers: list[str] = []
            for index, value in enumerate(headers_raw):
                heading = str(value).strip() if value is not None else ""
                heading = heading or f"Column {index + 1}"
                counts[heading] = counts.get(heading, 0) + 1
                headers.append(heading if counts[heading] == 1 else f"{heading} #{counts[heading]}")
            profile_col = _column(headers, ("Profile ID", "ProfileID", "Registrant ID", "Attendee ID"))
            source_row_col = _column(headers, ("Source Row ID", "Row ID", "Record ID", "Source ID"))
            name_col = _column(headers, ("Full Name", "Name", "Attendee Name", "Registrant Name"))
            first_col = _column(headers, ("First Name", "Given Name"))
            last_col = _column(headers, ("Last Name", "Family Name", "Surname"))
            company_col = _column(headers, ("Company", "Organization", "Organisation", "Employer"))
            title_col = _column(headers, ("Job Title", "Title", "Designation", "Role"))
            email_col = _column(headers, ("Email", "Email Address", "Work Email"))
            phone_col = _column(headers, ("Phone", "Phone Number", "Mobile", "Mobile Number"))
            shortlist_col = _column(
                headers,
                ("Shortlist", "Shortlist Status", "Short List", "Latent Sig Fit", "Fit"),
                ("short", "list"),
            )
            cse_col = _column(headers, ("CSE Status", "CSE Progress", "Research Status"), ("cse",))
            sheet_rows = 0
            sheet_errors = 0
            for row_number, row in enumerate(iterator, start=first_row_number + 1):
                values = list(row)
                if not any(value is not None and str(value).strip() for value in values):
                    continue
                if len(parsed) >= MAX_IMPORT_ROWS:
                    raise HTTPException(status_code=413, detail=f"A workbook may contain at most {MAX_IMPORT_ROWS:,} non-empty data rows.")
                total_cells += len(headers)
                if total_cells > MAX_IMPORT_CELLS:
                    raise HTTPException(status_code=413, detail=f"A workbook may contain at most {MAX_IMPORT_CELLS:,} worksheet cells.")
                raw = {headers[index]: _cell_value(values[index] if index < len(values) else None) for index in range(len(headers))}
                full_name = _value(values, name_col)
                if not full_name:
                    first, last = _value(values, first_col), _value(values, last_col)
                    full_name = " ".join(part for part in (first, last) if part) or None
                profile_id = _value(values, profile_col)
                source_row_id = _value(values, source_row_col)
                shortlist = _value(values, shortlist_col)
                errors: list[str] = []
                if re.search(r"\bstrong\b", shortlist or "", re.I):
                    if not profile_id:
                        errors.append("Strong shortlist row is missing Profile ID.")
                    if not full_name:
                        errors.append("Strong shortlist row is missing a name.")
                    if not _value(values, company_col):
                        errors.append("Strong shortlist row is missing a company.")
                sheet_identity = f"sheet:{worksheet.title.casefold()}"
                source_identity = f"{sheet_identity}:source:{source_row_id.casefold()}" if source_row_id else f"{sheet_identity}:row:{row_number}"
                source_key = f"profile:{profile_id.casefold()}:{source_identity}" if profile_id else f"row:{source_identity}"
                derived = {
                    "full_name": full_name, "company": _value(values, company_col),
                    "job_title": _value(values, title_col), "email": _value(values, email_col),
                    "phone": _value(values, phone_col), "shortlist_status": shortlist,
                    "cse_status": _value(values, cse_col),
                }
                parsed.append({
                    "sheet_name": worksheet.title, "source_row": row_number,
                    "source_key": source_key[:500], "profile_id": profile_id,
                    "row_data": {"cells": raw, "derived": derived}, "validation_errors": errors,
                })
                sheet_rows += 1
                sheet_errors += len(errors)
                for message in errors:
                    workbook_errors.append({"sheet_name": worksheet.title, "source_row": row_number, "message": message})
            summary.append({"sheet_name": worksheet.title, "columns": headers, "rows": sheet_rows, "errors": sheet_errors})
    finally:
        workbook.close()
    return parsed, [worksheet.title for worksheet in workbook.worksheets], workbook_errors


def _registrant_snapshot(item: EventRegistrant) -> dict:
    return {
        "profile_id": item.profile_id, "source_key": item.source_key, "source_filename": item.source_filename,
        "sheet_name": item.sheet_name, "source_row": item.source_row, "full_name": item.full_name,
        "company": item.company, "job_title": item.job_title, "email": item.email, "phone": item.phone,
        "shortlist_status": item.shortlist_status, "cse_status": item.cse_status, "raw_data": item.raw_data,
        "match_status": item.match_status, "matched_lead_id": str(item.matched_lead_id) if item.matched_lead_id else None,
        "reconciliation_required": item.reconciliation_required, "reconciliation_errors": item.reconciliation_errors,
        "last_import_batch_id": str(item.last_import_batch_id) if item.last_import_batch_id else None,
    }


def _registrant_json(item: EventRegistrant) -> dict:
    return {
        "id": str(item.id), "profile_id": item.profile_id, "source_filename": item.source_filename,
        "sheet_name": item.sheet_name, "source_row": item.source_row, "full_name": item.full_name,
        "company": item.company, "job_title": item.job_title, "email": item.email, "phone": item.phone,
        "shortlist_status": item.shortlist_status, "cse_status": item.cse_status, "raw_data": item.raw_data,
        "match_status": item.match_status, "matched_lead_id": str(item.matched_lead_id) if item.matched_lead_id else None,
        "reconciliation_required": item.reconciliation_required, "reconciliation_errors": item.reconciliation_errors,
    }


@router.get("/events/{event_id}/research/imports")
def list_imports(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    batches = db.scalars(select(ResearchImportBatch).where(ResearchImportBatch.event_id == event_id).order_by(ResearchImportBatch.created_at.desc())).all()
    return [{
        "id": str(item.id), "original_filename": item.original_filename, "file_sha256": item.file_sha256,
        "status": item.status, "sheet_names": item.sheet_names, "row_count": item.row_count,
        "errors": item.errors, "created_at": item.created_at.isoformat(),
        "imported_at": item.imported_at.isoformat() if item.imported_at else None,
    } for item in batches]


@router.post("/events/{event_id}/research/imports", status_code=201)
async def preview_import(event_id: uuid.UUID, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    filename = _clean_name(file.filename)
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Upload an .xlsx or .xlsm workbook.")
    data = await file.read(settings.max_workbook_upload_bytes + 1)
    await file.close()
    if not data:
        raise HTTPException(status_code=400, detail="The workbook is empty.")
    if len(data) > settings.max_workbook_upload_bytes:
        max_megabytes = settings.max_workbook_upload_bytes // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Workbooks must be {max_megabytes} MB or smaller.")
    if not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=415, detail="The file contents are not a valid Excel workbook.")
    parsed, sheet_names, errors = _parse_workbook(data)
    if not sheet_names:
        raise HTTPException(status_code=422, detail="The workbook does not contain any worksheets.")
    storage_path, _ = storage.save_private(data, event.slug, "research-workbooks", suffix, CONTENT_TYPES[suffix])
    batch = ResearchImportBatch(
        event_id=event.id, uploaded_by=user.id, original_filename=filename,
        file_sha256=hashlib.sha256(data).hexdigest(), storage_path=storage_path,
        status="preview", sheet_names=sheet_names, row_count=len(parsed), errors=errors,
    )
    db.add(batch)
    db.flush()
    for row in parsed:
        db.add(ResearchImportRow(batch_id=batch.id, **row))
    db.add(AuditLog(user_id=user.id, action="research_workbook_previewed", entity_type="research_import", entity_id=str(batch.id), metadata_json={"filename": filename, "rows": len(parsed)}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(storage_path)
        raise
    sheet_summary: dict[str, dict] = {}
    for sheet_name in sheet_names:
        rows = [row for row in parsed if row["sheet_name"] == sheet_name]
        columns = list(rows[0]["row_data"]["cells"].keys()) if rows else []
        sheet_summary[sheet_name] = {"sheet_name": sheet_name, "columns": columns, "rows": len(rows), "errors": sum(len(row["validation_errors"]) for row in rows)}
    return {
        "id": str(batch.id), "original_filename": filename, "status": batch.status,
        "sheet_names": sheet_names, "row_count": len(parsed), "error_count": len(errors),
        "errors": errors, "sheets": list(sheet_summary.values()),
        "macros_executed": False,
    }


@router.post("/research/imports/{batch_id}/confirm")
def confirm_import(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    batch = db.get(ResearchImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import preview not found.")
    if batch.status == "imported":
        return {"id": str(batch.id), "status": batch.status, "row_count": batch.row_count, "idempotent": True}
    if batch.status != "preview":
        raise HTTPException(status_code=409, detail="Only a preview can be imported.")
    rows = db.scalars(select(ResearchImportRow).where(ResearchImportRow.batch_id == batch.id).order_by(ResearchImportRow.sheet_name, ResearchImportRow.source_row)).all()
    for staged in rows:
        existing = db.scalar(select(EventRegistrant).where(EventRegistrant.event_id == batch.event_id, EventRegistrant.source_key == staged.source_key))
        staged.previous_data = _registrant_snapshot(existing) if existing else None
        derived = staged.row_data.get("derived", {})
        raw_data = staged.row_data.get("cells", {})
        values = {
            "last_import_batch_id": batch.id, "profile_id": staged.profile_id, "source_filename": batch.original_filename,
            "sheet_name": staged.sheet_name, "source_row": staged.source_row,
            "full_name": derived.get("full_name"), "company": derived.get("company"), "job_title": derived.get("job_title"),
            "email": derived.get("email"), "phone": derived.get("phone"), "shortlist_status": derived.get("shortlist_status"),
            "cse_status": derived.get("cse_status"), "raw_data": raw_data,
            "reconciliation_required": bool(staged.validation_errors), "reconciliation_errors": staged.validation_errors,
        }
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
        else:
            db.add(EventRegistrant(event_id=batch.event_id, source_key=staged.source_key, **values))
    batch.status = "imported"
    batch.imported_at = now_utc()
    db.add(AuditLog(user_id=user.id, action="research_workbook_imported", entity_type="research_import", entity_id=str(batch.id), metadata_json={"rows": len(rows), "event_id": str(batch.event_id)}))
    db.commit()
    return {"id": str(batch.id), "status": batch.status, "row_count": len(rows), "error_count": len(batch.errors), "idempotent": False}


@router.post("/research/imports/{batch_id}/rollback")
def rollback_import(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(require_roles(*MANAGERS))):
    batch = db.get(ResearchImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")
    if batch.status == "rolled_back":
        return {"id": str(batch.id), "status": batch.status, "idempotent": True}
    if batch.status != "imported":
        raise HTTPException(status_code=409, detail="Only an imported workbook can be rolled back.")
    rows = db.scalars(select(ResearchImportRow).where(ResearchImportRow.batch_id == batch.id).order_by(ResearchImportRow.sheet_name.desc(), ResearchImportRow.source_row.desc())).all()
    for staged in rows:
        current = db.scalar(select(EventRegistrant).where(EventRegistrant.event_id == batch.event_id, EventRegistrant.source_key == staged.source_key))
        if current is None or current.last_import_batch_id != batch.id:
            continue
        previous = staged.previous_data
        if previous is None:
            db.delete(current)
            continue
        for key, value in previous.items():
            if key == "matched_lead_id" and value:
                value = uuid.UUID(value)
            elif key == "last_import_batch_id" and value:
                value = uuid.UUID(value)
            setattr(current, key, value)
    batch.status = "rolled_back"
    batch.rolled_back_at = now_utc()
    db.add(AuditLog(user_id=user.id, action="research_workbook_rolled_back", entity_type="research_import", entity_id=str(batch.id), metadata_json={"event_id": str(batch.event_id)}))
    db.commit()
    return {"id": str(batch.id), "status": batch.status, "idempotent": False}


@router.get("/research/imports/{batch_id}/source")
def download_import_source(batch_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    batch = db.get(ResearchImportBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import not found.")
    try:
        data = storage.read(batch.storage_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="The original workbook is unavailable.") from None
    suffix = Path(batch.original_filename).suffix.lower()
    return Response(data, media_type=CONTENT_TYPES.get(suffix, "application/octet-stream"), headers={
        "Content-Disposition": f'attachment; filename="{batch.original_filename.replace(chr(34), "")}"',
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    })


@router.get("/events/{event_id}/research/registrants")
def search_registrants(
    event_id: uuid.UUID, search: str | None = None, sheet: str | None = None,
    shortlist_status: str | None = None, cse_status: str | None = None,
    match_status: str | None = None, reconciliation_required: bool | None = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    query = select(EventRegistrant).where(EventRegistrant.event_id == event_id)
    if search:
        term = f"%{search.strip()}%"
        query = query.where(or_(
            EventRegistrant.profile_id.ilike(term), EventRegistrant.full_name.ilike(term),
            EventRegistrant.company.ilike(term), EventRegistrant.email.ilike(term),
            EventRegistrant.phone.ilike(term), cast(EventRegistrant.raw_data, String).ilike(term),
        ))
    if sheet:
        query = query.where(EventRegistrant.sheet_name == sheet)
    if shortlist_status:
        query = query.where(EventRegistrant.shortlist_status.ilike(f"%{shortlist_status.strip()}%"))
    if cse_status:
        query = query.where(EventRegistrant.cse_status.ilike(f"%{cse_status.strip()}%"))
    if match_status:
        query = query.where(EventRegistrant.match_status == match_status)
    if reconciliation_required is not None:
        query = query.where(EventRegistrant.reconciliation_required.is_(reconciliation_required))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(EventRegistrant.sheet_name, EventRegistrant.source_row).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_registrant_json(item) for item in rows], "total": total, "page": page, "page_size": page_size}
