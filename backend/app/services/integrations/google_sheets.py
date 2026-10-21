import json

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Interaction, Lead, User

SHEETS_SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_HEADERS = ["Lead ID", "Date", "Time", "Full Name", "Company", "Job Title", "Email", "WhatsApp", "Website", "Interest", "Intent", "Requirement / Visitor Feedback", "Capture Method", "Source", "Captured By", "Assigned To", "Status", "Interaction ID", "Other Interest Details", "Other Discussion Details", "Address", "Data Processing Consent At", "Follow-up Consent At", "Consent Notice Version", "AI Processing Consent Recorded At", "AI Consent Notice Version"]


def _service():
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
    else:
        info = {
            "type": "service_account", "client_email": settings.google_service_account_email,
            "private_key": settings.google_private_key.replace("\\n", "\n"),
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    credentials = Credentials.from_service_account_info(info, scopes=SHEETS_SCOPE)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False).spreadsheets()


def sync_interaction(db: Session, interaction: Interaction) -> None:
    if not settings.google_sheet_id:
        return
    lead = db.get(Lead, interaction.lead_id)
    assignee = db.get(User, interaction.assigned_to) if interaction.assigned_to else None
    if lead is None:
        raise ValueError("Lead for Sheets sync no longer exists")
    service = _service()
    escaped_tab = settings.google_sheet_tab.replace("'", "''")
    header_range = f"'{escaped_tab}'!A1:Z1"
    header = service.values().get(spreadsheetId=settings.google_sheet_id, range=header_range).execute().get("values", [])
    if not header:
        service.values().update(
            spreadsheetId=settings.google_sheet_id, range=header_range,
            valueInputOption="RAW", body={"values": [SHEET_HEADERS]},
        ).execute()
        spreadsheet = service.get(spreadsheetId=settings.google_sheet_id, fields="sheets(properties(sheetId,title))").execute()
        sheet_id = next((item["properties"]["sheetId"] for item in spreadsheet.get("sheets", []) if item.get("properties", {}).get("title") == settings.google_sheet_tab), None)
        if sheet_id is None:
            raise ValueError(f"Configured Google Sheet tab '{settings.google_sheet_tab}' was not found")
        service.batchUpdate(spreadsheetId=settings.google_sheet_id, body={"requests": [{"updateDimensionProperties": {"range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 17, "endIndex": 18}, "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}}]}).execute()
    elif len(header[0]) < len(SHEET_HEADERS):
        existing_count = len(header[0])
        service.values().update(
            spreadsheetId=settings.google_sheet_id,
            range=f"'{escaped_tab}'!{chr(65 + existing_count)}1:Z1",
            valueInputOption="RAW", body={"values": [SHEET_HEADERS[existing_count:]]},
        ).execute()
    row = [
        lead.lead_code,
        interaction.created_at.strftime("%Y-%m-%d"), interaction.created_at.strftime("%H:%M:%S UTC"),
        lead.full_name, lead.company, lead.job_title, lead.email, lead.phone, lead.website or "",
        ", ".join(interaction.interest), interaction.intent, interaction.requirement_message or "",
        interaction.capture_method, interaction.source, interaction.captured_by or "",
        assignee.full_name if assignee else "", interaction.status, str(interaction.id),
        interaction.other_interest_details or "", interaction.other_intent_details or "", lead.address or "",
        interaction.data_processing_consent_at.isoformat() if interaction.data_processing_consent_at else "",
        interaction.follow_up_consent_at.isoformat() if interaction.follow_up_consent_at else "", interaction.consent_notice_version or "",
        interaction.ai_processing_consent_at.isoformat() if interaction.ai_processing_consent_at else "",
        interaction.ai_processing_consent_notice_version or "",
    ]
    id_column = service.values().get(spreadsheetId=settings.google_sheet_id, range=f"'{escaped_tab}'!R:R").execute().get("values", [])
    existing_row = next((index + 1 for index, values in enumerate(id_column) if values and values[0] == str(interaction.id)), None)
    if existing_row:
        service.values().update(spreadsheetId=settings.google_sheet_id, range=f"'{escaped_tab}'!A{existing_row}:Z{existing_row}", valueInputOption="RAW", body={"values": [row]}).execute()
    else:
        service.values().append(spreadsheetId=settings.google_sheet_id, range=f"'{escaped_tab}'!A:Z", valueInputOption="RAW", insertDataOption="INSERT_ROWS", body={"values": [row]}).execute()
