import hashlib
import csv
import io
import json
import re
import uuid
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session
from openpyxl import load_workbook

from app.core.config import settings
from app.core.security import current_user, require_roles
from app.db.models import AuditLog, Event, EventRegistrant, ResearchImportBatch, ResearchImportRow, User, now_utc
from app.db.session import get_db
from app.services.research_matching import registrant_identity_key, registrant_identity_rows
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


def _source_row_fingerprint(cells: dict[str, Any]) -> str:
    normalized = [{"header": _header_key(key), "value": value} for key, value in (cells or {}).items()]
    normalized.sort(key=lambda item: (item["header"], json.dumps(item["value"], sort_keys=True, ensure_ascii=False, default=str)))
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _import_quality_summary(parsed_rows: list[dict], warning_count: int) -> dict[str, int]:
    profile_sheets: dict[str, set[str]] = defaultdict(set)
    registrant_profile_ids: set[str] = set()
    missing_profile_id_rows = 0
    for row in parsed_rows:
        profile_id = (row.get("profile_id") or "").strip().casefold()
        sheet_name = row["sheet_name"]
        if not profile_id:
            missing_profile_id_rows += 1
            continue
        profile_sheets[profile_id].add(sheet_name.casefold())
        if sheet_name.casefold() == "registrants":
            registrant_profile_ids.add(profile_id)
    return {
        "unique_profile_ids_in_registrants": len(registrant_profile_ids),
        "repeated_profile_ids_across_sheets": sum(1 for sheets in profile_sheets.values() if len(sheets) > 1),
        "missing_profile_id_rows": missing_profile_id_rows,
        "warning_count": warning_count,
    }


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
            strong_shortlist_sheet = "strong" in worksheet.title.casefold() and "shortlist" in worksheet.title.casefold()
            cse_col = _column(headers, ("CSE Status", "CSE Progress", "Research Status"), ("cse",))
            sheet_rows = 0
            sheet_errors = 0
            source_occurrences: dict[str, int] = {}
            sheet_token = hashlib.sha256(worksheet.title.casefold().encode("utf-8")).hexdigest()[:20]
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
                is_strong_row = bool(re.search(r"\bstrong\b", shortlist or "", re.I))
                if is_strong_row or (strong_shortlist_sheet and not profile_id):
                    if not profile_id:
                        errors.append("Strong shortlist row is missing Profile ID.")
                    if not full_name:
                        errors.append("Strong shortlist row is missing a name.")
                    if not _value(values, company_col):
                        errors.append("Strong shortlist row is missing a company.")
                source_fingerprint = _source_row_fingerprint(raw)
                if source_row_id:
                    source_base = f"sheet:{sheet_token}:source:{hashlib.sha256(source_row_id.casefold().encode('utf-8')).hexdigest()}"
                else:
                    source_base = f"sheet:{sheet_token}:content:{source_fingerprint}"
                occurrence = source_occurrences.get(source_base, 0)
                source_occurrences[source_base] = occurrence + 1
                source_identity = f"{source_base}:copy:{occurrence}"
                if profile_id:
                    profile_token = hashlib.sha256(profile_id.casefold().encode("utf-8")).hexdigest()[:32]
                    source_key = f"profile:{profile_token}:{source_identity}"
                else:
                    source_key = f"row:{source_identity}"
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


def _identity_expression():
    profile_id = func.lower(func.trim(EventRegistrant.profile_id))
    source_key = func.lower(func.trim(EventRegistrant.source_key))
    return case(
        (profile_id != "", literal("profile:") + profile_id),
        else_=literal("source:") + source_key,
    )


def _attendee_summary(rows: list[EventRegistrant], *, include_source_data: bool = False) -> dict:
    rows = sorted(
        rows,
        key=lambda row: (
            row.sheet_name.casefold() != "registrants",
            row.sheet_name.casefold(),
            row.source_row,
        ),
    )
    primary = rows[0]

    def cell(*aliases: str) -> str | None:
        source = primary.raw_data or {}
        by_key = {str(key).casefold(): value for key, value in source.items()}
        for alias in aliases:
            value = by_key.get(alias.casefold())
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    memberships = [
        {
            "id": str(row.id),
            "profile_id": row.profile_id,
            "full_name": row.full_name,
            "company": row.company,
            "job_title": row.job_title,
            "sheet_name": row.sheet_name,
            "source_row": row.source_row,
            "shortlist_status": row.shortlist_status,
            "cse_status": row.cse_status,
            "match_status": row.match_status,
            "reconciliation_required": row.reconciliation_required,
            "reconciliation_errors": row.reconciliation_errors or [],
            **({"raw_data": row.raw_data or {}} if include_source_data else {}),
        }
        for row in rows
    ]
    match_status = (
        "matched" if any(row.match_status == "matched" for row in rows)
        else "suggested" if any(row.match_status == "suggested" for row in rows)
        else "unmatched"
    )
    return {
        "id": str(primary.id),
        "identity_type": registrant_identity_key(primary)[0],
        "profile_id": primary.profile_id,
        "full_name": primary.full_name,
        "company": primary.company,
        "job_title": primary.job_title,
        "website": cell("Company Website (cleaned)", "Company Website", "Website"),
        "linkedin": cell("Person LinkedIn", "LinkedIn", "LinkedIn URL"),
        "location": ", ".join(filter(None, (cell("City"), cell("State"), cell("Country")))) or None,
        "sheets": list(dict.fromkeys(row.sheet_name for row in rows)),
        "membership_count": len(rows),
        "match_status": match_status,
        "reconciliation_required": any(row.reconciliation_required for row in rows),
        "reconciliation_errors": list(dict.fromkeys(
            error for row in rows for error in (row.reconciliation_errors or [])
        )),
        "memberships": memberships,
    }


@router.get("/events/{event_id}/research/imports")
def list_imports(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    batches = db.scalars(select(ResearchImportBatch).where(ResearchImportBatch.event_id == event_id).order_by(ResearchImportBatch.created_at.desc())).all()
    batch_ids = [item.id for item in batches]
    missing_counts: dict[uuid.UUID, int] = {}
    registrant_profile_counts: dict[uuid.UUID, int] = {}
    repeated_profile_counts: dict[uuid.UUID, int] = {}
    if batch_ids:
        missing_counts = dict(db.execute(
            select(ResearchImportRow.batch_id, func.count(ResearchImportRow.id))
            .where(
                ResearchImportRow.batch_id.in_(batch_ids),
                or_(ResearchImportRow.profile_id.is_(None), func.trim(ResearchImportRow.profile_id) == ""),
            ).group_by(ResearchImportRow.batch_id)
        ).all())
        registrant_profile_counts = dict(db.execute(
            select(ResearchImportRow.batch_id, func.count(func.distinct(func.lower(func.trim(ResearchImportRow.profile_id)))))
            .where(
                ResearchImportRow.batch_id.in_(batch_ids),
                func.lower(func.trim(ResearchImportRow.sheet_name)) == "registrants",
                ResearchImportRow.profile_id.is_not(None), func.trim(ResearchImportRow.profile_id) != "",
            ).group_by(ResearchImportRow.batch_id)
        ).all())
        repeated_profiles = select(
            ResearchImportRow.batch_id.label("batch_id"),
            func.lower(func.trim(ResearchImportRow.profile_id)).label("profile_key"),
        ).where(
            ResearchImportRow.batch_id.in_(batch_ids),
            ResearchImportRow.profile_id.is_not(None), func.trim(ResearchImportRow.profile_id) != "",
        ).group_by(
            ResearchImportRow.batch_id, func.lower(func.trim(ResearchImportRow.profile_id)),
        ).having(func.count(func.distinct(func.lower(func.trim(ResearchImportRow.sheet_name)))) > 1).subquery()
        repeated_profile_counts = dict(db.execute(
            select(repeated_profiles.c.batch_id, func.count(repeated_profiles.c.profile_key))
            .group_by(repeated_profiles.c.batch_id)
        ).all())
    return [{
        "id": str(item.id), "original_filename": item.original_filename, "file_sha256": item.file_sha256,
        "status": item.status, "sheet_names": item.sheet_names, "row_count": item.row_count,
        "errors": item.errors, "created_at": item.created_at.isoformat(),
        "imported_at": item.imported_at.isoformat() if item.imported_at else None,
        "rollback_available": item.status == "imported",
        "quality": {
            "unique_profile_ids_in_registrants": int(registrant_profile_counts.get(item.id, 0)),
            "repeated_profile_ids_across_sheets": int(repeated_profile_counts.get(item.id, 0)),
            "missing_profile_id_rows": int(missing_counts.get(item.id, 0)),
            "warning_count": len(item.errors or []),
        },
    } for item in batches]


@router.get("/events/{event_id}/research/sheets")
def list_research_sheets(event_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    batch = db.scalar(
        select(ResearchImportBatch)
        .where(ResearchImportBatch.event_id == event_id, ResearchImportBatch.status == "imported")
        .order_by(ResearchImportBatch.created_at.desc())
        .limit(1)
    )
    if batch is None:
        return {"batch_id": None, "original_filename": None, "row_count": 0, "sheets": []}

    row_counts = dict(db.execute(
        select(ResearchImportRow.sheet_name, func.count(ResearchImportRow.id))
        .where(ResearchImportRow.batch_id == batch.id)
        .group_by(ResearchImportRow.sheet_name)
    ).all())
    profile_counts = dict(db.execute(
        select(
            ResearchImportRow.sheet_name,
            func.count(func.distinct(func.lower(func.trim(ResearchImportRow.profile_id)))),
        )
        .where(ResearchImportRow.batch_id == batch.id)
        .group_by(ResearchImportRow.sheet_name)
    ).all())
    missing_id_counts = dict(db.execute(
        select(ResearchImportRow.sheet_name, func.count(ResearchImportRow.id))
        .where(
            ResearchImportRow.batch_id == batch.id,
            or_(
                ResearchImportRow.profile_id.is_(None),
                func.trim(ResearchImportRow.profile_id) == "",
            ),
        )
        .group_by(ResearchImportRow.sheet_name)
    ).all())
    flagged_counts = dict(db.execute(
        select(EventRegistrant.sheet_name, func.count(EventRegistrant.id))
        .where(
            EventRegistrant.event_id == event_id,
            EventRegistrant.last_import_batch_id == batch.id,
            EventRegistrant.reconciliation_required.is_(True),
        )
        .group_by(EventRegistrant.sheet_name)
    ).all())
    errors_by_sheet: dict[str, int] = {}
    for error in batch.errors or []:
        name = error.get("sheet_name")
        if name:
            errors_by_sheet[name] = errors_by_sheet.get(name, 0) + 1

    sheets = []
    for sheet_name in batch.sheet_names or []:
        first_row = db.scalar(
            select(ResearchImportRow.row_data)
            .where(
                ResearchImportRow.batch_id == batch.id,
                ResearchImportRow.sheet_name == sheet_name,
            )
            .order_by(ResearchImportRow.source_row)
            .limit(1)
        ) or {}
        cells = first_row.get("cells", {}) if isinstance(first_row, dict) else {}
        sheets.append({
            "sheet_name": sheet_name,
            "row_count": int(row_counts.get(sheet_name, 0)),
            "profile_id_count": int(profile_counts.get(sheet_name, 0)),
            "missing_profile_id_count": int(missing_id_counts.get(sheet_name, 0)),
            "reconciliation_rows": int(flagged_counts.get(sheet_name, 0)),
            "warning_count": errors_by_sheet.get(sheet_name, 0),
            "columns": list(cells.keys()),
        })
    return {
        "batch_id": str(batch.id),
        "original_filename": batch.original_filename,
        "row_count": sum(sheet["row_count"] for sheet in sheets),
        "unique_registrant_profile_ids": next(
            (sheet["profile_id_count"] for sheet in sheets if sheet["sheet_name"].casefold() == "registrants"),
            0,
        ),
        "sheets": sheets,
    }


def _spreadsheet_safe_cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


@router.get("/events/{event_id}/research/export")
def export_research_sheet(
    event_id: uuid.UUID,
    sheet: str = Query(..., min_length=1, max_length=255),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    batch = db.scalar(
        select(ResearchImportBatch)
        .where(ResearchImportBatch.event_id == event_id, ResearchImportBatch.status == "imported")
        .order_by(ResearchImportBatch.created_at.desc())
        .limit(1)
    )
    if batch is None or sheet not in (batch.sheet_names or []):
        raise HTTPException(status_code=404, detail="Research worksheet not found.")
    source_rows = db.scalars(
        select(ResearchImportRow)
        .where(ResearchImportRow.batch_id == batch.id, ResearchImportRow.sheet_name == sheet)
        .order_by(ResearchImportRow.source_row)
    ).all()
    headers: list[str] = []
    if source_rows:
        cells = source_rows[0].row_data.get("cells", {})
        headers = list(cells.keys()) if isinstance(cells, dict) else []
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\r\n")
    if headers:
        writer.writerow(headers)
        for row in source_rows:
            cells = row.row_data.get("cells", {})
            writer.writerow([_spreadsheet_safe_cell(cells.get(header)) for header in headers])
    filename = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{sheet}-research.csv").strip(".-") or "research.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


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
    file_sha256 = hashlib.sha256(data).hexdigest()
    batch = ResearchImportBatch(
        event_id=event.id, uploaded_by=user.id, original_filename=filename,
        file_sha256=file_sha256, storage_path=storage_path,
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
        "file_sha256": file_sha256, "sheet_names": sheet_names, "row_count": len(parsed), "error_count": len(errors),
        "errors": errors, "sheets": list(sheet_summary.values()),
        "quality": _import_quality_summary(parsed, len(errors)), "rollback_available": False,
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
    latest_batch = db.scalar(
        select(ResearchImportBatch)
        .where(ResearchImportBatch.event_id == batch.event_id, ResearchImportBatch.status == "imported")
        .order_by(ResearchImportBatch.imported_at.desc(), ResearchImportBatch.created_at.desc())
        .limit(1)
    )
    legacy_rows = db.scalars(select(EventRegistrant).where(
        EventRegistrant.event_id == batch.event_id,
        EventRegistrant.last_import_batch_id == latest_batch.id,
    )).all() if latest_batch else []
    legacy_by_profile_sheet: dict[tuple[str, str], list[EventRegistrant]] = defaultdict(list)
    legacy_by_content_sheet: dict[tuple[str, str], list[EventRegistrant]] = defaultdict(list)
    for item in legacy_rows:
        sheet_key = item.sheet_name.casefold()
        if item.profile_id:
            legacy_by_profile_sheet[(item.profile_id.strip().casefold(), sheet_key)].append(item)
        else:
            legacy_by_content_sheet[(sheet_key, _source_row_fingerprint(item.raw_data or {}))].append(item)
    incoming_profile_counts: dict[tuple[str, str], int] = defaultdict(int)
    incoming_content_counts: dict[tuple[str, str], int] = defaultdict(int)
    for staged in rows:
        sheet_key = staged.sheet_name.casefold()
        if staged.profile_id:
            incoming_profile_counts[(staged.profile_id.strip().casefold(), sheet_key)] += 1
        else:
            incoming_content_counts[(sheet_key, _source_row_fingerprint(staged.row_data.get("cells", {})))] += 1
    claimed_legacy_ids: set[uuid.UUID] = set()
    for staged in rows:
        existing = db.scalar(select(EventRegistrant).where(EventRegistrant.event_id == batch.event_id, EventRegistrant.source_key == staged.source_key))
        if existing is None and staged.profile_id:
            key = (staged.profile_id.strip().casefold(), staged.sheet_name.casefold())
            candidates = [item for item in legacy_by_profile_sheet.get(key, []) if item.id not in claimed_legacy_ids]
            if incoming_profile_counts[key] == 1 and len(candidates) == 1:
                existing = candidates[0]
        elif existing is None:
            key = (staged.sheet_name.casefold(), _source_row_fingerprint(staged.row_data.get("cells", {})))
            candidates = [item for item in legacy_by_content_sheet.get(key, []) if item.id not in claimed_legacy_ids]
            if incoming_content_counts[key] == 1 and len(candidates) == 1:
                existing = candidates[0]
        if existing is not None:
            claimed_legacy_ids.add(existing.id)
        staged.previous_data = _registrant_snapshot(existing) if existing else None
        derived = staged.row_data.get("derived", {})
        raw_data = staged.row_data.get("cells", {})
        values = {
            "source_key": staged.source_key, "last_import_batch_id": batch.id,
            "profile_id": staged.profile_id, "source_filename": batch.original_filename,
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
            db.add(EventRegistrant(event_id=batch.event_id, **values))
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
    priority: str | None = Query(None, pattern="^(A|B)$"),
    match_status: str | None = None, reconciliation_required: bool | None = None,
    sort_by: str | None = Query(None, max_length=255),
    sort_direction: str = Query("asc", pattern="^(asc|desc)$"),
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
    if priority:
        priority_values = [func.upper(func.trim(EventRegistrant.raw_data[key].as_string())) == priority.upper()
                           for key in ("Must-Meet", "Must Meet", "Priority")]
        query = query.where(or_(*priority_values))
    if cse_status:
        query = query.where(EventRegistrant.cse_status.ilike(f"%{cse_status.strip()}%"))
    if match_status:
        query = query.where(EventRegistrant.match_status == match_status)
    if reconciliation_required is not None:
        query = query.where(EventRegistrant.reconciliation_required.is_(reconciliation_required))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    if sort_by:
        sort_value = EventRegistrant.raw_data[sort_by].as_string()
        sort_order = sort_value.desc().nullslast() if sort_direction == "desc" else sort_value.asc().nullslast()
        order_by = (sort_order, EventRegistrant.sheet_name, EventRegistrant.source_row)
    else:
        order_by = (EventRegistrant.sheet_name, EventRegistrant.source_row)
    rows = db.scalars(query.order_by(*order_by).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [_registrant_json(item) for item in rows], "total": total, "page": page, "page_size": page_size}


@router.get("/events/{event_id}/research/attendees")
def search_research_attendees(
    event_id: uuid.UUID,
    search: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if db.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="Event not found.")
    conditions = [EventRegistrant.event_id == event_id]
    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        conditions.append(or_(
            EventRegistrant.profile_id.ilike(pattern),
            EventRegistrant.full_name.ilike(pattern),
            EventRegistrant.company.ilike(pattern),
            EventRegistrant.job_title.ilike(pattern),
            EventRegistrant.email.ilike(pattern),
            EventRegistrant.phone.ilike(pattern),
            cast(EventRegistrant.raw_data, String).ilike(pattern),
        ))

    identity = _identity_expression()
    summary = (
        select(
            identity.label("identity_key"),
            func.min(EventRegistrant.full_name).label("full_name"),
            func.min(EventRegistrant.company).label("company"),
        )
        .where(*conditions)
        .group_by(identity)
        .subquery()
    )
    total = db.scalar(select(func.count()).select_from(summary)) or 0
    identity_keys = db.scalars(
        select(summary.c.identity_key)
        .order_by(
            func.lower(func.coalesce(summary.c.full_name, "")),
            func.lower(func.coalesce(summary.c.company, "")),
            summary.c.identity_key,
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    if not identity_keys:
        return {"items": [], "total": total, "page": page, "page_size": page_size}

    rows = db.scalars(
        select(EventRegistrant)
        .where(EventRegistrant.event_id == event_id, _identity_expression().in_(identity_keys))
        .order_by(
            case((func.lower(EventRegistrant.sheet_name) == "registrants", 0), else_=1),
            EventRegistrant.sheet_name,
            EventRegistrant.source_row,
        )
    ).all()
    groups: dict[str, list[EventRegistrant]] = {}
    for row in rows:
        identity_type, identity_value = registrant_identity_key(row)
        groups.setdefault(f"{identity_type}:{identity_value}", []).append(row)
    return {
        "items": [_attendee_summary(groups[key]) for key in identity_keys if key in groups],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/events/{event_id}/research/attendees/{registrant_id}")
def get_research_attendee(
    event_id: uuid.UUID,
    registrant_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    registrant = db.get(EventRegistrant, registrant_id)
    if registrant is None or registrant.event_id != event_id:
        raise HTTPException(status_code=404, detail="Research attendee not found.")
    rows = registrant_identity_rows(db, event_id, registrant)
    return _attendee_summary(rows, include_source_data=True)
