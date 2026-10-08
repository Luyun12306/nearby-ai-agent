"""Offline demo agent: no LLM, no API key.

A rule-based slot-filling conversation (keyword classification + regex parsing)
that drives the same real provider search and lead validation as the Claude agent.
It's rigid by design; it exists so the end-to-end flow can be demonstrated without
an Anthropic key.
"""

import re
from pathlib import Path
from typing import Optional

from .agent import LEADS_DIR
from .categories import CATEGORIES
from .leads import save_lead, validate_lead
from .providers import ProviderSearchError, search_providers

# Keyword -> category scoring. Longer, more specific phrases score higher.
KEYWORDS = {
    "water_damage_restoration": ["flood", "flooding", "water coming in", "water in my basement", "water in the basement",
                                 "standing water", "water damage", "soaked", "storm", "basement is wet"],
    "basement_waterproofing": ["seepage", "sump pump", "waterproof", "foundation crack", "damp basement"],
    "plumbing": ["leak", "leaking", "pipe", "clog", "clogged", "drain", "toilet", "faucet", "water heater",
                 "sewer", "sink", "no hot water", "shower"],
    "electrical": ["outlet", "spark", "breaker", "electrical", "wiring", "power out", "no power", "light switch", "panel"],
    "hvac": ["furnace", "heat", "heating", "ac ", "a/c", "air condition", "hvac", "thermostat", "boiler", "heat pump",
             "freezing", "cold air"],
    "roofing": ["roof", "shingle", "ceiling stain", "gutter", "stain on my ceiling", "stain spreading"],
    "mold_remediation": ["mold", "mould", "musty"],
    "appliance_repair": ["washer", "dryer", "fridge", "refrigerator", "dishwasher", "oven", "stove", "appliance"],
    "pest_control": ["mice", "mouse", "rat", "roach", "termite", "ants", "bed bug", "pest", "wasp", "raccoon"],
    "locksmith": ["locked out", "lock", "key"],
    "garage_door": ["garage door", "garage opener"],
    "tree_service": ["tree", "branch", "stump"],
    "landscaping": ["lawn", "landscap", "sprinkler", "irrigation", "yard"],
    "septic": ["septic"],
    "cleaning": ["cleaning", "clean my", "maid", "deep clean"],
    "painting": ["paint"],
    "handyman": ["handyman", "drywall", "door won't", "hang", "assemble", "install a"],
    "general_contractor": ["remodel", "renovation", "addition", "contractor"],
}

EMERGENCY_WORDS = ["flood", "burst", "spark", "smoke", "gas", "no heat", "freezing", "sewage", "locked out",
                   "right now", "emergency", "pouring", "coming in", "tonight", "last night"]
HAZARD_WORDS = {
    "gas": "If you smell gas, leave the house now and call your gas utility or 911 from outside.",
    "spark": "Please keep away from that outlet and switch off its breaker if you can do so safely.",
    "smoke": "If there's smoke or a burning smell, leave and call 911.",
    "flood": "If water is near outlets or the electrical panel, stay out of the water and don't touch anything electrical.",
    "coming in": "If water is near outlets or the electrical panel, stay out of the water and don't touch anything electrical.",
    "burst": "Shut off the main water valve if you can find it.",
}

CLARIFYING_QUESTION = {
    "water_damage_restoration": "How much water is there, which areas are wet (carpet, drywall, furniture), and is it still coming in?",
    "basement_waterproofing": "Where is the water getting in, and how often does it happen?",
    "plumbing": "Where exactly is the problem, how long has it been going on, and have you tried anything yet?",
    "electrical": "Which rooms or outlets are affected, and does the breaker trip again when you reset it?",
    "hvac": "What kind of system is it (gas furnace, heat pump, central AC) and what is it doing right now?",
    "roofing": "Where is the leak or damage, and did it start after a storm?",
    "mold_remediation": "Where is the mold and roughly how large an area?",
    "appliance_repair": "Which appliance (brand if you know it) and what is it doing wrong?",
    "pest_control": "What pest are you seeing, where, and for how long?",
    "locksmith": "Are you locked out right now, or is this a lock repair or rekey?",
    "garage_door": "Is the door stuck open or closed, and did you hear a loud bang (broken spring)?",
    "tree_service": "Is the tree down or just at risk, and is it on or near the house, car or power lines?",
}
DEFAULT_QUESTION = "Can you tell me a bit more: where is the problem, how big is it, and when did it start?"

YES_RE = re.compile(r"\b(yes|yeah|yep|yup|sure|ok|okay|please|go ahead|do it|send|sounds good|that works|fine|agree)\b", re.I)
NO_RE = re.compile(r"\b(no|nope|nah|don't|do not|not now|not yet|rather not)\b", re.I)
PHONE_RE = re.compile(r"(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
CITY_STATE_RE = re.compile(r"\b([A-Z][a-zA-Z .'-]+),\s*([A-Z]{2})\b")
STREET_RE = re.compile(r"\b\d+[A-Za-z]?\s+[A-Za-z0-9 .'#-]+?(?=,|$|\s+in\s)", re.M)

URGENCY_CHOICES = {
    "1": "emergency", "2": "within_24h", "3": "within_week", "4": "flexible",
}


def classify(text: str) -> list:
    """Return categories ranked by keyword score (best first)."""
    t = f" {text.lower()} "
    scores = {}
    for cat, words in KEYWORDS.items():
        s = sum(len(w) for w in words if w in t)
        if s:
            scores[cat] = s
    return sorted(scores, key=scores.get, reverse=True)


def detect_urgency(text: str) -> Optional[str]:
    t = text.lower()
    if any(w in t for w in EMERGENCY_WORDS):
        return "emergency"
    if re.search(r"\b(today|asap|tomorrow|urgent)\b", t):
        return "within_24h"
    if re.search(r"\b(this week|few days|soon)\b", t):
        return "within_week"
    if re.search(r"\b(no rush|whenever|flexible|next month|not urgent)\b", t):
        return "flexible"
    return None


def extract_location(text: str) -> Optional[str]:
    m = ZIP_RE.search(text)
    if m:
        return m.group(1)
    m = CITY_STATE_RE.search(text)
    if m:
        return f"{m.group(1).strip()}, {m.group(2)}"
    return None


def extract_name(text: str) -> str:
    t = PHONE_RE.sub(" ", EMAIL_RE.sub(" ", text))
    m = re.search(r"(?:my name is|name's|i'm|i am|this is|it's)\s+([A-Za-z][A-Za-z'.-]*(?:\s+[A-Za-z][A-Za-z'.-]*){0,2})", t, re.I)
    if m:
        return m.group(1).strip().title()
    words = [w for w in re.split(r"[,;\s]+", t) if w]
    if 1 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z'-]+", w) for w in words):
        return " ".join(words).title()
    first = re.split(r"[,;]", t)[0].strip()
    if 1 <= len(first.split()) <= 3 and re.fullmatch(r"[A-Za-z' -]+", first):
        return first.title()
    return ""


def parse_address(text: str, fallback: dict) -> dict:
    out = {"street_address": "", "city": fallback.get("city", ""), "state": fallback.get("state", ""),
           "zip": fallback.get("postcode", "")}
    m = STREET_RE.search(text)
    if m:
        out["street_address"] = m.group(0).strip()
    z = ZIP_RE.findall(text)
    if z:
        out["zip"] = z[-1]
    cs = CITY_STATE_RE.search(text)
    if cs:
        out["city"], out["state"] = cs.group(1).strip(), cs.group(2)
        # "1402 Bluebonnet Ln, Austin, TX" -> the city match can swallow the street; keep the last comma part.
        out["city"] = out["city"].split(",")[-1].strip()
    return out


class OfflineAgent:
    """Same public surface as HomeServiceAgent: send(), lead, lead_path, transcript, known_providers."""

    def __init__(self, provider_backend=None, leads_dir: Optional[Path] = None, log=None, on_search=None):
        self.provider_backend = provider_backend
        self.leads_dir = leads_dir or LEADS_DIR
        self.log = log or (lambda msg: None)
        self.on_search = on_search
        self.transcript: list = []
        self.known_providers: dict = {}
        self.lead: Optional[dict] = None
        self.lead_path: Optional[Path] = None

        self.problem = ""
        self.category: Optional[str] = None
        self.category_options: list = []
        self.location: Optional[str] = None
        self.resolved: dict = {}
        self.urgency: Optional[str] = None
        self.details: list = []
        self.asked_detail = False
        self.providers: list = []
        self.chosen: Optional[str] = None
        self.customer = {"name": "", "phone": "", "email": ""}
        self.address: dict = {}
        self.availability = ""
        self.ownership = ""
        self.declined = False
        self.awaiting: Optional[str] = None

    # -- public ----------------------------------------------------------------
    def send(self, user_text: str) -> str:
        self.transcript.append({"role": "user", "text": user_text})
        reply = self._handle(user_text.strip())
        self.transcript.append({"role": "assistant", "text": reply})
        if self.lead_path:
            save_lead(self.lead, self.transcript, self.leads_dir)
        return reply

    # -- slot handling -----------------------------------------------------------
    def _handle(self, text: str) -> str:
        if self.lead:
            return f"Your request {self.lead['lead_id']} has already been sent. Anything else I can help with?"
        prefix = ""
        if not self.problem:
            self.problem = text
            prefix = self._hazard_note(text)
            ranked = classify(text)
            if ranked:
                self.category = ranked[0]
            self.urgency = detect_urgency(text)
            self.location = extract_location(text)
        else:
            prefix = self._absorb(text)
            if self.lead:
                return prefix
        return (prefix + " " + self._next()).strip()

    def _hazard_note(self, text: str) -> str:
        t = text.lower()
        for word, note in HAZARD_WORDS.items():
            if word in t:
                return "Sorry you're dealing with that. " + note
        return "Sorry you're dealing with that, let's get it sorted."

    def _absorb(self, text: str) -> str:
        """Interpret the user's reply to whatever we last asked."""
        a = self.awaiting
        if a == "category":
            if text.isdigit() and 1 <= int(text) <= len(self.category_options):
                self.category = self.category_options[int(text) - 1]
            else:
                ranked = classify(text)
                key = text.strip().lower().replace(" ", "_")
                self.category = key if key in CATEGORIES else (ranked[0] if ranked else None)
            self.problem += " " + text
        elif a == "location":
            self.location = extract_location(text) or text.strip()
        elif a == "detail":
            self.details.append(text)
            self.urgency = self.urgency or detect_urgency(text)
            self.asked_detail = True
        elif a == "urgency":
            self.urgency = URGENCY_CHOICES.get(text.strip()) or detect_urgency(text) or "flexible"
        elif a == "offer":
            if text.strip() in {"1", "2", "3"} and int(text) <= len(self.providers):
                self.chosen = self.providers[int(text) - 1]["provider_id"]
            elif YES_RE.search(text) and not NO_RE.search(text):
                self.chosen = self.providers[0]["provider_id"]
            else:
                self.declined = True
        elif a == "contact":
            phone = PHONE_RE.search(text)
            email = EMAIL_RE.search(text)
            if phone:
                self.customer["phone"] = phone.group(0)
            if email:
                self.customer["email"] = email.group(0)
            self.customer["name"] = extract_name(text) or self.customer["name"]
        elif a == "address":
            self.address = parse_address(text, self.resolved)
        elif a == "availability":
            self.availability = text
            t = text.lower()
            if "rent" in t:
                self.ownership = "renter"
            elif "own" in t:
                self.ownership = "owner"
        elif a == "ownership":
            t = text.lower()
            self.ownership = "renter" if "rent" in t else "owner" if "own" in t else "unknown"
        elif a == "consent":
            if YES_RE.search(text) and not NO_RE.search(text):
                return self._create_lead(consent_statement=text)
            self.declined = True
        return ""

    def _next(self) -> str:
        if self.declined:
            self.awaiting = None
            lines = [f"No problem. You can reach them directly:"]
            lines += [f"  - {p['name']}: {p.get('phone') or p.get('website', '')}" for p in self.providers[:3]]
            return "\n".join(lines) + "\nIf you change your mind, just say so."

        if not self.category:
            self.category_options = classify(self.problem)[:4] or ["plumbing", "electrical", "hvac", "roofing"]
            self.awaiting = "category"
            opts = "\n".join(f"  {i}. {CATEGORIES[c].label}" for i, c in enumerate(self.category_options, 1))
            return f"Which of these best fits? Reply with a number, or describe it differently.\n{opts}"

        if not self.location:
            self.awaiting = "location"
            return "What's your ZIP code (or city and state)?"

        if not self.asked_detail:
            self.awaiting = "detail"
            return CLARIFYING_QUESTION.get(self.category, DEFAULT_QUESTION)

        if not self.urgency:
            self.awaiting = "urgency"
            return ("How soon do you need someone?\n  1. Emergency, right now\n  2. Within 24 hours\n"
                    "  3. This week\n  4. Flexible")

        if not self.providers:
            return self._search()

        if not self.chosen:
            self.awaiting = "offer"
            return ""  # _search already asked; only reached on an unparseable answer

        if not (self.customer["name"] and (self.customer["phone"] or self.customer["email"])):
            self.awaiting = "contact"
            missing = "your name and best phone number" if not self.customer["name"] else "a phone number or email"
            return f"Great. What's {missing}?"

        if not self.address.get("street_address"):
            self.awaiting = "address"
            return "What's the street address where the work is needed?"

        if not self.availability:
            self.awaiting = "availability"
            return "When can someone come by (e.g. 'today after 3pm', 'weekday mornings')?"

        if not self.ownership:
            self.awaiting = "ownership"
            return "Do you own or rent the home?"

        self.awaiting = "consent"
        p = self.known_providers[self.chosen]
        a = self.address
        return (f"Here's what I'll send to {p['name']}:\n"
                f"  {self.customer['name']}, {self.customer['phone'] or self.customer['email']}\n"
                f"  {a['street_address']}, {a['city']}, {a['state']} {a['zip']}\n"
                f"  {CATEGORIES[self.category].label} ({self.urgency.replace('_', ' ')}): {self._summary()}\n"
                f"Is it OK to share your contact info with them so they can call you back? (yes/no)")

    def _search(self) -> str:
        if self.on_search:
            self.on_search({"category": self.category, "location": self.location})
        try:
            result = search_providers(self.category, self.location, self.urgency, " ".join(self.details),
                                      backend=self.provider_backend)
        except ProviderSearchError as e:
            self.location = None
            self.awaiting = "location"
            return f"I couldn't search that area ({e}). Could you give me a 5-digit ZIP code?"
        self.resolved = result["resolved_location"]
        self.providers = [p.to_dict() for p in result["providers"]]
        self.log(f"[search_providers] {self.category} @ {self.location} -> {len(self.providers)} via {result['data_source']}")
        if not self.providers:
            self.declined = True
            return (f"I couldn't find {CATEGORIES[self.category].label.lower()} providers listed near "
                    f"{self.resolved.get('display_name', self.location)}. Try a nearby larger city's ZIP code.")
        for p in self.providers:
            self.known_providers[p["provider_id"]] = p
        lines = [f"Here are {CATEGORIES[self.category].label.lower()} pros near {self.resolved.get('city') or self.location}:"]
        for i, p in enumerate(self.providers[:3], 1):
            bits = [p.get("phone") or p.get("website", "")]
            if p.get("distance_km") is not None:
                bits.append(f"{p['distance_km']} km away")
            if p.get("rating"):
                bits.append(f"{p['rating']}★ ({p.get('review_count', 0)} reviews)")
            if any("24/7" in r for r in p.get("match_reasons", [])):
                bits.append("24/7")
            lines.append(f"  {i}. {p['name']} - {', '.join(b for b in bits if b)}")
        lines.append(f"Want me to send your request to {self.providers[0]['name']} so they call you back? "
                     f"(yes / pick 1-3 / no)")
        self.awaiting = "offer"
        return "\n".join(lines)

    def _summary(self) -> str:
        text = " ".join([self.problem] + self.details).strip()
        return text if len(text) >= 30 else f"{text} (customer requested {CATEGORIES[self.category].label.lower()})"

    def _create_lead(self, consent_statement: str) -> str:
        backups = [p["provider_id"] for p in self.providers[:3] if p["provider_id"] != self.chosen][:2]
        data = {
            "customer": {**self.customer, "preferred_contact_method": "phone" if self.customer["phone"] else "email",
                         "consent_to_share": True, "consent_statement": consent_statement},
            "service_location": {**self.address, "ownership": self.ownership, "property_type": ""},
            "job": {
                "category": self.category,
                "urgency": self.urgency,
                "problem_summary": self._summary(),
                "details": [self.problem] + self.details,
                "availability": self.availability,
            },
            "recommended_provider_id": self.chosen,
            "backup_provider_ids": backups,
        }
        errors, lead = validate_lead(data, self.known_providers)
        if errors:
            self.log(f"[create_lead] rejected: {errors}")
            # Re-ask for whatever failed validation.
            joined = " ".join(errors)
            if "phone" in joined or "email" in joined or "name" in joined:
                self.customer = {"name": "", "phone": "", "email": ""}
            if "service_location" in joined:
                self.address = {}
            return "Some details didn't check out (" + "; ".join(e.split(" - ")[0] for e in errors) + ")."
        self.lead = lead
        self.lead_path = save_lead(lead, self.transcript, self.leads_dir)
        self.awaiting = None
        p = lead["recommended_provider"]
        self.log(f"[create_lead] saved {self.lead_path}")
        return (f"Done! Your request {lead['lead_id']} is queued for {p['name']}, who will be asked to reach you at "
                f"{lead['customer']['phone'] or lead['customer']['email']}. "
                f"If it's urgent, you can also call them directly at {p.get('phone') or p.get('website', '')}.")
