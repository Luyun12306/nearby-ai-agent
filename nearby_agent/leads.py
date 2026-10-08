"""Lead validation, quality scoring and persistence.

A lead is "dispatchable" only if a real provider could act on it without
calling the customer back just to ask basic questions: who, where, what,
how urgent, how to reach them, consent to share, and which real provider.
"""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .categories import CATEGORIES, URGENCY_LEVELS

PHONE_RE = re.compile(r"^\+?1?\D*(\d{3})\D*(\d{3})\D*(\d{4})$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
STATE_RE = re.compile(r"^[A-Za-z]{2}$|^[A-Za-z ]{4,}$")


def normalize_phone(phone: str) -> str:
    m = PHONE_RE.match((phone or "").strip())
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}" if m else ""


def validate_lead(data: dict, known_providers: dict) -> tuple:
    """Return (errors, normalized_lead). Errors are phrased so the agent can act on them."""
    errors = []
    c = data.get("customer", {}) or {}
    loc = data.get("service_location", {}) or {}
    job = data.get("job", {}) or {}

    name = (c.get("name") or "").strip()
    if len(name) < 2:
        errors.append("customer.name is missing - ask for the customer's name.")
    phone = normalize_phone(c.get("phone", ""))
    if c.get("phone") and not phone:
        errors.append(f"customer.phone '{c.get('phone')}' is not a valid 10-digit US number - confirm it with the customer.")
    email = (c.get("email") or "").strip()
    if email and not EMAIL_RE.match(email):
        errors.append(f"customer.email '{email}' looks invalid - confirm it with the customer.")
        email = ""
    if not phone and not email:
        errors.append("Need at least a phone number or email so the provider can reach the customer.")
    consent_statement = (c.get("consent_statement") or "").strip()
    if c.get("consent_to_share") is not True or not consent_statement:
        errors.append("customer.consent_to_share must be true and customer.consent_statement must quote the customer's "
                      "agreement - ask if it's OK to share their contact info with the named provider.")

    street = (loc.get("street_address") or "").strip()
    if not re.search(r"\d", street) or len(street) < 5:
        errors.append("service_location.street_address must be a street address with a number - ask where the job is.")
    if not (loc.get("city") or "").strip():
        errors.append("service_location.city is missing.")
    if not STATE_RE.match((loc.get("state") or "").strip()):
        errors.append("service_location.state is missing.")
    if not ZIP_RE.match((loc.get("zip") or "").strip()):
        errors.append("service_location.zip must be a 5-digit ZIP code.")

    if job.get("category") not in CATEGORIES:
        errors.append(f"job.category must be one of: {', '.join(CATEGORIES)}.")
    if job.get("urgency") not in URGENCY_LEVELS:
        errors.append(f"job.urgency must be one of: {', '.join(URGENCY_LEVELS)}.")
    if len((job.get("problem_summary") or "").strip()) < 30:
        errors.append("job.problem_summary is too thin - write 1-3 sentences a technician could act on.")

    pid = data.get("recommended_provider_id")
    if pid not in known_providers:
        errors.append(
            "recommended_provider_id must be the provider_id of a provider returned by search_providers in this "
            "conversation. Never invent providers."
        )
    backups = [b for b in data.get("backup_provider_ids", []) or [] if b in known_providers and b != pid]

    if errors:
        return errors, None

    lead = {
        "lead_id": f"LEAD-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "ready_to_dispatch",
        "customer": {
            "name": name,
            "phone": phone,
            "email": email,
            "preferred_contact_method": c.get("preferred_contact_method") or ("phone" if phone else "email"),
            "consent_to_share": True,
            "consent_statement": consent_statement,
        },
        "service_location": {
            "street_address": street,
            "city": loc["city"].strip(),
            "state": loc["state"].strip(),
            "zip": loc["zip"].strip(),
            "property_type": loc.get("property_type", ""),
            "ownership": loc.get("ownership", ""),
        },
        "job": {
            "category": job["category"],
            "category_label": CATEGORIES[job["category"]].label,
            "urgency": job["urgency"],
            "problem_summary": job["problem_summary"].strip(),
            "details": [d for d in job.get("details", []) or [] if str(d).strip()],
            "availability": job.get("availability", ""),
            "safety_notes": job.get("safety_notes", ""),
            "insurance_claim": job.get("insurance_claim", ""),
        },
        "recommended_provider": known_providers[pid],
        "backup_providers": [known_providers[b] for b in backups],
    }
    lead["quality"] = score_lead(lead)
    return [], lead


def score_lead(lead: dict) -> dict:
    """0-100 heuristic of how actionable a lead is for a provider."""
    checks = {
        # Core (already guaranteed by validation, kept so the score is self-explanatory).
        "contact_reachable": 20,
        "full_address": 15,
        "category_and_urgency": 10,
        "problem_summary": 10,
        "real_provider_with_phone": 10,
        # Enrichment that makes providers more likely to accept.
        "3+_job_details": 10,
        "availability_window": 8,
        "property_type": 4,
        "ownership": 5,
        "phone_and_email": 3,
        "backup_provider": 5,
    }
    c, loc, job = lead["customer"], lead["service_location"], lead["job"]
    passed = {
        "contact_reachable": bool(c["phone"] or c["email"]),
        "full_address": True,
        "category_and_urgency": True,
        "problem_summary": len(job["problem_summary"]) >= 60,
        "real_provider_with_phone": bool(lead["recommended_provider"].get("phone")),
        "3+_job_details": len(job["details"]) >= 3,
        "availability_window": bool(job["availability"]),
        "property_type": bool(loc["property_type"]),
        "ownership": bool(loc["ownership"]),
        "phone_and_email": bool(c["phone"] and c["email"]),
        "backup_provider": bool(lead["backup_providers"]),
    }
    score = sum(w for k, w in checks.items() if passed[k])
    return {"score": score, "missing": [k for k, ok in passed.items() if not ok]}


def save_lead(lead: dict, transcript: list, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{lead['lead_id']}.json"
    path.write_text(json.dumps({**lead, "transcript": transcript}, indent=2))
    return path


def format_lead(lead: dict) -> str:
    c, loc, job, p = lead["customer"], lead["service_location"], lead["job"], lead["recommended_provider"]
    lines = [
        f"LEAD {lead['lead_id']}  [{job['urgency'].upper()}]  {job['category_label']}  quality={lead['quality']['score']}/100",
        f"  Customer : {c['name']} | {c['phone'] or '-'} | {c['email'] or '-'} (prefers {c['preferred_contact_method']})",
        f"  Location : {loc['street_address']}, {loc['city']}, {loc['state']} {loc['zip']}"
        + (f" ({', '.join(x for x in (loc['property_type'], loc['ownership']) if x)})"
           if loc['property_type'] or loc['ownership'] else ""),
        f"  Problem  : {job['problem_summary']}",
    ]
    lines += [f"    - {d}" for d in job["details"]]
    if job["availability"]:
        lines.append(f"  Available: {job['availability']}")
    if job["insurance_claim"]:
        lines.append(f"  Insurance: {job['insurance_claim']}")
    if job["safety_notes"]:
        lines.append(f"  Safety   : {job['safety_notes']}")
    lines.append(f"  Provider : {p['name']} | {p.get('phone', '-')} | {p.get('website', '-')} | {p.get('source_url', '')}")
    for b in lead["backup_providers"]:
        lines.append(f"  Backup   : {b['name']} | {b.get('phone', '-')}")
    return "\n".join(lines)
