from nearby_agent import offline as offline_mod
from nearby_agent.offline import OfflineAgent, classify, extract_location, extract_name, parse_address
from nearby_agent.providers import Provider


def fake_search(category_key, location, urgency="flexible", keywords="", backend=None, limit=5):
    return {
        "resolved_location": {"display_name": "78704, Austin, TX", "city": "Austin", "state": "Texas", "postcode": "78704"},
        "category": category_key, "data_source": "fake", "total_found": 2,
        "providers": [
            Provider("osm:node/1", "Total Restoration of Texas", category_key, "openstreetmap",
                     "https://www.openstreetmap.org/node/1", phone="+1-512-698-8444", distance_km=3.2),
            Provider("osm:node/2", "Austin Flood & Leak Restoration", category_key, "openstreetmap",
                     "https://www.openstreetmap.org/node/2", phone="+1 512-271-5099", distance_km=10.9),
        ],
    }


def test_helpers():
    assert classify("Water started coming into my basement last night after the storm")[0] == "water_damage_restoration"
    assert classify("my furnace stopped working and it's freezing")[0] == "hvac"
    assert classify("kitchen sink totally clogged")[0] == "plumbing"
    assert extract_location("I'm in 78704") == "78704"
    assert extract_location("near Chicago, IL") == "Chicago, IL"
    assert extract_name("Maria Lopez, 512-555-0142") == "Maria Lopez"
    assert extract_name("my name is dave k, call 773 555 0199") == "Dave K"
    a = parse_address("1402 Bluebonnet Ln, Austin, TX 78704", {})
    assert a == {"street_address": "1402 Bluebonnet Ln", "city": "Austin", "state": "TX", "zip": "78704"}
    assert parse_address("1402 Bluebonnet Ln", {"city": "Austin", "state": "Texas", "postcode": "78704"})["zip"] == "78704"


def test_offline_full_flow(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_mod, "search_providers", fake_search)
    a = OfflineAgent(leads_dir=tmp_path)
    r = a.send("Water started coming into my basement last night after the storm. I don't know who to call.")
    assert "outlets" in r and "ZIP" in r
    assert "How much water" in a.send("78704")
    r = a.send("About 2 inches across the basement, carpet soaked, still seeping in along the north wall")
    assert "Total Restoration of Texas" in r and "send your request" in r
    assert "name" in a.send("yes please")
    assert "street address" in a.send("Maria Lopez 512-555-0142")
    assert "When can someone" in a.send("1402 Bluebonnet Ln")
    assert "own or rent" in a.send("home all day today")
    r = a.send("I own it")
    assert "OK to share" in r and "1402 Bluebonnet Ln, Austin, Texas 78704" in r
    r = a.send("yes")
    assert r.startswith("Done!") and a.lead
    lead = a.lead
    assert lead["job"]["category"] == "water_damage_restoration"
    assert lead["job"]["urgency"] == "emergency"
    assert lead["customer"]["phone"] == "(512) 555-0142"
    assert lead["recommended_provider"]["name"] == "Total Restoration of Texas"
    assert lead["backup_providers"][0]["name"] == "Austin Flood & Leak Restoration"
    assert a.lead_path.exists()


def test_offline_decline_gives_numbers(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_mod, "search_providers", fake_search)
    a = OfflineAgent(leads_dir=tmp_path)
    a.send("my roof is leaking, 78704")
    a.send("over the bedroom since the storm, it's urgent today")
    r = a.send("no thanks")
    assert "+1-512-698-8444" in r and a.lead is None


def test_offline_asks_category_when_unclear(monkeypatch, tmp_path):
    monkeypatch.setattr(offline_mod, "search_providers", fake_search)
    a = OfflineAgent(leads_dir=tmp_path)
    r = a.send("something is wrong in my house")
    assert "Which of these best fits" in r
    assert "ZIP" in a.send("2")
