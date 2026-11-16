import re
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Iterable
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import EventEncounter, EventRegistrant, Interaction, Lead


def _norm(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def registrant_identity_key(registrant: EventRegistrant) -> tuple[str, str]:
    profile_id = (registrant.profile_id or "").strip().casefold()
    if profile_id:
        return "profile", profile_id
    return "source", (registrant.source_key or str(registrant.id)).strip().casefold()


def registrant_identity_token(registrant: EventRegistrant) -> str:
    identity_type, identity = registrant_identity_key(registrant)
    return f"{identity_type}:{identity}"


def group_registrants(registrants: Iterable[EventRegistrant]) -> dict[tuple[str, str], list[EventRegistrant]]:
    groups: dict[tuple[str, str], list[EventRegistrant]] = defaultdict(list)
    for registrant in registrants:
        groups[registrant_identity_key(registrant)].append(registrant)
    return dict(groups)


def registrant_identity_rows(db: Session, event_id: uuid.UUID, registrant: EventRegistrant) -> list[EventRegistrant]:
    identity_type, identity = registrant_identity_key(registrant)
    query = select(EventRegistrant).where(EventRegistrant.event_id == event_id)
    if identity_type == "profile":
        query = query.where(func.lower(func.trim(EventRegistrant.profile_id)) == identity)
    else:
        query = query.where(EventRegistrant.source_key == registrant.source_key)
    return db.scalars(query).all()


def mark_registrant_identity_matched(db: Session, registrant: EventRegistrant, lead_id: uuid.UUID) -> int:
    rows = registrant_identity_rows(db, registrant.event_id, registrant)
    for row in rows:
        row.matched_lead_id = lead_id
        row.match_status = "matched"
    for encounter in db.scalars(select(EventEncounter).where(
        EventEncounter.event_id == registrant.event_id,
        EventEncounter.identity_key == registrant_identity_token(registrant),
    )).all():
        encounter.lead_id = lead_id
    return len(rows)


def _score_registrant(registrant: EventRegistrant, email: str, phone: str, name: str, company: str) -> dict | None:
    email_match = bool(email and registrant.email and email == registrant.email.strip().casefold())
    phone_match = bool(phone and registrant.phone and phone == re.sub(r"\D", "", registrant.phone))
    candidate_name, candidate_company = _norm(registrant.full_name), _norm(registrant.company)
    name_score = SequenceMatcher(None, name, candidate_name).ratio() if name and candidate_name else 0
    company_score = SequenceMatcher(None, company, candidate_company).ratio() if company and candidate_company else 0
    exact_name_company = bool(name and company and name == candidate_name and company == candidate_company)
    high = email_match or phone_match or exact_name_company
    if not high and not (name_score >= 0.90 and company_score >= 0.88):
        return None
    return {
        "registrant": registrant,
        "score": 1.0 if high else round(0.68 * name_score + 0.32 * company_score, 3),
        "confidence": "high" if high else "possible",
        "matched_by": "email" if email_match else "phone" if phone_match else "name_company",
    }


def find_attendee_candidates(
    db: Session,
    event_id: uuid.UUID | None,
    fields: dict,
    limit: int = 8,
    exclude_registrant_identity: tuple[str, str] | None = None,
) -> list[dict]:
    """Return one candidate per live lead and per imported research identity."""
    email = (fields.get("email") or "").strip().casefold()
    phone = re.sub(r"\D", "", fields.get("phone") or "")
    name, company = _norm(fields.get("full_name")), _norm(fields.get("company"))
    results: list[dict] = []
    leads_query = select(Lead).order_by(Lead.created_at.desc()).limit(5000)
    if event_id:
        leads_query = select(Lead).where(Lead.id.in_(
            select(Interaction.lead_id).where(Interaction.event_id == event_id)
        )).order_by(Lead.created_at.desc()).limit(5000)
    leads = db.scalars(leads_query).all()
    for lead in leads:
        email_match = bool(email and lead.normalized_email and email == lead.normalized_email.casefold())
        phone_match = bool(phone and lead.normalized_phone and phone == re.sub(r"\D", "", lead.normalized_phone))
        lead_name, lead_company = _norm(lead.full_name), _norm(lead.company)
        name_score = SequenceMatcher(None, name, lead_name).ratio() if name and lead_name else 0
        company_score = SequenceMatcher(None, company, lead_company).ratio() if company and lead_company else 0
        exact_name_company = bool(name and company and name == lead_name and company == lead_company)
        high = email_match or phone_match or exact_name_company
        if high or (name_score >= 0.90 and company_score >= 0.88):
            results.append({
                "kind": "lead", "id": str(lead.id), "full_name": lead.full_name, "company": lead.company,
                "email": lead.email, "phone": lead.phone,
                "score": 1.0 if high else round(0.68 * name_score + 0.32 * company_score, 3),
                "confidence": "high" if high else "possible",
                "matched_by": "email" if email_match else "phone" if phone_match else "name_company",
            })

    registrants_query = select(EventRegistrant)
    if event_id:
        registrants_query = registrants_query.where(EventRegistrant.event_id == event_id)
    registrants = db.scalars(registrants_query.order_by(EventRegistrant.created_at.desc()).limit(5000)).all()
    lead_candidate_ids = {uuid.UUID(item["id"]) for item in results if item["kind"] == "lead"}
    for identity, group in group_registrants(registrants).items():
        if identity == exclude_registrant_identity:
            continue
        matches = [match for row in group if (match := _score_registrant(row, email, phone, name, company))]
        if not matches:
            continue
        matched_lead_ids = {row.matched_lead_id for row in group if row.matched_lead_id}
        # A research row already linked to a suggested live lead is the same candidate, not a second visitor.
        if len(matched_lead_ids) == 1 and next(iter(matched_lead_ids)) in lead_candidate_ids:
            continue
        matches.sort(key=lambda match: (
            match["confidence"] == "high", match["score"], bool(match["registrant"].matched_lead_id),
        ), reverse=True)
        best = matches[0]
        registrant = best["registrant"]
        confidence = "possible" if len(matched_lead_ids) > 1 else best["confidence"]
        results.append({
            "kind": "registrant", "id": str(registrant.id), "full_name": registrant.full_name,
            "company": registrant.company, "email": registrant.email, "phone": registrant.phone,
            "profile_id": registrant.profile_id,
            "matched_lead_id": str(next(iter(matched_lead_ids))) if len(matched_lead_ids) == 1 else None,
            "source_records": len(group), "match_status": registrant.match_status,
            "score": best["score"], "confidence": confidence, "matched_by": best["matched_by"],
        })
    results.sort(key=lambda item: (item["score"], item["kind"] == "lead"), reverse=True)
    return results[:limit]


def link_event_research_registrants(db: Session, event, lead: Lead) -> None:
    email = (lead.normalized_email or "").strip().casefold()
    phone_digits = re.sub(r"\D", "", lead.normalized_phone or "")
    name, company = _norm(lead.full_name), _norm(lead.company)
    clauses = []
    if email:
        clauses.append(func.lower(func.trim(EventRegistrant.email)) == email)
    if phone_digits:
        normalized_source_phone = EventRegistrant.phone
        for character in ("+", " ", "-", "(", ")", ".", "/"):
            normalized_source_phone = func.replace(normalized_source_phone, character, "")
        clauses.append(normalized_source_phone == phone_digits)
    name_token = next(iter(re.findall(r"[a-z0-9]+", (lead.full_name or "").casefold())), "")
    company_token = next(iter(re.findall(r"[a-z0-9]+", (lead.company or "").casefold())), "")
    if name_token and company_token:
        clauses.append((EventRegistrant.full_name.ilike(f"%{name_token}%")) & EventRegistrant.company.ilike(f"%{company_token}%"))
    if not clauses:
        return
    candidates = db.scalars(select(EventRegistrant).where(EventRegistrant.event_id == event.id, or_(*clauses)).limit(5000)).all()
    groups: dict[tuple[str, str], dict] = {}
    for registrant in candidates:
        match = _score_registrant(registrant, email, phone_digits, name, company)
        if match is None:
            continue
        identity = registrant_identity_key(registrant)
        existing = groups.get(identity)
        if existing is None or (match["confidence"] == "high" and existing["confidence"] != "high") or match["score"] > existing["score"]:
            groups[identity] = match

    high = {identity: match for identity, match in groups.items() if match["confidence"] == "high"}
    if len(high) == 1:
        registrant = next(iter(high.values()))["registrant"]
        siblings = registrant_identity_rows(db, event.id, registrant)
        matched_lead_ids = {row.matched_lead_id for row in siblings if row.matched_lead_id}
        if matched_lead_ids and matched_lead_ids != {lead.id}:
            for row in siblings:
                row.match_status = "suggested"
            return
        mark_registrant_identity_matched(db, registrant, lead.id)
        return

    for match in groups.values():
        for row in registrant_identity_rows(db, event.id, match["registrant"]):
            if row.matched_lead_id != lead.id:
                row.match_status = "suggested"
