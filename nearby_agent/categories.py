"""Home-service category taxonomy.

Each category maps to:
- a Google Places text query,
- OpenStreetMap tag filters (key, value) that directly identify the trade,
- a case-insensitive name regex used as a secondary OSM signal (many trades
  have no dedicated OSM tag, e.g. water-damage restoration).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    description: str
    google_query: str
    osm_tags: tuple = field(default_factory=tuple)
    name_regex: str = ""


CATEGORIES = {
    c.key: c
    for c in [
        Category(
            "water_damage_restoration",
            "Water Damage Restoration",
            "Active flooding, water intrusion after storms, burst pipes that already soaked floors/walls, water extraction and drying.",
            "water damage restoration",
            (),
            "restoration|water damage|servpro|servicemaster|puroclean|paul davis|belfor|rainbow international|flood",
        ),
        Category(
            "basement_waterproofing",
            "Basement Waterproofing & Foundation",
            "Recurring basement seepage, sump pumps, foundation cracks, grading/drainage fixes (non-emergency, after water is removed).",
            "basement waterproofing foundation repair",
            (),
            "waterproof|basement|foundation|sump",
        ),
        Category(
            "plumbing",
            "Plumbing",
            "Leaks, burst/frozen pipes, clogged drains, sewer backups, water heaters, toilets, faucets, gas lines.",
            "plumber",
            (("craft", "plumber"),),
            "plumb|rooter|drain|sewer",
        ),
        Category(
            "electrical",
            "Electrical",
            "Outages in part of the house, sparking outlets, breaker trips, panel upgrades, wiring, EV chargers.",
            "electrician",
            (("craft", "electrician"),),
            "electric",
        ),
        Category(
            "hvac",
            "Heating & Air Conditioning",
            "No heat, no AC, furnace/boiler/heat pump problems, thermostats, ductwork.",
            "HVAC heating and air conditioning repair",
            (("craft", "hvac"),),
            "hvac|heating|cooling|air condition|furnace|mechanical|comfort",
        ),
        Category(
            "roofing",
            "Roofing",
            "Roof leaks, storm/hail/wind damage, missing shingles, gutters.",
            "roofing contractor",
            (("craft", "roofer"),),
            "roof|gutter",
        ),
        Category(
            "mold_remediation",
            "Mold Remediation",
            "Visible mold, musty smell after water damage, mold testing and removal.",
            "mold remediation",
            (),
            "mold|mould|remediation",
        ),
        Category(
            "appliance_repair",
            "Appliance Repair",
            "Broken washer, dryer, refrigerator, dishwasher, oven/range.",
            "appliance repair",
            (("craft", "appliance_repair"), ("shop", "appliance")),
            "appliance",
        ),
        Category(
            "pest_control",
            "Pest Control",
            "Insects, rodents, termites, bed bugs, wildlife removal.",
            "pest control",
            (("shop", "pest_control"), ("craft", "pest_control")),
            "pest|exterminat|termite|bug",
        ),
        Category(
            "locksmith",
            "Locksmith",
            "Locked out, broken locks, rekeying, lock installation.",
            "locksmith",
            (("craft", "locksmith"), ("shop", "locksmith")),
            "locksmith|lock & key|lock and key",
        ),
        Category(
            "garage_door",
            "Garage Door Repair",
            "Garage door stuck, broken spring, opener failure.",
            "garage door repair",
            (),
            "garage door|overhead door",
        ),
        Category(
            "tree_service",
            "Tree Service",
            "Fallen or dangerous trees, storm debris, trimming, stump removal.",
            "tree service",
            (("craft", "arborist"),),
            "tree|arbor",
        ),
        Category(
            "landscaping",
            "Landscaping & Lawn Care",
            "Lawn care, landscaping, yard drainage, irrigation/sprinklers.",
            "landscaping lawn care",
            (("craft", "gardener"),),
            "landscap|lawn|irrigation|sprinkler",
        ),
        Category(
            "septic",
            "Septic Services",
            "Septic tank pumping, backups on septic systems, drain field problems.",
            "septic service",
            (),
            "septic",
        ),
        Category(
            "cleaning",
            "House Cleaning",
            "Regular or deep cleaning, move-out cleaning, post-construction cleaning.",
            "house cleaning service",
            (("craft", "cleaning"),),
            "cleaning|maid",
        ),
        Category(
            "painting",
            "Painting",
            "Interior/exterior painting, drywall touch-up after repairs.",
            "house painter",
            (("craft", "painter"),),
            "paint",
        ),
        Category(
            "handyman",
            "Handyman",
            "Small repairs and installs: drywall patches, doors, fixtures, furniture assembly.",
            "handyman",
            (("craft", "handyman"), ("craft", "carpenter")),
            "handyman|handy man|carpent",
        ),
        Category(
            "general_contractor",
            "General Contractor / Remodeling",
            "Remodels, additions, major structural repair, multi-trade projects.",
            "general contractor remodeling",
            (("craft", "builder"), ("office", "construction_company")),
            "construction|contracting|remodel|builders",
        ),
    ]
}

URGENCY_LEVELS = ["emergency", "within_24h", "within_week", "flexible"]


def category_catalog_text() -> str:
    """Compact category list for the system prompt."""
    return "\n".join(f"- {c.key}: {c.description}" for c in CATEGORIES.values())
