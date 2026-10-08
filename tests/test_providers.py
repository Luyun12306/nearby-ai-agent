from nearby_agent.categories import CATEGORIES
from nearby_agent.providers import Location, build_overpass_query, parse_osm_elements, rank_providers

ORIGIN = Location("78704", 30.25, -97.76, "78704, Austin, TX")


def el(i, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": tags}


def test_overpass_query_contains_tags_and_name_filter():
    q = build_overpass_query(CATEGORIES["plumbing"], 30.25, -97.76, 10000)
    assert '"craft"="plumber"' in q
    assert "around:10000,30.25,-97.76" in q
    assert '"name"~"plumb' in q


def test_parse_filters_non_service_matches_and_dedupes():
    elements = [
        el(1, 30.26, -97.70, name="Economy Plumbing", craft="plumber", phone="+1-512-580-7829",
           **{"addr:housenumber": "701", "addr:street": "Tillery St", "addr:city": "Austin", "addr:postcode": "78702"}),
        el(2, 30.26, -97.70, name="Economy Plumbing", craft="plumber"),            # duplicate name
        el(3, 30.27, -97.75, name="Plumbing Supply Co", shop="trade"),             # supply house
        el(4, 30.27, -97.75, name="Drain Bar", shop="clothes"),                   # unrelated shop
        el(5, 30.30, -97.74, name="Rooter Pros", office="company", phone="512-555-0100"),
        el(6, 30.30, -97.74, name="Old Plumber", craft="plumber", disused="yes"),
        {"type": "way", "id": 7, "center": {"lat": 30.2, "lon": -97.8}, "tags": {"name": "Way Plumbing", "craft": "plumber"}},
    ]
    providers = parse_osm_elements(elements, CATEGORIES["plumbing"], ORIGIN)
    names = [p.name for p in providers]
    assert names == ["Economy Plumbing", "Rooter Pros", "Way Plumbing"]
    first = providers[0]
    assert first.provider_id == "osm:node/1"
    assert first.source_url == "https://www.openstreetmap.org/node/1"
    assert first.address == "701 Tillery St, Austin 78702"
    assert 5 < first.distance_km < 7


def test_rank_prefers_contactable_close_emergency_providers():
    elements = [
        el(1, 30.25, -97.76, name="Near No Phone Plumbing", craft="plumber"),
        el(2, 30.26, -97.75, name="Near Plumbing", craft="plumber", phone="512-555-0101", opening_hours="24/7"),
        el(3, 30.60, -97.40, name="Far Plumbing", craft="plumber", phone="512-555-0102"),
    ]
    ranked = rank_providers(parse_osm_elements(elements, CATEGORIES["plumbing"], ORIGIN), "emergency")
    assert ranked[0].name == "Near Plumbing"
    assert "advertises 24/7 or emergency service" in ranked[0].match_reasons


def test_search_providers_only_returns_providers_with_phone(monkeypatch):
    from nearby_agent import providers as prov

    class FakeBackend:
        name = "fake"

        def search(self, category, origin, keywords=""):
            return parse_osm_elements([
                el(1, 30.25, -97.76, name="No Phone HVAC", craft="hvac", website="https://example.com"),
                el(2, 30.26, -97.75, name="Phone HVAC", craft="hvac", phone="512-555-0101"),
            ], category, origin)

    monkeypatch.setattr(prov, "geocode", lambda q: ORIGIN)
    monkeypatch.setattr(prov, "CACHE_DIR", __import__("pathlib").Path(__import__("tempfile").mkdtemp()))
    r = prov.search_providers("hvac", "78704", "emergency", backend=FakeBackend())
    assert [p.name for p in r["providers"]] == ["Phone HVAC"]
    assert r["total_found"] == 2 and r["excluded_without_phone"] == 1


def test_generalist_builder_ranked_below_trade_specialist():
    elements = [
        el(1, 30.25, -97.76, name="South Side Builders", craft="plumber", phone="512-555-0101"),
        el(2, 30.30, -97.70, name="Ace Plumbing", craft="plumber", phone="512-555-0102"),
    ]
    ranked = rank_providers(parse_osm_elements(elements, CATEGORIES["plumbing"], ORIGIN), "within_24h")
    assert [p.name for p in ranked] == ["Ace Plumbing", "South Side Builders"]


def test_name_only_match_on_store_rejected():
    elements = [
        el(1, 30.25, -97.76, name="University Electric", shop="appliance", phone="512-555-0101"),
        el(2, 30.25, -97.76, name="Bright Electric", office="company", phone="512-555-0102"),
    ]
    names = [p.name for p in parse_osm_elements(elements, CATEGORIES["electrical"], ORIGIN)]
    assert names == ["Bright Electric"]
