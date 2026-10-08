"""Real local service-provider discovery.

Two backends, both returning real businesses only:
- GooglePlacesBackend: Google Places API (New) Text Search. Best coverage,
  ratings and open-now info. Requires GOOGLE_PLACES_API_KEY.
- OSMBackend: OpenStreetMap via Nominatim (geocoding) + Overpass (POI search).
  Free, no key, real community-mapped businesses, but sparser coverage.

Nothing here ever invents a provider: every result carries a source URL that
can be used to independently verify the business.
"""

import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import requests

from .categories import CATEGORIES, Category

USER_AGENT = "NearbyAI-HomeServiceAgent/0.1 (take-home demo)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
SEARCH_BUDGET_S = 75
GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"


@dataclass
class Location:
    query: str
    lat: float
    lon: float
    display_name: str
    city: str = ""
    state: str = ""
    postcode: str = ""


@dataclass
class Provider:
    provider_id: str
    name: str
    category: str
    source: str
    source_url: str
    phone: str = ""
    website: str = ""
    email: str = ""
    address: str = ""
    distance_km: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    open_now: Optional[bool] = None
    hours: str = ""
    match_reasons: list = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("score")
        return {k: v for k, v in d.items() if v not in (None, "", [])}


class ProviderSearchError(Exception):
    pass


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


_geocode_cache: dict = {}
_last_nominatim_call = 0.0


def geocode(query: str, session: Optional[requests.Session] = None) -> Location:
    """Resolve a ZIP / city / address to coordinates using Nominatim (US only)."""
    global _last_nominatim_call
    key = query.strip().lower()
    if key in _geocode_cache:
        return _geocode_cache[key]
    session = session or requests.Session()
    params = {"format": "jsonv2", "limit": 1, "countrycodes": "us", "addressdetails": 1}
    if re.fullmatch(r"\d{5}", query.strip()):
        params["postalcode"] = query.strip()
    else:
        params["q"] = query
    # Nominatim usage policy: max 1 request/second.
    wait = 1.0 - (time.time() - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.time()
    try:
        resp = session.get(NOMINATIM_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as e:
        raise ProviderSearchError(f"Geocoding failed: {e}") from e
    if not results:
        raise ProviderSearchError(f"Could not find location '{query}'. Ask for a ZIP code or city and state.")
    r = results[0]
    addr = r.get("address", {})
    loc = Location(
        query=query,
        lat=float(r["lat"]),
        lon=float(r["lon"]),
        display_name=r.get("display_name", query),
        city=addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet") or "",
        state=addr.get("state", ""),
        postcode=addr.get("postcode", ""),
    )
    _geocode_cache[key] = loc
    return loc


# --------------------------------------------------------------------------
# OpenStreetMap backend
# --------------------------------------------------------------------------

def build_overpass_query(category: Category, lat: float, lon: float, radius_m: int) -> str:
    # Fetch business-like objects in the radius once (spatial index first), then filter
    # that set by trade tag or name. Starting from a key or name filter instead makes
    # Overpass scan globally and time out.
    lines = [
        "[out:json][timeout:25];",
        f'nwr[~"^(craft|shop|office|company)$"~"."](around:{radius_m},{lat},{lon})->.biz;',
        "(",
    ]
    lines += [f'  nwr.biz["{k}"="{v}"];' for k, v in category.osm_tags]
    if category.name_regex:
        lines.append(f'  nwr.biz["name"~"{category.name_regex.replace(chr(34), "")}",i];')
    lines += [");", "out center tags 200;"]
    return "\n".join(lines)


def _osm_address(tags: dict) -> str:
    street = " ".join(x for x in [tags.get("addr:housenumber", ""), tags.get("addr:street", "")] if x)
    city_line = ", ".join(x for x in [tags.get("addr:city", ""), tags.get("addr:state", "")] if x)
    if tags.get("addr:postcode"):
        city_line = f"{city_line} {tags['addr:postcode']}".strip()
    return ", ".join(x for x in [street, city_line] if x)


NOT_A_SERVICE_RE = re.compile(r"suppl(y|ies)|distribut|wholesale|outlet|union|hall\b", re.I)
SERVICE_OFFICE_VALUES = {"company", "contractor", "construction_company", "tradesman", "yes"}
# Only shop types that are themselves a service. shop=trade/appliance/electrical are supply houses and
# appliance stores (e.g. "University Electric", an appliance showroom, matched "electric").
SERVICE_SHOP_VALUES = {"locksmith", "pest_control"}


def looks_like_service_business(tags: dict) -> bool:
    """A name-only match counts only if the object is tagged as a trade/contractor,
    which filters out e.g. "Electric Kitten Tattoo" (shop=tattoo) or a union hall."""
    if tags.get("craft"):
        return True
    if tags.get("office") in SERVICE_OFFICE_VALUES:
        return True
    if tags.get("shop") in SERVICE_SHOP_VALUES:
        return True
    return bool(tags.get("company")) and not tags.get("shop") and not tags.get("office")


def parse_osm_elements(elements: list, category: Category, origin: Location) -> list:
    providers, seen = [], set()
    tag_pairs = set(category.osm_tags)
    name_re = re.compile(category.name_regex, re.I) if category.name_regex else None
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        if tags.get("disused") or tags.get("abandoned") or any(k.startswith(("disused:", "was:")) for k in tags):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        dedupe = name.strip().lower()
        if dedupe in seen:
            continue
        seen.add(dedupe)
        reasons = []
        tag_match = any((k, tags.get(k)) in tag_pairs for k, _ in tag_pairs)
        name_match = bool(name_re and name_re.search(name))
        if NOT_A_SERVICE_RE.search(name):
            continue
        if not tag_match and not (name_match and looks_like_service_business(tags)):
            continue
        if tag_match:
            reasons.append(f"tagged as {category.label.lower()} on OpenStreetMap")
        if name_match:
            reasons.append("business name matches the service")
        p = Provider(
            provider_id=f"osm:{el['type']}/{el['id']}",
            name=name,
            category=category.key,
            source="openstreetmap",
            source_url=f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
            phone=tags.get("phone") or tags.get("contact:phone", ""),
            website=tags.get("website") or tags.get("contact:website", ""),
            email=tags.get("email") or tags.get("contact:email", ""),
            address=_osm_address(tags),
            distance_km=round(haversine_km(origin.lat, origin.lon, float(lat), float(lon)), 1),
            hours=tags.get("opening_hours", ""),
            match_reasons=reasons,
        )
        providers.append(p)
    return providers


class OSMBackend:
    name = "openstreetmap"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def _overpass(self, query: str, deadline: float) -> list:
        last_err = None
        for attempt, url in enumerate(OVERPASS_URLS * 2):
            if attempt:
                time.sleep(min(2 * attempt, 4))
            remaining = deadline - time.time()
            if remaining < 5:
                break
            try:
                resp = self.session.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT},
                                         timeout=min(30, remaining))
                resp.raise_for_status()
                data = resp.json()
                # A server-side timeout comes back as HTTP 200 with a "remark" and partial/empty results.
                if "runtime error" in data.get("remark", ""):
                    raise ValueError(data["remark"][:120])
                return data.get("elements", [])
            except (requests.RequestException, ValueError) as e:
                last_err = e
        raise ProviderSearchError(f"OpenStreetMap search is busy or unavailable right now ({last_err}).")

    def search(self, category: Category, origin: Location, keywords: str = "") -> list:
        # Hard cap on total wait so the chat never hangs for minutes.
        deadline = time.time() + SEARCH_BUDGET_S
        providers = []
        for radius in (10000, 30000):
            try:
                elements = self._overpass(build_overpass_query(category, origin.lat, origin.lon, radius), deadline)
            except ProviderSearchError:
                if providers:
                    break  # keep what the smaller radius found
                raise
            providers = parse_osm_elements(elements, category, origin)
            if len(providers) >= 3:
                break
        return providers


# --------------------------------------------------------------------------
# Google Places backend
# --------------------------------------------------------------------------

GOOGLE_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.location",
        "places.currentOpeningHours.openNow",
        "places.regularOpeningHours.weekdayDescriptions",
    ]
)


class GooglePlacesBackend:
    name = "google_places"

    def __init__(self, api_key: str, session: Optional[requests.Session] = None):
        self.api_key = api_key
        self.session = session or requests.Session()

    def search(self, category: Category, origin: Location, keywords: str = "") -> list:
        text = f"{keywords} {category.google_query}".strip() if keywords else category.google_query
        body = {
            "textQuery": f"{text} near {origin.display_name}",
            "maxResultCount": 15,
            "locationBias": {
                "circle": {"center": {"latitude": origin.lat, "longitude": origin.lon}, "radius": 30000.0}
            },
        }
        headers = {"X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": GOOGLE_FIELDS}
        try:
            resp = self.session.post(GOOGLE_TEXT_SEARCH_URL, json=body, headers=headers, timeout=20)
            resp.raise_for_status()
            places = resp.json().get("places", [])
        except (requests.RequestException, ValueError) as e:
            raise ProviderSearchError(f"Google Places search failed: {e}") from e
        providers = []
        for pl in places:
            if pl.get("businessStatus", "OPERATIONAL") != "OPERATIONAL":
                continue
            loc = pl.get("location", {})
            dist = None
            if "latitude" in loc:
                dist = round(haversine_km(origin.lat, origin.lon, loc["latitude"], loc["longitude"]), 1)
            hours = pl.get("regularOpeningHours", {}).get("weekdayDescriptions", [])
            providers.append(
                Provider(
                    provider_id=f"gplaces:{pl['id']}",
                    name=pl.get("displayName", {}).get("text", ""),
                    category=category.key,
                    source="google_places",
                    source_url=pl.get("googleMapsUri", ""),
                    phone=pl.get("nationalPhoneNumber", ""),
                    website=pl.get("websiteUri", ""),
                    address=pl.get("formattedAddress", ""),
                    distance_km=dist,
                    rating=pl.get("rating"),
                    review_count=pl.get("userRatingCount"),
                    open_now=pl.get("currentOpeningHours", {}).get("openNow"),
                    hours="; ".join(hours),
                    match_reasons=[f"Google Places result for '{text}'"],
                )
            )
        return providers


# --------------------------------------------------------------------------
# Ranking / matching
# --------------------------------------------------------------------------

EMERGENCY_RE = re.compile(r"24\s*/\s*7|24 hour|24hr|emergency", re.I)
# General builders often carry a trade tag on OSM but rarely take small trade jobs.
GENERALIST_RE = re.compile(r"\b(builders?|construction|contracting|development)\b", re.I)
GENERALIST_CATEGORIES = {"general_contractor", "handyman"}


def rank_providers(providers: list, urgency: str, keywords: str = "") -> list:
    """Score providers on contactability, proximity, reputation, availability and specialization."""
    kw = [w for w in re.findall(r"[a-z]{4,}", keywords.lower())]
    for p in providers:
        s = 0.0
        # A lead can only be dispatched to a business we can reach.
        if p.phone:
            s += 3
        if p.website:
            s += 1.5
        if p.email:
            s += 0.5
        if p.distance_km is not None:
            # Proximity matters more when someone needs to show up today.
            s += max(0.0, 4 - p.distance_km / 5) * (1.5 if urgency in ("emergency", "within_24h") else 1.0)
        if p.rating is not None and p.review_count:
            s += (p.rating - 3.5) * 2 + min(math.log10(p.review_count + 1), 3)
        if len(p.match_reasons) > 1:
            s += 1
        text = f"{p.name} {p.hours} {p.website}".lower()
        if urgency in ("emergency", "within_24h"):
            if p.hours.strip() == "24/7" or EMERGENCY_RE.search(p.name) or EMERGENCY_RE.search(p.hours):
                s += 1.5
                p.match_reasons.append("advertises 24/7 or emergency service")
            if p.open_now:
                s += 1.5
                p.match_reasons.append("open now")
        if p.category not in GENERALIST_CATEGORIES and GENERALIST_RE.search(p.name):
            s -= 3
        hits = [w for w in kw if w in text]
        if hits:
            s += 1
            p.match_reasons.append(f"specialization match: {', '.join(hits)}")
        p.score = s
    return sorted(providers, key=lambda p: p.score, reverse=True)


CACHE_DIR = Path(os.environ.get("NEARBY_CACHE_DIR", Path(__file__).resolve().parent.parent / ".cache"))
CACHE_TTL_S = 24 * 3600
# Cached entries hold parsed/filtered providers; bump when parsing or filtering rules change.
CACHE_VERSION = 2


def _cached_search(backend, category: Category, origin: Location, keywords: str) -> list:
    """Cache raw provider results on disk for a day (Overpass can take 30s+ per query)."""
    raw = f"v{CACHE_VERSION}|{backend.name}|{category.key}|{origin.lat:.3f}|{origin.lon:.3f}|{keywords.lower().strip()}"
    path = CACHE_DIR / f"{hashlib.sha1(raw.encode()).hexdigest()}.json"
    if path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_S:
        return [Provider(**d) for d in json.loads(path.read_text())]
    found = backend.search(category, origin, keywords)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(p) for p in found]))
    return found


def default_backend():
    key = os.environ.get("GOOGLE_PLACES_API_KEY")
    if key:
        return GooglePlacesBackend(key)
    return OSMBackend()


def search_providers(
    category_key: str, location: str, urgency: str = "flexible", keywords: str = "", backend=None, limit: int = 5
) -> dict:
    if category_key not in CATEGORIES:
        raise ProviderSearchError(f"Unknown category '{category_key}'. Valid: {', '.join(CATEGORIES)}")
    category = CATEGORIES[category_key]
    backend = backend or default_backend()
    origin = geocode(location)
    found = _cached_search(backend, category, origin, keywords)
    ranked = rank_providers(found, urgency, keywords)
    # A lead can't be dispatched to a business we can't phone, and phoneless OSM entries were
    # disproportionately mis-tagged (e.g. a test-chamber maker tagged craft=hvac).
    dispatchable = [p for p in ranked if p.phone]
    return {
        "resolved_location": {
            "display_name": origin.display_name,
            "city": origin.city,
            "state": origin.state,
            "postcode": origin.postcode,
        },
        "category": category.key,
        "data_source": backend.name,
        "total_found": len(found),
        "excluded_without_phone": len(ranked) - len(dispatchable),
        "providers": dispatchable[:limit],
    }
