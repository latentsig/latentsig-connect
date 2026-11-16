import io
import csv
import hashlib
import os
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import uuid

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    BusinessCard, Event, EventEncounter, EventRegistrant, EventSession, IntegrationJob, Interaction, Lead,
    Meeting, ResearchImportBatch, ResearchImportRow, StaffCardCapture, User,
)
from app.db.session import get_db
from app.core.config import Settings, settings
from app.core import rate_limit as rate_limit_module
from app.core.passwords import hash_password
from app.main import app
from app.services.integrations import worker
from app.services.backup import create_backup
from app.services.vision.exceptions import VisionUnavailable
from app.services.vision.schemas import CardExtraction
from app.api.v1.routes import research as research_routes
from app.api.v1.routes import staff_capture as staff_capture_routes


class LeadApiTests(unittest.TestCase):
    def setUp(self):
        environment_patch = patch.dict(os.environ, {
            "DATABASE_URL": "sqlite:///./latentsig.db",
            "REDIS_URL": "",
        })
        self.addCleanup(environment_patch.stop)
        environment_patch.start()
        redis_patch = patch.object(settings, "redis_url", "")
        self.addCleanup(redis_patch.stop)
        redis_patch.start()
        # The in-memory limiter is process-wide; reset it between isolated API cases.
        rate_limit_module._hits.clear()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.TestSession = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        session_patch = patch("app.main.SessionLocal", self.TestSession)
        self.addCleanup(session_patch.stop)
        session_patch.start()

        with self.TestSession() as db:
            db.add_all([
                Event(name="Test Event", slug="test-event", location="Test City", is_active=True),
                User(email="bharat@latentsig.com", full_name="Admin User", role="ADMIN"),
                User(email="bhoomika@latentsig.com", full_name="Sales User", role="SALES"),
                User(email="raksha@latentsig.com", full_name="Read Only User", role="VIEWER"),
                User(email="other-sales@latentsig.com", full_name="Other Sales", role="SALES"),
            ])
            db.commit()

        def override_get_db():
            with self.TestSession() as db:
                yield db

        app.dependency_overrides[get_db] = override_get_db
        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        app.dependency_overrides.clear()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    @staticmethod
    def payload(**overrides):
        value = {
            "full_name": "Taylor Example",
            "company": "Example Company",
            "job_title": "Product Manager",
            "email": "taylor@example.com",
            "email_type": "work",
            "phone": "+14155552671",
            "website": "example.com",
            "address": "One Example Street, Bengaluru",
            "data_processing_consent": True,
            "follow_up_consent": True,
            "interest": ["AI Agents"],
            "intent": "I need a demo",
            "event_slug": "test-event",
            "source": "api-test",
        }
        value.update(overrides)
        return value

    def submit(self, **overrides):
        return self.client.post("/api/v1/leads", json=self.payload(**overrides))

    def sign_in(self, email):
        return self.client.post("/api/v1/auth/email-login", json={"email": email})

    def test_submission_creates_normalized_lead_interaction_and_audit(self):
        response = self.submit(email="Taylor@Example.com", website="example.com", utm_source="qr", utm_medium="booth", utm_campaign="test-event")
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(response.json()["created"])

        with self.TestSession() as db:
            lead = db.scalar(select(Lead).where(Lead.normalized_email == "taylor@example.com"))
            self.assertIsNotNone(lead)
            self.assertEqual(lead.website, "https://example.com")
            self.assertEqual(lead.address, "One Example Street, Bengaluru")
            interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead.id))
            self.assertIsNotNone(interaction.data_processing_consent_at)
            self.assertIsNotNone(interaction.follow_up_consent_at)
            self.assertEqual(interaction.consent_notice_version, settings.consent_notice_version)
            self.assertEqual(interaction.utm_source, "qr")
            self.assertEqual(interaction.utm_medium, "booth")
            self.assertEqual(interaction.utm_campaign, "test-event")
            self.assertEqual(db.scalar(select(func.count()).select_from(Interaction).where(Interaction.lead_id == lead.id)), 1)

    def test_duplicate_contact_adds_interaction_without_creating_lead(self):
        first = self.submit()
        second = self.submit(
            full_name="Taylor Updated", email="TAYLOR@example.com", phone="+14155552672",
            event_slug="test-event", source="second-visit",
        )
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(second.status_code, 201, second.text)
        self.assertTrue(first.json()["created"])
        self.assertFalse(second.json()["created"])
        self.assertEqual(first.json()["id"], second.json()["id"])

        with self.TestSession() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Lead)), 1)
            self.assertEqual(db.scalar(select(func.count()).select_from(Interaction)), 2)

    def test_simultaneous_event_submissions_keep_separate_visitors(self):
        database_url = os.environ.get("LATENTSIG_TEST_POSTGRES_URL")
        if not database_url:
            self.skipTest("Set LATENTSIG_TEST_POSTGRES_URL to a disposable local PostgreSQL database.")
        url = make_url(database_url)
        if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
            self.fail("Concurrency integration tests may only use a local PostgreSQL database.")

        schema = f"codex_concurrency_{uuid.uuid4().hex}"
        admin_engine = create_engine(database_url)
        engine = None
        prior_override = app.dependency_overrides.get(get_db)
        try:
            with admin_engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine = create_engine(database_url, connect_args={"options": f"-csearch_path={schema}"})
            Base.metadata.create_all(engine)
            ConcurrentSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

            def override_get_db():
                with ConcurrentSession() as db:
                    yield db

            app.dependency_overrides[get_db] = override_get_db
            with ConcurrentSession() as db:
                db.add(Event(name="Concurrent Test Event", slug="concurrent-test", is_active=True))
                db.commit()

            def submit(index):
                return self.client.post("/api/v1/leads", json=self.payload(
                    full_name=f"Concurrent Visitor {index}",
                    email=f"concurrent-{index}@example.com",
                    phone=f"+1415555268{index}",
                    event_slug="concurrent-test",
                ))

            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(submit, (1, 2)))

            self.assertEqual([response.status_code for response in responses], [201, 201])
            self.assertEqual(len({response.json()["id"] for response in responses}), 2)
            self.assertEqual(len({response.json()["lead_code"] for response in responses}), 2)
            with ConcurrentSession() as db:
                leads = db.scalars(select(Lead).where(Lead.normalized_email.in_(
                    ("concurrent-1@example.com", "concurrent-2@example.com"),
                ))).all()
                self.assertEqual(len(leads), 2)
                self.assertEqual(db.scalar(select(func.count()).select_from(Interaction).where(
                    Interaction.lead_id.in_([lead.id for lead in leads]),
                )), 2)
        finally:
            if prior_override is None:
                app.dependency_overrides.pop(get_db, None)
            else:
                app.dependency_overrides[get_db] = prior_override
            if engine is not None:
                engine.dispose()
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            admin_engine.dispose()

    def test_invalid_phone_and_interest_are_rejected(self):
        invalid_phone = self.submit(phone="not-a-phone")
        invalid_interest = self.submit(email="other@example.com", phone="+14155552672", interest=["Made up"])
        self.assertEqual(invalid_phone.status_code, 422)
        self.assertEqual(invalid_interest.status_code, 422)

        with self.TestSession() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Lead)), 0)

    def test_idempotency_key_returns_original_interaction_without_duplicate(self):
        key = str(uuid.uuid4())
        body = self.payload(email="idempotent@example.com", phone="+14155552672")
        first = self.client.post("/api/v1/leads", json=body, headers={"Idempotency-Key": key})
        retry = self.client.post("/api/v1/leads", json=body, headers={"Idempotency-Key": key})
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(retry.status_code, 201, retry.text)
        self.assertEqual(first.json(), retry.json())
        with self.TestSession() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Interaction)), 1)

    def test_idempotency_key_must_be_a_uuid(self):
        response = self.client.post("/api/v1/leads", json=self.payload(), headers={"Idempotency-Key": "invalid"})
        self.assertEqual(response.status_code, 400)

    def test_other_interest_requires_details_and_persists_them(self):
        missing_details = self.submit(
            email="other-required@example.com", phone="+14155552673",
            interest=["Other"], other_interest_details="   ",
        )
        self.assertEqual(missing_details.status_code, 422)

        message = "RAG agent workflows"
        accepted = self.submit(
            email="other-details@example.com", phone="+14155552674",
            interest=["AI Agents", "Other"], other_interest_details=message,
            requirement_message="How the form felt and what could be improved.",
        )
        self.assertEqual(accepted.status_code, 201, accepted.text)
        with self.TestSession() as db:
            interaction = db.scalar(select(Interaction).where(Interaction.id == uuid.UUID(accepted.json()["interaction_id"])))
            self.assertEqual(interaction.interest, ["AI Agents", "Other"])
            self.assertEqual(interaction.other_interest_details, message)
            self.assertEqual(interaction.requirement_message, "How the form felt and what could be improved.")

        missing_discussion = self.submit(
            email="other-discussion-required@example.com", phone="+14155552675",
            intent="Other", requirement_message=" ",
        )
        too_many_words = self.submit(
            email="other-too-many@example.com", phone="+14155552676",
            interest=["Other"], other_interest_details="one two three four five six",
        )
        accepted_discussion = self.submit(
            email="other-discussion@example.com", phone="+14155552677",
            intent="Other", other_intent_details="RAG agent for support",
        )
        self.assertEqual(missing_discussion.status_code, 422)
        self.assertEqual(too_many_words.status_code, 422)
        self.assertEqual(accepted_discussion.status_code, 201, accepted_discussion.text)

    def test_business_card_submission_requires_tokens_and_manual_flow_rejects_them(self):
        missing_front = self.submit(capture_method="business_card")
        manual_with_card = self.submit(email="other@example.com", phone="+14155552672", business_card_token="not-a-token")
        self.assertEqual(missing_front.status_code, 422)
        self.assertEqual(manual_with_card.status_code, 422)

    def test_lead_submission_requires_explicit_consent(self):
        response = self.client.post("/api/v1/leads", json=self.payload(data_processing_consent=False))
        self.assertEqual(response.status_code, 422)

    def test_follow_up_consent_is_optional_and_recorded_separately(self):
        response = self.submit(email="no-follow-up@example.com", phone="+14155552678", follow_up_consent=False)
        self.assertEqual(response.status_code, 201, response.text)
        with self.TestSession() as db:
            interaction = db.scalar(select(Interaction).where(Interaction.id == uuid.UUID(response.json()["interaction_id"])))
            self.assertIsNotNone(interaction.data_processing_consent_at)
            self.assertIsNone(interaction.follow_up_consent_at)

    def test_public_submissions_require_explicit_event_and_preserve_each_event_encounter(self):
        with self.TestSession() as db:
            bts = Event(name="Bengaluru Tech Summit 2026", slug="bts-2026", is_active=True)
            other = Event(name="Other Event", slug="other-event", is_active=True)
            db.add_all([bts, other])
            db.flush()
            session = EventSession(event_id=other.id, name="Morning", slug="morning")
            db.add(session)
            db.commit()
            other_id, session_id = other.id, session.id

        direct_payload = self.payload(email="multi-event@example.com", phone="+14155552681")
        direct_payload.pop("event_slug")
        direct = self.client.post("/api/v1/leads", json=direct_payload)
        self.assertEqual(direct.status_code, 201, direct.text)
        first_event = self.submit(email="multi-event@example.com", phone="+14155552681", event_slug="test-event")
        second_event = self.submit(
            email="multi-event@example.com", phone="+14155552681",
            event_slug="other-event", session_slug="morning",
        )
        self.assertEqual(first_event.status_code, 201, first_event.text)
        self.assertEqual(second_event.status_code, 201, second_event.text)
        self.assertEqual(direct.json()["id"], first_event.json()["id"])
        self.assertEqual(first_event.json()["id"], second_event.json()["id"])

        with self.TestSession() as db:
            interactions = db.scalars(select(Interaction).where(Interaction.lead_id == uuid.UUID(direct.json()["id"]))).all()
            self.assertEqual(len(interactions), 3)
            self.assertEqual(sum(item.event_id is None for item in interactions), 1)
            encounter = next(item for item in interactions if item.event_id == other_id)
            self.assertEqual(encounter.session_id, session_id)

        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        for slug in ("test-event", "other-event"):
            response = self.client.get("/api/v1/admin/leads", params={"event": slug})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["total"], 1)

    def test_workbook_import_keeps_sheet_rows_is_idempotent_and_rolls_back(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        from openpyxl import Workbook

        source = Workbook()
        strong = source.active
        strong.title = "Strong Shortlist"
        strong.append(["Profile ID", "Source Row ID", "Full Name", "Company", "Shortlist Status", "Custom Field"])
        strong.append(["P-001", "R-001", "Jordan Sample", "Example Labs", "Strong", "alpha"])
        strong.append([None, "R-002", "No Profile", "Example Labs", "Strong", "beta"])
        strong.append(["P-003", "R-003", None, "Example Labs", "Strong", "gamma"])
        strong.append(["P-004", "R-004", "No Company", None, "Strong", "delta"])
        strong.append([None, "R-005", "No Profile Two", "Example Labs", "Strong", "epsilon"])
        strong.append(["P-006", "R-006", None, "Example Labs", "Strong", "zeta"])
        cse = source.create_sheet("CSE Research")
        cse.append(["Profile ID", "Source Row ID", "Full Name", "Company", "CSE Status", "Custom Field"])
        cse.append(["P-001", "R-001", "Jordan Sample", "Example Labs", "In Progress", "cse-row"])
        payload = io.BytesIO()
        source.save(payload)
        source.close()
        file_bytes = payload.getvalue()
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)

        with patch.object(research_routes.storage, "save_private", return_value=("test-workbook.xlsx", len(file_bytes))):
            first_preview = self.client.post(
                f"/api/v1/admin/events/{event_id}/research/imports",
                files={"file": ("BTS shortlist.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            self.assertEqual(first_preview.status_code, 201, first_preview.text)
            self.assertEqual(first_preview.json()["row_count"], 7)
            self.assertEqual(first_preview.json()["error_count"], 5)
            self.assertEqual(first_preview.json()["sheet_names"], ["Strong Shortlist", "CSE Research"])
            self.assertEqual(first_preview.json()["file_sha256"], hashlib.sha256(file_bytes).hexdigest())
            self.assertEqual(first_preview.json()["quality"], {
                "unique_profile_ids_in_registrants": 0,
                "repeated_profile_ids_across_sheets": 1,
                "missing_profile_id_rows": 2,
                "warning_count": 5,
            })
            self.assertFalse(first_preview.json()["rollback_available"])
            first_id = first_preview.json()["id"]
            imported = self.client.post(f"/api/v1/admin/research/imports/{first_id}/confirm")
            self.assertEqual(imported.status_code, 200, imported.text)
            retry = self.client.post(f"/api/v1/admin/research/imports/{first_id}/confirm")
            self.assertTrue(retry.json()["idempotent"])

            second_preview = self.client.post(
                f"/api/v1/admin/events/{event_id}/research/imports",
                files={"file": ("BTS shortlist.xlsx", file_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            self.assertEqual(second_preview.status_code, 201, second_preview.text)
            second_id = second_preview.json()["id"]
            second_import = self.client.post(f"/api/v1/admin/research/imports/{second_id}/confirm")
            self.assertEqual(second_import.status_code, 200, second_import.text)
            history = self.client.get(f"/api/v1/admin/events/{event_id}/research/imports")
            self.assertEqual(history.status_code, 200, history.text)
            second_history_item = next(item for item in history.json() if item["id"] == second_id)
            self.assertTrue(second_history_item["rollback_available"])
            self.assertEqual(second_history_item["file_sha256"], hashlib.sha256(file_bytes).hexdigest())
            self.assertEqual(second_history_item["quality"]["repeated_profile_ids_across_sheets"], 1)
            self.assertEqual(second_history_item["quality"]["missing_profile_id_rows"], 2)
            rows = self.client.get(f"/api/v1/admin/events/{event_id}/research/registrants", params={"search": "cse-row"})
            self.assertEqual(rows.status_code, 200, rows.text)
            self.assertEqual(rows.json()["total"], 1)
            self.assertEqual(rows.json()["items"][0]["raw_data"]["Custom Field"], "cse-row")
            self.assertEqual(rows.json()["items"][0]["sheet_name"], "CSE Research")
            self.assertEqual(self.client.post(f"/api/v1/admin/research/imports/{second_id}/rollback").status_code, 200)
            self.assertEqual(self.client.post(f"/api/v1/admin/research/imports/{first_id}/rollback").status_code, 200)

        with self.TestSession() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(EventRegistrant)), 0)

    def test_reordered_workbook_keeps_stable_rows_and_manual_encounters(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        from openpyxl import Workbook

        def make_workbook(rows):
            source = Workbook()
            sheet = source.active
            sheet.title = "Registrants"
            sheet.append(["Profile ID", "Name", "Company", "Research Note"])
            for row in rows:
                sheet.append(row)
            payload = io.BytesIO()
            source.save(payload)
            source.close()
            return payload.getvalue()

        first_bytes = make_workbook([
            ["P-001", "Jordan Sample", "Alpha Systems", "Discuss vision workflow"],
            ["P-002", "Casey Sample", "Beta Systems", "Review integration plan"],
            [None, "Unidentified Visitor", "Unknown Systems", "Needs identity review"],
            [None, "Unidentified Visitor", "Unknown Systems", "Needs identity review"],
        ])
        reordered_bytes = make_workbook([
            ["P-002", "Casey Sample", "Beta Systems", "Review integration plan"],
            [None, "Unidentified Visitor", "Unknown Systems", "Needs identity review"],
            ["P-001", "Jordan Sample", "Updated Alpha Systems", "Discuss vision workflow"],
            [None, "Unidentified Visitor", "Unknown Systems", "Needs identity review"],
        ])
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)

        with patch.object(research_routes.storage, "save_private", return_value=("reordered-workbook.xlsx", len(first_bytes))):
            first_preview = self.client.post(
                f"/api/v1/admin/events/{event_id}/research/imports",
                files={"file": ("research.xlsx", first_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            self.assertEqual(first_preview.status_code, 201, first_preview.text)
            self.assertEqual(first_preview.json()["quality"], {
                "unique_profile_ids_in_registrants": 2,
                "repeated_profile_ids_across_sheets": 0,
                "missing_profile_id_rows": 2,
                "warning_count": 0,
            })
            first_import = self.client.post(f"/api/v1/admin/research/imports/{first_preview.json()['id']}/confirm")
            self.assertEqual(first_import.status_code, 200, first_import.text)

            with self.TestSession() as db:
                registrants = db.scalars(select(EventRegistrant).where(EventRegistrant.event_id == uuid.UUID(event_id))).all()
                by_profile = {row.profile_id: row for row in registrants if row.profile_id}
                first_ids = {profile_id: row.id for profile_id, row in by_profile.items()}
                anonymous_ids = {row.id for row in registrants if not row.profile_id}
                self.assertEqual(len(anonymous_ids), 2)
                jordan = by_profile["P-001"]
                # Simulate a row written by the legacy row-number key scheme.
                jordan.source_key = "profile:p-001:sheet:registrants:row:2"
                encounter = EventEncounter(
                    event_id=uuid.UUID(event_id), registrant_id=jordan.id,
                    identity_key="profile:p-001", encounter_type="meeting", status="confirmed",
                    notes="Staff-entered notes must survive reimport and rollback.",
                )
                db.add(encounter)
                db.commit()
                encounter_id = encounter.id

            second_preview = self.client.post(
                f"/api/v1/admin/events/{event_id}/research/imports",
                files={"file": ("research.xlsx", reordered_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            self.assertEqual(second_preview.status_code, 201, second_preview.text)
            second_import = self.client.post(f"/api/v1/admin/research/imports/{second_preview.json()['id']}/confirm")
            self.assertEqual(second_import.status_code, 200, second_import.text)

            with self.TestSession() as db:
                latest = db.scalar(select(ResearchImportBatch).where(ResearchImportBatch.id == uuid.UUID(second_preview.json()["id"])))
                latest_rows = db.scalars(select(EventRegistrant).where(
                    EventRegistrant.event_id == uuid.UUID(event_id),
                    EventRegistrant.last_import_batch_id == latest.id,
                )).all()
                by_profile = {row.profile_id: row for row in latest_rows if row.profile_id}
                self.assertEqual({key: row.id for key, row in by_profile.items()}, first_ids)
                self.assertEqual(by_profile["P-001"].source_row, 4)
                self.assertEqual(by_profile["P-001"].company, "Updated Alpha Systems")
                self.assertEqual({row.id for row in latest_rows if not row.profile_id}, anonymous_ids)
                self.assertEqual(len(latest_rows), 4)
                saved_encounter = db.get(EventEncounter, encounter_id)
                self.assertEqual(saved_encounter.registrant_id, by_profile["P-001"].id)
                self.assertEqual(saved_encounter.notes, "Staff-entered notes must survive reimport and rollback.")

            rolled_back = self.client.post(f"/api/v1/admin/research/imports/{second_preview.json()['id']}/rollback")
            self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
            with self.TestSession() as db:
                restored = db.scalar(select(EventRegistrant).where(
                    EventRegistrant.event_id == uuid.UUID(event_id), EventRegistrant.profile_id == "P-001",
                ))
                saved_encounter = db.get(EventEncounter, encounter_id)
                self.assertEqual(restored.id, first_ids["P-001"])
                self.assertEqual(restored.source_key, "profile:p-001:sheet:registrants:row:2")
                self.assertEqual(restored.source_row, 2)
                self.assertEqual(restored.company, "Alpha Systems")
                self.assertEqual(saved_encounter.registrant_id, restored.id)
                self.assertEqual(saved_encounter.notes, "Staff-entered notes must survive reimport and rollback.")

    def test_workbook_flags_incomplete_latent_sig_fit_rows(self):
        from openpyxl import Workbook

        source = Workbook()
        sheet = source.active
        sheet.title = "Strong shortlist"
        sheet.append(["Profile ID", "Name", "Designation", "Company", "Latent Sig Fit"])
        sheet.append(["BTS_2026_000001", "Jordan Sample", "Director", "Example Labs", "Strong"])
        sheet.append(["BTS_2026_000002", "Casey Sample", "Founder", None, "Strong"])
        sheet.append([None, "Riley Sample", "Director", "Example Labs", None])
        payload = io.BytesIO()
        source.save(payload)
        source.close()

        parsed, sheet_names, errors = research_routes._parse_workbook(payload.getvalue())

        self.assertEqual(sheet_names, ["Strong shortlist"])
        self.assertEqual(parsed[0]["row_data"]["derived"]["shortlist_status"], "Strong")
        self.assertEqual(parsed[0]["validation_errors"], [])
        self.assertEqual(parsed[1]["validation_errors"], ["Strong shortlist row is missing a company."])
        self.assertEqual(parsed[2]["validation_errors"], ["Strong shortlist row is missing Profile ID."])
        self.assertEqual(errors, [{
            "sheet_name": "Strong shortlist", "source_row": 3,
            "message": "Strong shortlist row is missing a company.",
        }, {
            "sheet_name": "Strong shortlist", "source_row": 4,
            "message": "Strong shortlist row is missing Profile ID.",
        }])

    def test_event_profiles_copy_session_dates_venue_and_staff_assignments(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        profile = self.client.post("/api/v1/admin/event-profiles", json={
            "name": "Summit Reuse Profile", "location": "Bengaluru", "venue": "BIEC",
            "sessions_template": [{
                "name": "Expo Hall", "venue": "Hall 2",
                "starts_at": "2026-11-17T10:00:00+05:30", "ends_at": "2026-11-17T12:00:00+05:30",
            }],
        })
        self.assertEqual(profile.status_code, 201, profile.text)
        created = self.client.post("/api/v1/admin/events/from-profile", json={
            "profile_id": profile.json()["id"], "name": "Summit Test Workspace", "slug": "summit-test-workspace",
            "start_date": "2026-11-17", "end_date": "2026-11-19",
        })
        self.assertEqual(created.status_code, 201, created.text)
        event_id = created.json()["id"]
        sessions = self.client.get(f"/api/v1/admin/events/{event_id}/sessions")
        self.assertEqual(sessions.status_code, 200, sessions.text)
        self.assertEqual(len(sessions.json()), 1)
        self.assertEqual(sessions.json()[0]["name"], "Expo Hall")
        self.assertEqual(sessions.json()[0]["venue"], "Hall 2")
        self.assertTrue(sessions.json()[0]["starts_at"].startswith("2026-11-17T10:00:00"))
        self.assertTrue(sessions.json()[0]["ends_at"].startswith("2026-11-17T12:00:00"))
        with self.TestSession() as db:
            sales_id = str(db.scalar(select(User.id).where(User.email == "bhoomika@latentsig.com")))
        assigned = self.client.put(f"/api/v1/admin/events/{event_id}/staff", json={"user_ids": [sales_id]})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        staff = self.client.get(f"/api/v1/admin/events/{event_id}/staff")
        self.assertEqual([item["user_id"] for item in staff.json()], [sales_id])
        invalid_session = self.client.post(f"/api/v1/admin/events/{event_id}/sessions", json={
            "name": "Invalid", "slug": "invalid", "starts_at": "2026-11-17T12:00:00+05:30", "ends_at": "2026-11-17T10:00:00+05:30",
        })
        self.assertEqual(invalid_session.status_code, 422)

    def test_lead_meeting_workflow_records_time_owner_status_and_follow_up(self):
        submission = self.submit(email="meeting@example.com", phone="+14155552670")
        self.assertEqual(submission.status_code, 201, submission.text)
        lead_id, interaction_id = submission.json()["id"], submission.json()["interaction_id"]
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            sales_id = str(db.scalar(select(User.id).where(User.email == "bhoomika@latentsig.com")))
        meeting = self.client.post(f"/api/v1/admin/leads/{lead_id}/meetings", json={
            "interaction_id": interaction_id, "scheduled_at": "2026-11-18T04:30:00+00:00", "employee_id": sales_id,
            "topics": ["Agentic AI"], "notes": "Meeting notes", "demo_presented": True,
            "status": "requested", "next_steps": "Share the demo", "follow_up_due_at": "2026-11-20T04:30:00+00:00",
        })
        self.assertEqual(meeting.status_code, 201, meeting.text)
        self.assertEqual(meeting.json()["status"], "requested")
        self.assertEqual(meeting.json()["employee_id"], sales_id)
        self.assertEqual(meeting.json()["employee_name"], "Sales User")
        self.assertTrue(meeting.json()["scheduled_at"].startswith("2026-11-18T04:30:00"))
        self.assertEqual(meeting.json()["topics"], ["Agentic AI"])
        self.assertTrue(meeting.json()["demo_presented"])
        self.assertEqual(meeting.json()["next_steps"], "Share the demo")
        updated = self.client.patch(f"/api/v1/admin/meetings/{meeting.json()['id']}", json={"status": "confirmed"})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "confirmed")
        with self.TestSession() as db:
            stored = db.get(Meeting, uuid.UUID(meeting.json()["id"]))
            interaction = db.get(Interaction, uuid.UUID(interaction_id))
            self.assertIsNotNone(stored.follow_up_due_at)
            self.assertEqual(interaction.status, "meeting")
            db.get(User, uuid.UUID(sales_id)).is_active = False
            db.commit()
        inactive_owner = self.client.patch(f"/api/v1/admin/meetings/{meeting.json()['id']}", json={"employee_id": sales_id})
        self.assertEqual(inactive_owner.status_code, 422)

    def test_card_capture_holds_ambiguous_matches_and_links_contactless_registrants(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
            duplicate_leads = [
                Lead(lead_code="DUPLICATE-001", full_name="Alex Example", company="Example Systems"),
                Lead(lead_code="DUPLICATE-002", full_name="Alex Example", company="Example Systems"),
            ]
            db.add_all(duplicate_leads)
            db.flush()
            db.add_all([
                Interaction(lead_id=lead.id, event_id=event.id, interest=[], intent="Unspecified", capture_method="manual", source="event-test")
                for lead in duplicate_leads
            ])
            db.add_all([
                EventRegistrant(event_id=event.id, profile_id="CONTACTLESS-001", source_key="profile:contactless-001:sheet:registrants:row:2", source_filename="research.xlsx", sheet_name="Registrants", source_row=2, full_name="Jordan Research", company="Research Systems", raw_data={}),
            ])
            db.commit()
            candidate_lead_id = str(db.scalar(select(Lead.id).where(Lead.lead_code == "DUPLICATE-001")))
        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        extractions = [
            CardExtraction(full_name="Alex Example", company="Example Systems"),
            CardExtraction(full_name="Jordan Research", company="Research Systems"),
        ]
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", side_effect=extractions), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("test-match-card.jpg", len(image_bytes))):
            ambiguous = self.client.post(
                "/api/v1/admin/card-captures", data={"event_id": event_id},
                files={"file": ("ambiguous.jpg", image_bytes, "image/jpeg")},
            )
            contactless = self.client.post(
                "/api/v1/admin/card-captures", data={"event_id": event_id},
                files={"file": ("contactless.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(ambiguous.status_code, 201, ambiguous.text)
        self.assertEqual(ambiguous.json()["status"], "pending_match")
        self.assertEqual(len(ambiguous.json()["candidates"]), 2)
        self.assertIsNone(ambiguous.json()["lead_id"])
        resolved = self.client.post(
            f"/api/v1/admin/card-captures/{ambiguous.json()['id']}/resolve",
            json={"lead_id": candidate_lead_id},
        )
        self.assertEqual(resolved.status_code, 200, resolved.text)
        self.assertEqual(resolved.json()["status"], "linked")
        self.assertEqual(resolved.json()["lead_id"], candidate_lead_id)
        self.assertEqual(contactless.status_code, 201, contactless.text)
        self.assertEqual(contactless.json()["status"], "linked")
        with self.TestSession() as db:
            registrant = db.scalar(select(EventRegistrant).where(EventRegistrant.profile_id == "CONTACTLESS-001"))
            linked = db.get(Lead, uuid.UUID(contactless.json()["lead_id"]))
            self.assertEqual(registrant.match_status, "matched")
            self.assertEqual(registrant.matched_lead_id, linked.id)
            self.assertEqual(linked.full_name, "Jordan Research")
            self.assertEqual(linked.company, "Research Systems")
            self.assertIsNone(linked.email)
            self.assertIsNone(linked.phone)

    def test_duplicate_workbook_rows_share_one_match_identity_and_dashboard_count(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = event.id
            db.add_all([
                EventRegistrant(
                    event_id=event_id, profile_id="PROFILE-REPEATED-001",
                    source_key="profile:profile-repeated-001:sheet:registrants:row:2",
                    source_filename="research.xlsx", sheet_name="Registrants", source_row=2,
                    full_name="Casey Research", company="Research Systems", raw_data={},
                ),
                EventRegistrant(
                    event_id=event_id, profile_id="PROFILE-REPEATED-001",
                    source_key="profile:profile-repeated-001:sheet:strong-shortlist:row:7",
                    source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=7,
                    full_name="Casey Research", company="Research Systems", raw_data={"Latent Sig Fit": "Strong"},
                    shortlist_status="Strong",
                ),
            ])
            db.commit()

        submission = self.submit(
            full_name="Casey Research", company="Research Systems", email="casey-research@example.com",
            phone="+14155552677", event_slug="test-event",
        )
        self.assertEqual(submission.status_code, 201, submission.text)
        with self.TestSession() as db:
            rows = db.scalars(select(EventRegistrant).where(EventRegistrant.profile_id == "PROFILE-REPEATED-001")).all()
            self.assertEqual(len(rows), 2)
            self.assertEqual({row.match_status for row in rows}, {"matched"})
            self.assertEqual({row.matched_lead_id for row in rows}, {uuid.UUID(submission.json()["id"])})
            capture_event_id = str(event_id)

        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        extraction = CardExtraction(full_name="Casey Research", company="Research Systems", job_title="Researcher")
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=extraction), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("repeated-profile-card.jpg", len(image_bytes))):
            capture = self.client.post(
                "/api/v1/admin/card-captures", data={"event_id": capture_event_id},
                files={"file": ("casey-card.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(capture.status_code, 201, capture.text)
        self.assertEqual(capture.json()["status"], "linked")
        self.assertEqual(capture.json()["lead_id"], submission.json()["id"])
        self.assertEqual(len(capture.json()["candidates"]), 1)
        self.assertEqual(capture.json()["candidates"][0]["kind"], "lead")
        dashboard = self.client.get(f"/api/v1/admin/events/{capture_event_id}/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["research"]["unique_registrants"], 1)
        self.assertEqual(dashboard.json()["research"]["matched_registrants"], 1)
        self.assertEqual(dashboard.json()["research"]["unmatched_registrants"], 0)
        self.assertEqual(dashboard.json()["research"]["shortlist_progress"]["total_rows"], 2)
        self.assertEqual(dashboard.json()["activity"]["unique_submitted_contacts"], 1)
        self.assertEqual(dashboard.json()["activity"]["staff_confirmed_encounters"], 1)

    def test_research_sheets_and_global_search_group_only_stable_profile_ids(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            user = db.scalar(select(User).where(User.email == "bharat@latentsig.com"))
            event_id = event.id
            batch = ResearchImportBatch(
                event_id=event.id,
                uploaded_by=user.id,
                original_filename="bts-fixture.xlsx",
                file_sha256="a" * 64,
                storage_path="bts-fixture.xlsx",
                status="imported",
                sheet_names=["Registrants", "Strong shortlist", "CSE Research"],
                row_count=4,
                errors=[],
            )
            db.add(batch)
            db.flush()
            source_rows = [
                ("PROFILE-GLOBAL-001", "Registrants", 2, "Jordan Example", "Research Systems", {}),
                ("PROFILE-GLOBAL-001", "Strong shortlist", 7, "Jordan Example", "Research Systems", {"Must-Meet": "A"}),
                ("PROFILE-GLOBAL-001", "CSE Research", 10, "Jordan Example", "Research Systems", {"Research Evidence": "CSE evidence phrase", "Untrusted cell": "=1+1"}),
                ("PROFILE-GLOBAL-002", "Registrants", 3, "Jordan Example", "Research Systems", {}),
            ]
            for profile_id, sheet_name, source_row, full_name, company, extra_cells in source_rows:
                cells = {"Profile ID": profile_id, "Name": full_name, "Company": company, **extra_cells}
                source_key = f"profile:{profile_id.casefold()}:sheet:{sheet_name.casefold()}:row:{source_row}"
                db.add(ResearchImportRow(
                    batch_id=batch.id,
                    sheet_name=sheet_name,
                    source_row=source_row,
                    source_key=source_key,
                    profile_id=profile_id,
                    row_data={"cells": cells},
                    validation_errors=[],
                ))
                db.add(EventRegistrant(
                    event_id=event.id,
                    last_import_batch_id=batch.id,
                    profile_id=profile_id,
                    source_key=source_key,
                    source_filename=batch.original_filename,
                    sheet_name=sheet_name,
                    source_row=source_row,
                    full_name=full_name,
                    company=company,
                    shortlist_status=extra_cells.get("Must-Meet"),
                    raw_data=cells,
                ))
            db.commit()

        sheets = self.client.get(f"/api/v1/admin/events/{event_id}/research/sheets")
        self.assertEqual(sheets.status_code, 200, sheets.text)
        self.assertEqual(sheets.json()["row_count"], 4)
        self.assertEqual(sheets.json()["unique_registrant_profile_ids"], 2)
        by_sheet = {item["sheet_name"]: item for item in sheets.json()["sheets"]}
        self.assertEqual(by_sheet["Registrants"]["row_count"], 2)
        self.assertEqual(by_sheet["Strong shortlist"]["row_count"], 1)
        self.assertEqual(by_sheet["CSE Research"]["row_count"], 1)

        matches = self.client.get(
            f"/api/v1/admin/events/{event_id}/research/attendees?search=CSE%20evidence%20phrase"
        )
        self.assertEqual(matches.status_code, 200, matches.text)
        self.assertEqual(matches.json()["total"], 1)
        person = matches.json()["items"][0]
        self.assertEqual(person["membership_count"], 3)
        self.assertEqual(set(person["sheets"]), {"Registrants", "Strong shortlist", "CSE Research"})

        same_name = self.client.get(
            f"/api/v1/admin/events/{event_id}/research/attendees?search=Jordan%20Example"
        )
        self.assertEqual(same_name.status_code, 200, same_name.text)
        self.assertEqual(same_name.json()["total"], 2)

        detail = self.client.get(
            f"/api/v1/admin/events/{event_id}/research/attendees/{person['id']}"
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertEqual(len(detail.json()["memberships"]), 3)
        self.assertIn("CSE evidence phrase", str(detail.json()["memberships"]))

        exported = self.client.get(f"/api/v1/admin/events/{event_id}/research/export?sheet=CSE%20Research")
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment; filename=", exported.headers["content-disposition"])
        export_rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig"))))
        self.assertEqual(len(export_rows), 1)
        self.assertEqual(export_rows[0]["Untrusted cell"], "'=1+1")

    def test_unmatched_visitor_metric_excludes_unmatched_imported_research_rows(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
            db.add(EventRegistrant(
                event_id=event.id,
                profile_id="UNMET-RESEARCH-TARGET",
                source_key="profile:unmet-research-target:sheet:registrants:row:2",
                source_filename="research.xlsx",
                sheet_name="Registrants",
                source_row=2,
                full_name="Unmet Research Target",
                company="Research Example Ltd",
                raw_data={},
            ))
            db.commit()

        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["research"]["unmatched_registrants"], 1)
        self.assertEqual(dashboard.json()["activity"]["unmatched_visitors"], 0)

        submission = self.submit(
            full_name="Actual Booth Visitor",
            company="Booth Example Ltd",
            email="actual-booth-visitor@example.com",
            phone="+14155552679",
            event_slug="test-event",
        )
        self.assertEqual(submission.status_code, 201, submission.text)
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["activity"]["unmatched_visitors"], 1)
        self.assertEqual(dashboard.json()["activity"]["unmatched_submissions"], 1)

    def test_research_matching_is_scoped_to_the_selected_event(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            other_event = Event(name="Other Event", slug="other-event", is_active=True)
            db.add(other_event)
            db.flush()
            registrant = EventRegistrant(
                event_id=other_event.id,
                profile_id="OTHER-EVENT-PROFILE",
                source_key="profile:other-event-profile:sheet:registrants:row:2",
                source_filename="other-event.xlsx",
                sheet_name="Registrants",
                source_row=2,
                full_name="Cross Event Contact",
                company="Shared Systems",
                raw_data={"Profile ID": "OTHER-EVENT-PROFILE"},
            )
            db.add(registrant)
            db.commit()
            event_id = str(other_event.id)
            registrant_id = str(registrant.id)

        submission = self.submit(
            full_name="Cross Event Contact",
            company="Shared Systems",
            email="cross-event-contact@example.com",
            phone="+14155552677",
            event_slug="test-event",
        )
        self.assertEqual(submission.status_code, 201, submission.text)
        lead_id = submission.json()["id"]
        suggestions = self.client.get(
            f"/api/v1/admin/events/{event_id}/research/registrants/{registrant_id}/matches"
        )
        self.assertEqual(suggestions.status_code, 200, suggestions.text)
        self.assertNotIn(lead_id, {item["id"] for item in suggestions.json() if item["kind"] == "lead"})
        linked = self.client.post(
            f"/api/v1/admin/events/{event_id}/research/registrants/{registrant_id}/match",
            json={"lead_id": lead_id},
        )
        self.assertEqual(linked.status_code, 422, linked.text)

    def test_research_attendee_encounters_do_not_create_leads_and_link_later(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
            registrants = []
            for sheet_name, source_row in (("Registrants", 2), ("Strong shortlist", 4)):
                registrant = EventRegistrant(
                    event_id=event.id,
                    profile_id="PROFILE-ENCOUNTER-001",
                    source_key=f"profile:profile-encounter-001:sheet:{sheet_name.casefold()}:row:{source_row}",
                    source_filename="research.xlsx",
                    sheet_name=sheet_name,
                    source_row=source_row,
                    full_name="Casey Research",
                    company="Research Systems",
                    raw_data={"Profile ID": "PROFILE-ENCOUNTER-001", "Name": "Casey Research"},
                )
                db.add(registrant)
                registrants.append(registrant)
            db.commit()
            ids = [str(row.id) for row in registrants]

        met = self.client.post(
            f"/api/v1/admin/events/{event_id}/encounters",
            json={"registrant_id": ids[0], "encounter_type": "met", "notes": "Discussed research goals."},
        )
        self.assertEqual(met.status_code, 201, met.text)
        self.assertIsNone(met.json()["lead_id"])
        self.assertEqual(met.json()["profile_id"], "PROFILE-ENCOUNTER-001")
        self.assertEqual(met.json()["status"], "completed")

        demo = self.client.post(
            f"/api/v1/admin/events/{event_id}/encounters",
            json={"registrant_id": ids[1], "encounter_type": "demo", "topics": ["Agentic AI"]},
        )
        self.assertEqual(demo.status_code, 201, demo.text)
        self.assertTrue(demo.json()["demo_presented"])

        meeting = self.client.post(
            f"/api/v1/admin/events/{event_id}/encounters",
            json={"registrant_id": ids[0], "encounter_type": "meeting", "status": "confirmed", "next_steps": "Send the demo notes.", "follow_up_due_at": "2030-01-01T00:00:00Z"},
        )
        self.assertEqual(meeting.status_code, 201, meeting.text)
        self.assertEqual(meeting.json()["status"], "confirmed")
        unified_meetings = self.client.get(f"/api/v1/admin/events/{event_id}/meetings")
        self.assertEqual(unified_meetings.status_code, 200, unified_meetings.text)
        self.assertEqual(len(unified_meetings.json()), 1)
        self.assertEqual(unified_meetings.json()[0]["kind"], "research_meeting")
        self.assertEqual(unified_meetings.json()[0]["registrant_id"], ids[0])

        from_other_membership = self.client.get(
            f"/api/v1/admin/events/{event_id}/research/attendees/{ids[1]}/encounters"
        )
        self.assertEqual(from_other_membership.status_code, 200, from_other_membership.text)
        self.assertEqual(len(from_other_membership.json()), 3)
        self.assertEqual({row["lead_id"] for row in from_other_membership.json()}, {None})
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.text)
        self.assertEqual(dashboard.json()["activity"]["staff_confirmed_encounters"], 2)
        self.assertEqual(dashboard.json()["activity"]["unique_people_met"], 1)
        self.assertEqual(dashboard.json()["activity"]["confirmed_meetings"], 1)
        self.assertEqual(dashboard.json()["activity"]["outstanding_follow_ups"], 1)

        completed = self.client.patch(
            f"/api/v1/admin/event-encounters/{meeting.json()['id']}",
            json={"status": "completed"},
        )
        self.assertEqual(completed.status_code, 200, completed.text)
        self.assertEqual(completed.json()["status"], "completed")
        unified_meetings = self.client.get(f"/api/v1/admin/events/{event_id}/meetings")
        self.assertEqual(unified_meetings.json()[0]["status"], "completed")
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.json()["activity"]["confirmed_meetings"], 1)
        self.assertEqual(dashboard.json()["activity"]["outstanding_follow_ups"], 0)

        submission = self.submit(
            full_name="Casey Research",
            company="Research Systems",
            email="casey-research@example.com",
            phone="+14155552678",
            event_slug="test-event",
        )
        self.assertEqual(submission.status_code, 201, submission.text)
        lead_id = submission.json()["id"]
        linked = self.client.post(
            f"/api/v1/admin/events/{event_id}/research/registrants/{ids[1]}/match",
            json={"lead_id": lead_id},
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        with self.TestSession() as db:
            encounters = db.scalars(select(EventEncounter).where(EventEncounter.event_id == uuid.UUID(event_id))).all()
            self.assertEqual({str(item.lead_id) for item in encounters}, {lead_id})

    def test_event_priority_panels_use_explicit_source_priority_and_open_actions(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            rows = [
                EventRegistrant(event_id=event.id, profile_id="TARGET-A", source_key="target-a:shortlist", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=2, full_name="A Target", company="Alpha Systems", raw_data={"Must-Meet": "A", "Relationship": "Client", "Latent Sig Fit": "Strong", "Opener": "Discuss a validated manufacturing workflow."}),
                EventRegistrant(event_id=event.id, profile_id="TARGET-A", source_key="target-a:client", source_filename="research.xlsx", sheet_name="Clients-Strong", source_row=3, full_name="A Target", company="Alpha Systems", raw_data={"Relationship": "Client", "Latent Sig Fit": "Strong", "Suggested Angle": "Same person from another worksheet."}),
                EventRegistrant(event_id=event.id, profile_id="TARGET-B", source_key="target-b:shortlist", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=4, full_name="B Target", company="Beta Systems", raw_data={"Must-Meet": "B", "Relationship": "Design Partner", "Latent Sig Fit": "Strong", "Opener": "Explore a small prototype."}),
                EventRegistrant(event_id=event.id, profile_id="TARGET-MET", source_key="target-met:shortlist", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=5, full_name="Met Target", company="Gamma Systems", raw_data={"Must-Meet": "A", "Relationship": "Client", "Latent Sig Fit": "Strong"}),
                EventRegistrant(event_id=event.id, profile_id="BAD-PRIORITY", source_key="bad-priority:shortlist", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=6, full_name="Bad Priority", company="Delta Systems", raw_data={"Must-Meet": "https://example.com", "Relationship": "Competitor", "Latent Sig Fit": "Strong"}),
                EventRegistrant(event_id=event.id, profile_id="OPPORTUNITY", source_key="opportunity:design", source_filename="research.xlsx", sheet_name="Design Partners", source_row=7, full_name="Opportunity Target", company="Partner Systems", raw_data={"Relationship": "Design Partner", "Latent Sig Fit": "Strong", "Suggested Angle": "Research-backed partnership idea."}),
                EventRegistrant(event_id=event.id, profile_id="RECONCILE", source_key="reconcile:row", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=8, full_name="Needs Review", company="Review Systems", raw_data={}, reconciliation_required=True, reconciliation_errors=["Missing Profile ID"]),
            ]
            db.add_all(rows)
            db.flush()
            db.add(EventEncounter(event_id=event.id, registrant_id=rows[3].id, identity_key="profile:target-met", encounter_type="met", status="completed", notes="Already met."))
            db.add(EventEncounter(event_id=event.id, registrant_id=rows[0].id, identity_key="profile:target-a", encounter_type="meeting", status="requested", follow_up_due_at=datetime.now(timezone.utc) - timedelta(days=1), next_steps="Send the agenda."))
            db.commit()
            event_id = str(event.id)

        response = self.client.get(f"/api/v1/admin/events/{event_id}/priority-panels")
        self.assertEqual(response.status_code, 200, response.text)
        panels = response.json()
        must_meet = panels["must_meet_next"]
        self.assertEqual(must_meet["total"], 2)
        self.assertEqual(must_meet["priority_counts"], {"A": 1, "B": 1})
        self.assertEqual([item["priority"] for item in must_meet["items"]], ["A", "B"])
        self.assertEqual(must_meet["items"][0]["profile_id"], "TARGET-A")
        self.assertEqual(must_meet["items"][0]["pitch"], "Discuss a validated manufacturing workflow.")
        self.assertNotIn("TARGET-MET", {item["profile_id"] for item in must_meet["items"]})
        self.assertNotIn("BAD-PRIORITY", {item["profile_id"] for item in must_meet["items"]})
        self.assertEqual(panels["research_opportunities"]["total"], 1)
        self.assertEqual(panels["research_opportunities"]["items"][0]["profile_id"], "OPPORTUNITY")
        self.assertEqual(panels["follow_ups"]["total"], 1)
        self.assertEqual(panels["follow_ups"]["items"][0]["next_steps"], "Send the agenda.")
        self.assertEqual(panels["needs_review"]["reconciliation_rows"], 1)
        self.assertEqual(panels["needs_review"]["reconciliation_items"][0]["sheet_name"], "Strong shortlist")
        priority_a = self.client.get(f"/api/v1/admin/events/{event_id}/research/registrants?sheet=Strong%20shortlist&priority=A&page_size=100")
        self.assertEqual(priority_a.status_code, 200, priority_a.text)
        self.assertEqual(priority_a.json()["total"], 2)
        self.assertTrue(all(row["raw_data"]["Must-Meet"] == "A" for row in priority_a.json()["items"]))
        priority_b = self.client.get(f"/api/v1/admin/events/{event_id}/research/registrants?sheet=Strong%20shortlist&priority=B&page_size=100")
        self.assertEqual(priority_b.status_code, 200, priority_b.text)
        self.assertEqual(priority_b.json()["total"], 1)
        self.assertEqual(priority_b.json()["items"][0]["raw_data"]["Must-Meet"], "B")

    def test_contactless_card_capture_collapses_duplicate_worksheet_candidates(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
            for sheet_name, source_row in (("Registrants", 2), ("Clients-Strong", 14)):
                db.add(EventRegistrant(
                    event_id=event.id, profile_id="PROFILE-CARD-001",
                    source_key=f"profile:profile-card-001:sheet:{sheet_name.casefold()}:row:{source_row}",
                    source_filename="research.xlsm", sheet_name=sheet_name, source_row=source_row,
                    full_name="Morgan Research", company="Research Systems", raw_data={},
                ))
            db.commit()

        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        extraction = CardExtraction(full_name="Morgan Research", company="Research Systems", job_title="Director")
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=extraction), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("contactless-profile-card.jpg", len(image_bytes))):
            response = self.client.post(
                "/api/v1/admin/card-captures", data={"event_id": event_id},
                files={"file": ("morgan-card.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "linked")
        self.assertEqual(len(response.json()["candidates"]), 1)
        self.assertEqual(response.json()["candidates"][0]["kind"], "registrant")
        self.assertEqual(response.json()["candidates"][0]["source_records"], 2)
        with self.TestSession() as db:
            rows = db.scalars(select(EventRegistrant).where(EventRegistrant.profile_id == "PROFILE-CARD-001")).all()
            lead = db.get(Lead, uuid.UUID(response.json()["lead_id"]))
            self.assertEqual({row.match_status for row in rows}, {"matched"})
            self.assertEqual({row.matched_lead_id for row in rows}, {lead.id})
            self.assertIsNone(lead.email)
            self.assertIsNone(lead.phone)

    def test_distinct_profile_ids_with_same_name_company_remain_ambiguous(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
            for profile_id, sheet_name, source_row in (
                ("PROFILE-AMBIGUOUS-001", "Registrants", 2),
                ("PROFILE-AMBIGUOUS-002", "Clients-Strong", 9),
            ):
                db.add(EventRegistrant(
                    event_id=event.id, profile_id=profile_id,
                    source_key=f"profile:{profile_id.casefold()}:sheet:{sheet_name.casefold()}:row:{source_row}",
                    source_filename="research.xlsx", sheet_name=sheet_name, source_row=source_row,
                    full_name="Taylor Example", company="Example Systems", raw_data={},
                ))
            db.commit()

        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        extraction = CardExtraction(full_name="Taylor Example", company="Example Systems")
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=extraction), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("ambiguous-profile-card.jpg", len(image_bytes))):
            response = self.client.post(
                "/api/v1/admin/card-captures", data={"event_id": event_id},
                files={"file": ("taylor-card.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "pending_match")
        self.assertEqual(len(response.json()["candidates"]), 2)
        self.assertEqual({item["profile_id"] for item in response.json()["candidates"]}, {
            "PROFILE-AMBIGUOUS-001", "PROFILE-AMBIGUOUS-002",
        })
        self.assertIsNone(response.json()["lead_id"])

    def test_manual_registrant_match_links_all_rows_for_profile_id(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = event.id
            lead = Lead(lead_code="PROFILE-MANUAL-001", full_name="Robin Research", company="Systems Lab")
            db.add(lead)
            db.flush()
            rows = []
            for sheet_name, source_row in (("Registrants", 3), ("Design Partners", 8)):
                row = EventRegistrant(
                    event_id=event.id, profile_id="PROFILE-MANUAL-001",
                    source_key=f"profile:profile-manual-001:sheet:{sheet_name.casefold()}:row:{source_row}",
                    source_filename="research.xlsx", sheet_name=sheet_name, source_row=source_row,
                    full_name="Robin Research", company="Systems Lab", raw_data={},
                )
                db.add(row)
                rows.append(row)
            db.add(Interaction(lead_id=lead.id, event_id=event.id, interest=[], intent="Unspecified", capture_method="manual", source="event-test"))
            db.commit()
            event_id, registrant_id, lead_id = str(event_id), str(rows[0].id), str(lead.id)

        response = self.client.post(
            f"/api/v1/admin/events/{event_id}/research/registrants/{registrant_id}/match",
            json={"lead_id": lead_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["matched_source_rows"], 2)
        with self.TestSession() as db:
            rows = db.scalars(select(EventRegistrant).where(EventRegistrant.profile_id == "PROFILE-MANUAL-001")).all()
            self.assertEqual({row.match_status for row in rows}, {"matched"})
            self.assertEqual({row.matched_lead_id for row in rows}, {uuid.UUID(lead_id)})

    def test_staff_manual_capture_keeps_missing_fields_and_consent_blank(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            session = EventSession(event_id=event.id, name="Morning", slug="manual-morning")
            db.add(session)
            db.commit()
            event_id, session_id = str(event.id), str(session.id)

        response = self.client.post("/api/v1/admin/manual-captures", json={
            "event_id": event_id, "session_id": session_id,
            "fields": {"full_name": "Jamie Manual", "company": "Example Works"},
            "notes": "Asked about annotation services.",
        })
        self.assertEqual(response.status_code, 201, response.text)
        result = response.json()
        self.assertEqual(result["event_name"], "Test Event")
        self.assertEqual(result["status"], "pending_review")
        self.assertTrue(result["created_lead"])
        with self.TestSession() as db:
            lead = db.get(Lead, uuid.UUID(result["lead_id"]))
            interaction = db.get(Interaction, uuid.UUID(result["interaction_id"]))
            self.assertEqual(lead.full_name, "Jamie Manual")
            self.assertEqual(lead.company, "Example Works")
            self.assertIsNone(lead.email)
            self.assertIsNone(lead.phone)
            self.assertEqual(interaction.event_id, uuid.UUID(event_id))
            self.assertEqual(interaction.session_id, uuid.UUID(session_id))
            self.assertEqual(interaction.capture_method, "manual")
            self.assertEqual(interaction.source, "staff_quick_capture")
            self.assertEqual(interaction.status, "pending_review")
            self.assertEqual(interaction.requirement_message, "Asked about annotation services.")
            self.assertIsNone(interaction.data_processing_consent_at)
            self.assertIsNone(interaction.follow_up_consent_at)
            self.assertIsNone(interaction.ai_processing_consent_at)
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.json()["activity"]["submissions"], 1)
        self.assertEqual(dashboard.json()["activity"]["staff_manual_captures"], 1)
        self.assertEqual(dashboard.json()["activity"]["staff_card_captures"], 0)

    def test_staff_manual_capture_requires_review_for_ambiguous_research_matches(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            db.add_all([
                EventRegistrant(event_id=event.id, profile_id="MANUAL-A", source_key="profile:manual-a", source_filename="research.xlsx", sheet_name="Registrants", source_row=2, full_name="Alex Visitor", company="Example Labs", raw_data={}),
                EventRegistrant(event_id=event.id, profile_id="MANUAL-B", source_key="profile:manual-b", source_filename="research.xlsx", sheet_name="Strong shortlist", source_row=3, full_name="Alex Visitor", company="Example Labs", raw_data={}),
            ])
            db.commit()
            event_id = str(event.id)

        payload = {"event_id": event_id, "fields": {"full_name": "Alex Visitor", "company": "Example Labs"}}
        ambiguous = self.client.post("/api/v1/admin/manual-captures", json=payload)
        self.assertEqual(ambiguous.status_code, 409, ambiguous.text)
        suggestions = ambiguous.json()["detail"]["candidates"]
        self.assertEqual(len(suggestions), 2)
        linked = self.client.post("/api/v1/admin/manual-captures", json={**payload, "registrant_id": suggestions[0]["id"]})
        self.assertEqual(linked.status_code, 201, linked.text)
        self.assertTrue(linked.json()["matched_research"])
        with self.TestSession() as db:
            selected_profile_id = next(item["profile_id"] for item in suggestions if item["id"] == suggestions[0]["id"])
            unselected_profile_id = next(item["profile_id"] for item in suggestions if item["id"] != suggestions[0]["id"])
            rows = db.scalars(select(EventRegistrant).where(EventRegistrant.profile_id == selected_profile_id)).all()
            siblings = db.scalars(select(EventRegistrant).where(EventRegistrant.profile_id == unselected_profile_id)).all()
            self.assertEqual({row.match_status for row in rows}, {"matched"})
            self.assertEqual({row.matched_lead_id for row in rows}, {uuid.UUID(linked.json()["lead_id"])})
            self.assertTrue(all(row.match_status == "unmatched" for row in siblings))

    def test_staff_manual_capture_links_exact_contact_from_another_event(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            previous_event = Event(name="Previous Event", slug="previous-event", is_active=True)
            db.add(previous_event)
            db.flush()
            lead = Lead(lead_code="LS-PREVIOUS-000001", full_name="Morgan Existing", email="morgan@example.com", normalized_email="morgan@example.com")
            db.add(lead)
            db.flush()
            db.add(Interaction(lead_id=lead.id, event_id=previous_event.id, interest=[], intent="Unspecified", capture_method="manual", source="prior-event"))
            db.commit()
            event_id, lead_id = str(event.id), lead.id

        response = self.client.post("/api/v1/admin/manual-captures", json={
            "event_id": event_id, "fields": {"full_name": "Morgan Existing", "email": "morgan@example.com"},
        })
        self.assertEqual(response.status_code, 201, response.text)
        self.assertFalse(response.json()["created_lead"])
        self.assertEqual(uuid.UUID(response.json()["lead_id"]), lead_id)
        with self.TestSession() as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(Lead)), 1)
            current_event_interaction = db.get(Interaction, uuid.UUID(response.json()["interaction_id"]))
            self.assertEqual(current_event_interaction.event_id, uuid.UUID(event_id))
            self.assertIsNone(current_event_interaction.data_processing_consent_at)

    def test_staff_card_capture_saves_incomplete_lead_without_inventing_consent(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            session = EventSession(event_id=event.id, name="Morning", slug="morning")
            db.add(session)
            db.commit()
            event_id, session_id = str(event.id), str(session.id)

        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        extraction = CardExtraction(full_name="Casey Example", company="Example Labs", job_title="CTO")
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=extraction), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("test-card.jpg", len(image_bytes))):
            response = self.client.post(
                "/api/v1/admin/card-captures",
                data={"event_id": event_id, "session_id": session_id},
                files={"file": ("card.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "linked")
        self.assertEqual(response.json()["event_id"], event_id)
        self.assertEqual(response.json()["captured_by"], "Admin User")
        self.assertFalse(response.json()["external_ai_consent_recorded"])
        lead_id = uuid.UUID(response.json()["lead_id"])
        with self.TestSession() as db:
            lead = db.get(Lead, lead_id)
            interaction = db.scalar(select(Interaction).where(Interaction.lead_id == lead_id))
            card = db.scalar(select(BusinessCard).where(BusinessCard.lead_id == lead_id))
            capture = db.get(StaffCardCapture, uuid.UUID(response.json()["id"]))
            self.assertEqual(lead.full_name, "Casey Example")
            self.assertIsNone(lead.email)
            self.assertEqual(interaction.event_id, uuid.UUID(event_id))
            self.assertEqual(interaction.session_id, uuid.UUID(session_id))
            self.assertEqual(interaction.status, "pending_review")
            self.assertIsNone(interaction.data_processing_consent_at)
            self.assertIsNone(interaction.follow_up_consent_at)
            self.assertIsNone(interaction.ai_processing_consent_at)
            self.assertIsNotNone(card)
            self.assertEqual(capture.captured_by_user_id, db.scalar(select(User.id).where(User.email == "bharat@latentsig.com")))
            interaction_id = str(interaction.id)

        meeting = self.client.post(
            f"/api/v1/admin/leads/{lead_id}/meetings/confirm",
            json={
                "event_id": event_id, "interaction_id": interaction_id,
                "topics": ["Agentic AI"], "notes": "Synthetic workflow verification",
                "demo_presented": True, "next_steps": "Send follow-up details",
                "follow_up_due_at": "2026-12-01T09:00:00+00:00",
            },
        )
        self.assertEqual(meeting.status_code, 201, meeting.text)
        self.assertEqual(meeting.json()["status"], "confirmed")
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.json()["activity"]["submissions"], 0)
        self.assertEqual(dashboard.json()["activity"]["staff_confirmed_encounters"], 1)
        self.assertEqual(dashboard.json()["activity"]["confirmed_meetings"], 1)
        self.assertEqual(dashboard.json()["activity"]["outstanding_follow_ups"], 1)

        synthetic = CardExtraction(full_name="Synthetic Smoke", company="Test Only")
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=synthetic), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("synthetic-card.jpg", len(image_bytes))):
            synthetic_capture = self.client.post(
                "/api/v1/admin/card-captures",
                data={"event_id": event_id, "synthetic_test": "true"},
                files={"file": ("synthetic.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(synthetic_capture.status_code, 201, synthetic_capture.text)
        self.assertTrue(synthetic_capture.json()["synthetic_test"])
        dashboard = self.client.get(f"/api/v1/admin/events/{event_id}/dashboard")
        self.assertEqual(dashboard.json()["activity"]["staff_confirmed_encounters"], 1)
        self.assertEqual(self.client.delete(f"/api/v1/admin/card-captures/{synthetic_capture.json()['id']}").status_code, 204)
        with self.TestSession() as db:
            self.assertIsNone(db.get(Lead, uuid.UUID(synthetic_capture.json()["lead_id"])))

    def test_staff_card_ocr_failure_can_be_recovered_in_review(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        with patch.object(settings, "ocr_provider", "ollama"), patch.object(settings, "ocr_enabled", True), \
                patch.object(staff_capture_routes, "extract_card", side_effect=VisionUnavailable("OCR unavailable")), \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("test-card-failed.jpg", len(image_bytes))):
            response = self.client.post(
                "/api/v1/admin/card-captures",
                files={"file": ("failed.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "ocr_failed")
        capture_id = response.json()["id"]
        recovered = self.client.post(
            f"/api/v1/admin/card-captures/{capture_id}/resolve",
            json={"fields": {"full_name": "Manual Example", "company": "Manual Co"}},
        )
        self.assertEqual(recovered.status_code, 200, recovered.text)
        self.assertEqual(recovered.json()["status"], "linked")
        self.assertEqual(recovered.json()["lead_name"], "Manual Example")

    def test_staff_card_permissions_and_external_ai_policy_are_enforced(self):
        self.assertEqual(self.sign_in("raksha@latentsig.com").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/admin/card-capture-policy").status_code, 403)
        self.client.post("/api/v1/auth/logout")
        self.assertEqual(self.sign_in("bhoomika@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            event_id = str(event.id)
        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        denied = self.client.post(
            "/api/v1/admin/card-captures", data={"event_id": event_id},
            files={"file": ("card.jpg", image_bytes, "image/jpeg")},
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        self.client.post("/api/v1/auth/logout")
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with patch.object(settings, "ocr_provider", "openrouter"), \
                patch.object(settings, "staff_card_processing_rules_approved", False), \
                patch.object(staff_capture_routes, "extract_card") as extract, \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("test-private-card.jpg", len(image_bytes))):
            consent_denied = self.client.post(
                "/api/v1/admin/card-captures",
                data={"external_ai_consent": "true"},
                files={"file": ("card.jpg", image_bytes, "image/jpeg")},
            )
            skipped = self.client.post(
                "/api/v1/admin/card-captures",
                files={"file": ("card.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(consent_denied.status_code, 403, consent_denied.text)
        self.assertEqual(skipped.status_code, 201, skipped.text)
        self.assertEqual(skipped.json()["status"], "pending_review")
        self.assertFalse(skipped.json()["external_ai_consent_recorded"])
        self.assertIn("skipped", skipped.json()["error"])
        extract.assert_not_called()

    def test_synthetic_card_cannot_bypass_external_ai_consent(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        with patch.object(settings, "ocr_provider", "openrouter"), \
                patch.object(settings, "ocr_enabled", True), \
                patch.object(settings, "staff_card_processing_rules_approved", False), \
                patch.object(staff_capture_routes, "extract_card") as extract, \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("synthetic-private-card.jpg", len(image_bytes))):
            synthetic = self.client.post(
                "/api/v1/admin/card-captures",
                data={"synthetic_test": "true"},
                files={"file": ("synthetic.jpg", image_bytes, "image/jpeg")},
            )
            fabricated_consent = self.client.post(
                "/api/v1/admin/card-captures",
                data={"synthetic_test": "true", "external_ai_consent": "true"},
                files={"file": ("synthetic.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(synthetic.status_code, 201, synthetic.text)
        self.assertTrue(synthetic.json()["synthetic_test"])
        self.assertTrue(synthetic.json()["exclude_from_analytics"])
        self.assertEqual(synthetic.json()["status"], "pending_review")
        self.assertFalse(synthetic.json()["external_ai_consent_recorded"])
        self.assertEqual(fabricated_consent.status_code, 422, fabricated_consent.text)
        self.assertIn("cannot record visitor AI consent", fabricated_consent.json()["detail"])
        extract.assert_not_called()
        self.assertEqual(self.client.get("/api/v1/admin/card-captures").json()["total"], 0)
        visible_tests = self.client.get("/api/v1/admin/card-captures?include_synthetic=true")
        self.assertEqual(visible_tests.json()["total"], 1)
        with patch.object(staff_capture_routes.storage, "delete") as delete_storage:
            removed = self.client.delete(f"/api/v1/admin/card-captures/{synthetic.json()['id']}")
        self.assertEqual(removed.status_code, 204)
        delete_storage.assert_called_once()

    def test_card_capture_inbox_filters_groups_dates_and_protects_thumbnails(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        with self.TestSession() as db:
            event = db.scalar(select(Event).where(Event.slug == "test-event"))
            now = datetime.now(timezone.utc)
            captures = []
            for status in ("pending_review", "template_detected", "pending_match", "linked", "ocr_failed"):
                capture = StaffCardCapture(
                    event_id=event.id, original_filename=f"{status}.jpg", mime_type="image/jpeg", file_size=12,
                    storage_path=f"private/{status}.jpg", ocr_json={"full_name": "Inbox Person"}, status=status,
                    synthetic_test=status == "ocr_failed", exclude_from_analytics=status == "ocr_failed",
                    created_at=now,
                )
                db.add(capture)
                captures.append(capture)
            db.commit()
            event_id = str(event.id)
            capture_id = str(captures[0].id)

        grouped = self.client.get(
            f"/api/v1/admin/card-captures?event_id={event_id}&status=pending_review%2Ctemplate_detected"
        )
        self.assertEqual(grouped.status_code, 200, grouped.text)
        self.assertEqual(grouped.json()["total"], 2)
        self.assertEqual({item["status"] for item in grouped.json()["items"]}, {"pending_review", "template_detected"})
        recent = self.client.get("/api/v1/admin/card-captures?created_after=2099-01-01T00%3A00%3A00Z")
        self.assertEqual(recent.status_code, 200, recent.text)
        self.assertEqual(recent.json()["total"], 0)
        invalid = self.client.get("/api/v1/admin/card-captures?status=unknown")
        self.assertEqual(invalid.status_code, 422)

        original = io.BytesIO()
        Image.new("RGB", (1200, 800), "white").save(original, format="JPEG")
        with patch.object(staff_capture_routes.storage, "read", return_value=original.getvalue()):
            thumbnail = self.client.get(f"/api/v1/admin/card-captures/{capture_id}/thumbnail")
        self.assertEqual(thumbnail.status_code, 200, thumbnail.text)
        self.assertEqual(thumbnail.headers["content-type"], "image/jpeg")
        self.assertEqual(thumbnail.headers["cache-control"], "private, no-store")
        with Image.open(io.BytesIO(thumbnail.content)) as preview:
            self.assertEqual(preview.format, "JPEG")
            self.assertLessEqual(preview.width, 360)
            self.assertLessEqual(preview.height, 240)

        self.assertEqual(self.sign_in("bhoomika@latentsig.com").status_code, 200)
        with patch.object(staff_capture_routes.storage, "read") as unauthorized_read:
            unauthorized = self.client.get(f"/api/v1/admin/card-captures/{capture_id}/thumbnail")
        self.assertEqual(unauthorized.status_code, 404)
        unauthorized_read.assert_not_called()

    def test_approved_synthetic_card_uses_external_ocr_without_fabricating_consent(self):
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)
        image = io.BytesIO()
        Image.new("RGB", (200, 120), "white").save(image, format="JPEG")
        image_bytes = image.getvalue()
        template = CardExtraction(is_template=True, warnings=["This image looks like a card template or mockup."])
        with patch.object(settings, "ocr_provider", "openrouter"), \
                patch.object(settings, "ocr_enabled", True), \
                patch.object(settings, "staff_card_processing_rules_approved", True), \
                patch.object(staff_capture_routes, "extract_card", return_value=template) as extract, \
                patch.object(staff_capture_routes.storage, "save_private", return_value=("approved-synthetic-card.jpg", len(image_bytes))):
            response = self.client.post(
                "/api/v1/admin/card-captures",
                data={"synthetic_test": "true"},
                files={"file": ("synthetic-template.jpg", image_bytes, "image/jpeg")},
            )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["status"], "template_detected")
        self.assertTrue(response.json()["synthetic_test"])
        self.assertTrue(response.json()["exclude_from_analytics"])
        self.assertFalse(response.json()["external_ai_consent_recorded"])
        self.assertIsNone(response.json()["lead_id"])
        extract.assert_called_once()

    def test_card_scan_requires_explicit_ai_processing_consent(self):
        image = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(image, format="JPEG")
        response = self.client.post("/api/v1/ocr/business-card", files={"files": ("card.jpg", image.getvalue(), "image/jpeg")})
        self.assertEqual(response.status_code, 422)

    def test_ocr_upload_rejects_unsupported_and_mismatched_files_before_recognition(self):
        valid_jpeg = io.BytesIO()
        Image.new("RGB", (100, 100), "white").save(valid_jpeg, format="JPEG")
        unsupported = self.client.post("/api/v1/ocr/business-card", files={"files": ("card.txt", b"not an image", "text/plain")}, data={"ai_processing_consent": "true"})
        mismatch = self.client.post("/api/v1/ocr/business-card", files={"files": ("card.png", valid_jpeg.getvalue(), "image/png")}, data={"ai_processing_consent": "true"})
        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(mismatch.status_code, 415)

    def test_sheets_worker_retries_failure_without_losing_the_lead(self):
        submission = self.submit()
        interaction_id = submission.json()["interaction_id"]
        with self.TestSession() as db:
            db.add(IntegrationJob(type="google_sheets_upsert", entity_id=uuid.UUID(interaction_id), status="pending"))
            db.commit()

        with patch.object(worker, "SessionLocal", self.TestSession), patch.object(worker, "_sync_interaction", side_effect=RuntimeError("Sheets unavailable")):
            self.assertTrue(worker.process_one())
            self.assertFalse(worker.process_one())

        with self.TestSession() as db:
            lead = db.scalar(select(Lead).where(Lead.email == "taylor@example.com"))
            job = db.scalar(select(IntegrationJob).where(IntegrationJob.entity_id == uuid.UUID(interaction_id)))
            self.assertIsNotNone(lead)
            self.assertEqual(job.status, "pending")
            self.assertEqual(job.attempt_count, 1)
            self.assertEqual(job.last_error, "Sheets unavailable")
            self.assertIsNotNone(job.next_retry_at)

    def test_sheets_worker_marks_successful_job_complete(self):
        submission = self.submit()
        interaction_id = submission.json()["interaction_id"]
        with self.TestSession() as db:
            db.add(IntegrationJob(type="google_sheets_upsert", entity_id=uuid.UUID(interaction_id), status="pending"))
            db.commit()

        with patch.object(worker, "SessionLocal", self.TestSession), patch.object(worker, "_sync_interaction"):
            self.assertTrue(worker.process_one())

        with self.TestSession() as db:
            job = db.scalar(select(IntegrationJob).where(IntegrationJob.entity_id == uuid.UUID(interaction_id)))
            self.assertEqual(job.status, "succeeded")
            self.assertEqual(job.attempt_count, 1)

    def test_lead_sort_dashboard_breakdowns_and_bulk_assignment(self):
        first = self.submit(full_name="Zoe Example", email="zoe@example.com", phone="+14155552671")
        second = self.submit(full_name="Aaron Example", email="aaron@example.com", phone="+14155552672")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(self.sign_in("bharat@latentsig.com").status_code, 200)

        sorted_leads = self.client.get("/api/v1/admin/leads", params={"sort_by": "full_name", "sort_order": "asc"})
        self.assertEqual(sorted_leads.status_code, 200, sorted_leads.text)
        self.assertEqual([row["full_name"] for row in sorted_leads.json()["items"]], ["Aaron Example", "Zoe Example"])
        dashboard = self.client.get("/api/v1/admin/dashboard")
        self.assertEqual(dashboard.json()["by_event"], {"Test Event": 2})
        self.assertEqual(dashboard.json()["by_status"]["new"], 2)

        manager = None
        with self.TestSession() as db:
            manager = User(email="manager@latentsig.com", full_name="Manager", role="MANAGER")
            db.add(manager)
            db.commit()
            db.refresh(manager)
            manager_id = str(manager.id)
        assigned = self.client.post("/api/v1/admin/leads/bulk-assign", json={"lead_ids": [first.json()["id"], second.json()["id"]], "assigned_to": manager_id})
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertEqual(assigned.json()["updated"], 2)

        with self.TestSession() as db:
            rows = db.scalars(select(Interaction)).all()
            self.assertEqual({str(row.assigned_to) for row in rows}, {manager_id})

    def test_sales_export_contains_all_visible_rows_and_excludes_other_assignees(self):
        shared = self.submit(email="shared@example.com", phone="+14155552671")
        assigned_elsewhere = self.submit(email="private@example.com", phone="+14155552672")
        self.assertEqual(shared.status_code, 201)
        self.assertEqual(assigned_elsewhere.status_code, 201)

        with self.TestSession() as db:
            other_sales = db.scalar(select(User).where(User.email == "other-sales@latentsig.com"))
            hidden_lead = db.scalar(select(Lead).where(Lead.email == "private@example.com"))
            hidden_interaction = db.scalar(select(Interaction).where(Interaction.lead_id == hidden_lead.id))
            hidden_interaction.assigned_to = other_sales.id
            db.commit()

        self.assertEqual(self.sign_in("bhoomika@latentsig.com").status_code, 200)
        response = self.client.get("/api/v1/admin/exports/leads.xlsx")
        self.assertEqual(response.status_code, 200, response.text)
        workbook = load_workbook(io.BytesIO(response.content), read_only=True)
        self.assertEqual(workbook.sheetnames, ["Leads", "Summary", "Export Metadata"])
        lead_sheet = workbook["Leads"]
        self.assertEqual(lead_sheet.max_row, 2)
        self.assertEqual(lead_sheet.cell(2, 6).value, "shared@example.com")
        self.assertEqual(lead_sheet.cell(1, 20).value, "Address")
        self.assertEqual(lead_sheet.cell(2, 20).value, "One Example Street, Bengaluru")
        workbook.close()

    def test_viewer_cannot_export_and_unallowlisted_user_cannot_sign_in(self):
        self.assertEqual(self.sign_in("raksha@latentsig.com").status_code, 200)
        denied = self.client.get("/api/v1/admin/exports/leads.xlsx")
        self.assertEqual(denied.status_code, 403)

        self.client.post("/api/v1/auth/logout")
        rejected = self.sign_in("outside@example.com")
        self.assertEqual(rejected.status_code, 403)

    def test_email_login_accepts_exact_team_allowlist_only_in_development(self):
        from app.core.config import settings

        expected_emails = {
            "raksha@latentsig.com", "bhoomika@latentsig.com", "bharat@latentsig.com",
            "info@latentsig.com", "shauryasharthak@latentsig.com",
        }
        with patch.object(settings, "admin_email_allowlist", ",".join(sorted(expected_emails))):
            for email in sorted(expected_emails):
                response = self.client.post("/api/v1/auth/email-login", json={"email": email})
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["email"], email)

            outsider = self.client.post("/api/v1/auth/email-login", json={"email": "outside@example.com"})
            self.assertEqual(outsider.status_code, 403)
            self.assertEqual(self.client.get("/api/v1/auth/google/start").status_code, 404)
            self.assertTrue(self.client.get("/api/v1/auth/providers").json()["development_email_login"])
            self.assertEqual(self.client.post("/api/v1/auth/password-login", json={
                "email": "bharat@latentsig.com", "password": "incorrect password",
            }).status_code, 401)

        with patch.object(settings, "app_env", "production"), patch.object(
            rate_limit_module, "settings", Settings(_env_file=None, app_env="development"),
        ):
            disabled = self.client.post("/api/v1/auth/email-login", json={"email": "bharat@latentsig.com"})
            self.assertEqual(disabled.status_code, 404)

    def test_health_readiness_and_http_metrics(self):
        self.assertEqual(self.client.get("/health/live").status_code, 200)
        self.assertEqual(self.client.get("/health/ready").json(), {"status": "ready"})
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn('route="/health/ready"', response.text)

    def test_auth_providers_expose_development_email_login_only_in_development(self):
        self.assertEqual(self.client.get("/api/v1/auth/providers").json(), {
            "password_login": True,
            "development_email_login": True,
        })
        with patch.object(settings, "app_env", "production"), patch.object(
            rate_limit_module, "settings", Settings(_env_file=None, app_env="development"),
        ):
            self.assertEqual(self.client.get("/api/v1/auth/providers").json(), {
                "password_login": True,
                "development_email_login": False,
            })

    def test_production_password_login_sets_session_for_active_allowlisted_user(self):
        password = "correct horse battery staple"
        with self.TestSession() as db:
            user = db.scalar(select(User).where(User.email == "bharat@latentsig.com"))
            user.password_hash = hash_password(password)
            db.commit()

        with patch.object(settings, "app_env", "production"), patch.object(
            rate_limit_module, "settings", Settings(_env_file=None, app_env="development"),
        ):
            response = self.client.post("/api/v1/auth/password-login", json={
                "email": "bharat@latentsig.com", "password": password,
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["email"], "bharat@latentsig.com")
            self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 200)

            wrong_password = self.client.post("/api/v1/auth/password-login", json={
                "email": "bharat@latentsig.com", "password": "wrong password long",
            })
            outside_allowlist = self.client.post("/api/v1/auth/password-login", json={
                "email": "outside@example.com", "password": password,
            })
            self.assertEqual(wrong_password.status_code, 401)
            self.assertEqual(outside_allowlist.status_code, 401)

    def test_sqlite_backup_is_integrity_checked(self):
        from app.core.config import settings

        root = Path(__file__).resolve().parent
        source = root / f".backup-source-{uuid.uuid4().hex}.db"
        backup = None
        try:
            with closing(sqlite3.connect(source)) as database:
                database.execute("CREATE TABLE sample (value TEXT)")
                database.execute("INSERT INTO sample VALUES ('preserved')")
                database.commit()
            with patch.object(settings, "database_url", f"sqlite:///{source.as_posix()}"):
                backup = create_backup(root)
            self.assertTrue(backup.is_file())
            with closing(sqlite3.connect(backup)) as database:
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT value FROM sample").fetchone()[0], "preserved")
        finally:
            for temporary_path in (source, backup, backup.with_suffix(backup.suffix + ".partial") if backup else None):
                if temporary_path and temporary_path.exists():
                    temporary_path.unlink()

    def test_production_settings_do_not_require_google_signup_or_sheets(self):
        with self.assertRaisesRegex(ValueError, "Production requires PostgreSQL"):
            Settings(_env_file=None, app_env="production", app_secret="s" * 40)
        settings = Settings(
            _env_file=None,
            app_env="production", app_secret="s" * 40,
            database_url=f"postgresql+psycopg://latentsig:{'s' * 40}@db:5432/latentsig",
            redis_url="redis://redis:6379/0", frontend_url="https://connect.example.com",
            openrouter_api_key="test-only-key",
            frontend_urls="https://connect.example.com",
            admin_email_allowlist="admin@example.com", initial_admin_emails="admin@example.com",
        )
        self.assertEqual(settings.app_env, "production")

    def test_production_settings_allow_manual_registration_without_openrouter(self):
        production = Settings(
            _env_file=None,
            app_env="production",
            app_secret="s" * 40,
            database_url=f"postgresql+psycopg://latentsig:{'s' * 40}@db:5432/latentsig",
            redis_url="redis://redis:6379/0",
            frontend_url="https://connect.latentsig.com",
            frontend_urls="https://connect.latentsig.com",
            admin_email_allowlist="bhoomika@latentsig.com,bharat@latentsig.com",
            initial_admin_emails="bhoomika@latentsig.com",
            ocr_enabled=False,
            openrouter_api_key="",
        )
        self.assertEqual(production.admin_emails, {"bhoomika@latentsig.com", "bharat@latentsig.com"})
        production_values = {
            "_env_file": None,
            "app_env": "production",
            "app_secret": "s" * 40,
            "database_url": f"postgresql+psycopg://latentsig:{'s' * 40}@db:5432/latentsig",
            "redis_url": "redis://redis:6379/0",
            "frontend_url": "https://connect.latentsig.com",
            "frontend_urls": "https://connect.latentsig.com",
            "admin_email_allowlist": "bhoomika@latentsig.com,bharat@latentsig.com",
            "initial_admin_emails": "bhoomika@latentsig.com",
            "ocr_enabled": False,
        }
        with self.assertRaisesRegex(ValueError, "APP_SECRET must be a unique"):
            Settings(**{**production_values, "app_secret": "replace-with-generated-random-value"})
        with self.assertRaisesRegex(ValueError, "unique PostgreSQL password"):
            Settings(**{**production_values, "database_url": "postgresql+psycopg://latentsig:replace-with-generated-random-value@db:5432/latentsig"})
        with self.assertRaisesRegex(ValueError, "OPENROUTER_API_KEY is required"):
            Settings(
                _env_file=None,
                app_env="production",
                app_secret="s" * 40,
                database_url=f"postgresql+psycopg://latentsig:{'s' * 40}@db:5432/latentsig",
                redis_url="redis://redis:6379/0",
                frontend_url="https://connect.latentsig.com",
                frontend_urls="https://connect.latentsig.com",
                admin_email_allowlist="bhoomika@latentsig.com,bharat@latentsig.com",
                initial_admin_emails="bhoomika@latentsig.com",
                ocr_enabled=True,
                openrouter_api_key="",
            )


if __name__ == "__main__":
    unittest.main()
