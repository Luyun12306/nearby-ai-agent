from nearby_agent.leads import normalize_phone, validate_lead

PROVIDER = {"provider_id": "osm:node/1", "name": "Total Restoration of Texas", "phone": "+1-512-698-8444"}
BACKUP = {"provider_id": "osm:node/2", "name": "Austin Flood & Leak Restoration", "phone": "+1 512-271-5099"}
KNOWN = {PROVIDER["provider_id"]: PROVIDER, BACKUP["provider_id"]: BACKUP}


def good_lead(**overrides):
    lead = {
        "customer": {"name": "Maria Lopez", "phone": "512-555-0142", "email": "maria@example.com", "consent_to_share": True, "consent_statement": "Yes, OK to share with them"},
        "service_location": {"street_address": "1402 Bluebonnet Ln", "city": "Austin", "state": "TX", "zip": "78704",
                             "property_type": "single_family", "ownership": "owner"},
        "job": {
            "category": "water_damage_restoration",
            "urgency": "emergency",
            "problem_summary": "About 2 inches of standing water across a finished basement after last night's storm; carpet and drywall wet.",
            "details": ["Water entering along the north wall", "Sump pump not running", "Started ~11pm last night"],
            "availability": "Home all day today",
        },
        "recommended_provider_id": "osm:node/1",
        "backup_provider_ids": ["osm:node/2", "osm:node/999"],
    }
    lead.update(overrides)
    return lead


def test_valid_lead_is_dispatchable_and_high_quality():
    errors, lead = validate_lead(good_lead(), KNOWN)
    assert errors == []
    assert lead["status"] == "ready_to_dispatch"
    assert lead["customer"]["phone"] == "(512) 555-0142"
    assert lead["recommended_provider"]["name"] == "Total Restoration of Texas"
    assert [b["provider_id"] for b in lead["backup_providers"]] == ["osm:node/2"]  # unknown backup dropped
    assert lead["quality"]["score"] >= 90
    assert lead["customer"]["consent_statement"] == "Yes, OK to share with them"


def test_consent_without_statement_rejected():
    data = good_lead()
    data["customer"] = {**data["customer"], "consent_statement": ""}
    errors, lead = validate_lead(data, KNOWN)
    assert lead is None and any("consent_statement" in e for e in errors)


def test_unknown_provider_rejected():
    errors, lead = validate_lead(good_lead(recommended_provider_id="made-up-plumber"), KNOWN)
    assert lead is None
    assert any("recommended_provider_id" in e for e in errors)


def test_missing_consent_and_contact_rejected():
    data = good_lead()
    data["customer"] = {"name": "Maria", "consent_to_share": False}
    errors, _ = validate_lead(data, KNOWN)
    assert any("consent" in e for e in errors)
    assert any("phone number or email" in e for e in errors)


def test_bad_address_and_enums_rejected():
    data = good_lead()
    data["service_location"] = {"street_address": "my house", "city": "", "state": "", "zip": "787"}
    data["job"] = {**data["job"], "category": "magic", "urgency": "asap", "problem_summary": "leak"}
    errors, _ = validate_lead(data, KNOWN)
    joined = " ".join(errors)
    for field in ["street_address", "city", "state", "zip", "category", "urgency", "problem_summary"]:
        assert field in joined


def test_normalize_phone():
    assert normalize_phone("+1 (512) 555-0142") == "(512) 555-0142"
    assert normalize_phone("5125550142") == "(512) 555-0142"
    assert normalize_phone("555-0142") == ""
