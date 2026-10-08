"""Conversational home-service agent built on Claude tool use."""

import json
import os
from pathlib import Path
from typing import Optional

import anthropic

from .categories import CATEGORIES, URGENCY_LEVELS, category_catalog_text
from .leads import save_lead, validate_lead
from .providers import ProviderSearchError, search_providers

MODEL = os.environ.get("NEARBY_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("NEARBY_EFFORT", "medium")
MAX_TOOL_ROUNDS = 8
LEADS_DIR = Path(os.environ.get("NEARBY_LEADS_DIR", Path(__file__).resolve().parent.parent / "leads"))

SYSTEM_PROMPT = f"""You are Nearby, a home-services concierge. Homeowners describe a problem; you figure out what kind \
of pro they need, find real local businesses, and send the job to one of them as a lead. Your goal is a \
lead that a real provider would accept, without wasting the homeowner's time.

How a good conversation goes:
1. Understand the problem. Briefly acknowledge it. If anything is a safety hazard (gas smell, sparking or \
burning smell, standing water near outlets or the panel, sewage, structural collapse), tell them the immediate \
safe step first (leave and call 911 / the gas utility, shut off the main water valve, turn off the breaker if \
safe) and then keep helping.
2. Ask only the questions a technician would need to quote and show up: what's happening and where, how bad / \
how much, since when, what they've already tried, and how urgent it is. Ask at most two questions per message. \
Get the ZIP code (or city and state) early.
3. As soon as you know the category and the ZIP/city, call search_providers. Don't wait for every detail. \
Recommend the best 1-3 matches by name with a one-line reason each (distance, emergency availability, rating, \
specialization). Only mention businesses returned by the tool, and never alter their names or phone numbers. \
If a search returns nothing useful, try a closely related category or a nearby larger city before giving up.
4. Offer to send the request to your top pick so they call back; this is the main value you provide. Then \
collect: full name, best phone (and email if they want), the service street address with city/state/ZIP, \
when someone can come, whether they own or rent, and the property type. Ask for these in one or two short \
messages, not one at a time.
5. Consent: before calling create_lead you need a clear yes to a question that names the provider and says what \
you'll share (name, phone/email, address, job details). A "go ahead and send it" given before you told them that \
doesn't count; ask the direct yes/no question once you have their details. Put their exact words of agreement in \
customer.consent_statement. Then call create_lead. If it returns errors, ask the user for exactly what's missing.
6. After the lead is created, give the lead ID and the provider's name and phone. The lead is created and queued \
for the provider, but you can't see whether they've received it, so never say it was "sent" or "received". Say \
it's queued, suggest they also call directly if it's urgent, and stop there.

Prices: you have no pricing data, so don't quote prices, costs or price ranges, not even rough ones. If asked, \
say cost depends on what the technician finds and that the provider will quote; offer to note in the lead that \
they want the diagnostic/trip fee and a written quote before any work. You can still explain likely causes and \
what's typically involved.

Classify into exactly one of these categories (pick the trade that should show up first, e.g. active basement \
flooding is water_damage_restoration, a dripping faucet is plumbing):
{category_catalog_text()}

Urgency levels: emergency (active damage or safety risk now), within_24h, within_week, flexible.

Write the lead for the technician: problem_summary is 1-3 concrete sentences; details are short factual bullets \
from the conversation (location in the house, extent, duration, cause if known, what was tried, access notes, \
insurance). Don't invent facts the user didn't give you.

The only phone numbers, websites and business names you may give are ones returned by search_providers, plus \
911. For utilities or insurers, say "your electric utility" or "your insurer" instead of quoting a number.

Style: warm, plain, concise; this is a chat, not an email. Replies are shown in a plain-text terminal, so don't \
use markdown (no **bold**, no headers); simple "- " lists and numbered lists are fine. If the user won't share contact \
details, respect that, give them the provider phone numbers, and leave it there."""

TOOLS = [
    {
        "name": "search_providers",
        "description": (
            "Find real, currently listed local service businesses for a home-service category near a location. "
            "Returns ranked providers with provider_id, name, phone, website, address, distance and verification URL. "
            "Call this as soon as you know the category and the user's ZIP code or city/state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": list(CATEGORIES)},
                "location": {
                    "type": "string",
                    "description": "5-digit US ZIP code (preferred), or 'City, ST', or a street address.",
                },
                "urgency": {"type": "string", "enum": URGENCY_LEVELS},
                "specialization": {
                    "type": "string",
                    "description": "Optional keywords for the specific need, e.g. 'sump pump', 'tankless water heater'.",
                },
            },
            "required": ["category", "location", "urgency"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_lead",
        "description": (
            "Create a dispatchable lead and send it to the chosen provider. Only call after the user has confirmed "
            "consent to share their contact info. Returns the lead ID, or a list of problems to fix."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "customer": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                        "preferred_contact_method": {"type": "string", "enum": ["phone", "text", "email"]},
                        "consent_to_share": {"type": "boolean"},
                        "consent_statement": {
                            "type": "string",
                            "description": "The customer's own words agreeing to share their info with the named provider.",
                        },
                    },
                    "required": ["name", "consent_to_share", "consent_statement"],
                },
                "service_location": {
                    "type": "object",
                    "properties": {
                        "street_address": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "zip": {"type": "string"},
                        "property_type": {
                            "type": "string",
                            "enum": ["single_family", "townhouse", "condo", "apartment", "mobile_home", "commercial", "other"],
                        },
                        "ownership": {"type": "string", "enum": ["owner", "renter", "property_manager", "unknown"]},
                    },
                    "required": ["street_address", "city", "state", "zip"],
                },
                "job": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "urgency": {"type": "string", "enum": URGENCY_LEVELS},
                        "problem_summary": {"type": "string"},
                        "details": {"type": "array", "items": {"type": "string"}},
                        "availability": {"type": "string", "description": "When the customer can be home / wants service."},
                        "safety_notes": {"type": "string"},
                        "insurance_claim": {"type": "string", "description": "e.g. 'yes - filing with State Farm', 'no', 'unsure'"},
                    },
                    "required": ["category", "urgency", "problem_summary", "details"],
                },
                "recommended_provider_id": {"type": "string"},
                "backup_provider_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["customer", "service_location", "job", "recommended_provider_id"],
        },
    },
]

# Blocks that must not be echoed when they precede a mid-output fallback boundary.
_PRE_FALLBACK_DROP = {"thinking", "redacted_thinking", "tool_use", "server_tool_use"}


def _echoable_content(content: list) -> list:
    fallback_idx = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    if fallback_idx < 0:
        return list(content)
    return [b for i, b in enumerate(content) if i > fallback_idx or b.type not in _PRE_FALLBACK_DROP]


class HomeServiceAgent:
    def __init__(self, client=None, provider_backend=None, leads_dir: Optional[Path] = None, log=None, on_search=None):
        self.client = client or anthropic.Anthropic()
        self.provider_backend = provider_backend
        self.leads_dir = leads_dir or LEADS_DIR
        self.log = log or (lambda msg: None)
        self.on_search = on_search
        self.messages: list = []
        self.transcript: list = []
        self.known_providers: dict = {}
        self.lead: Optional[dict] = None
        self.lead_path: Optional[Path] = None

    # -- tools ---------------------------------------------------------------
    def _run_tool(self, name: str, args: dict) -> tuple:
        """Return (result_text, is_error)."""
        if name == "search_providers":
            if self.on_search:
                self.on_search(args)
            try:
                result = search_providers(
                    args["category"],
                    args["location"],
                    args.get("urgency", "flexible"),
                    args.get("specialization", ""),
                    backend=self.provider_backend,
                )
            except (ProviderSearchError, KeyError) as e:
                return str(e), True
            providers = [p.to_dict() for p in result["providers"]]
            for p in providers:
                self.known_providers[p["provider_id"]] = p
            result["providers"] = providers
            if not providers:
                result["note"] = "No providers found. Try a related category or a nearby larger city."
            self.log(f"[search_providers] {args} -> {len(providers)} providers via {result['data_source']}")
            return json.dumps(result), False

        if name == "create_lead":
            if self.lead:
                return json.dumps({"error": "A lead was already created", "lead_id": self.lead["lead_id"]}), True
            errors, lead = validate_lead(args, self.known_providers)
            if errors:
                self.log(f"[create_lead] rejected: {errors}")
                return json.dumps({"errors": errors}), True
            self.lead = lead
            self.lead_path = save_lead(lead, self.transcript, self.leads_dir)
            self.log(f"[create_lead] saved {self.lead_path}")
            return (
                json.dumps(
                    {
                        "lead_id": lead["lead_id"],
                        "status": lead["status"],
                        "provider": {k: lead["recommended_provider"].get(k) for k in ("name", "phone", "website")},
                        "quality_score": lead["quality"]["score"],
                    }
                ),
                False,
            )

        return f"Unknown tool {name}", True

    # -- conversation ----------------------------------------------------------
    def _call_model(self):
        return self.client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
            output_config={"effort": EFFORT},
            cache_control={"type": "ephemeral"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def send(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})
        self.transcript.append({"role": "user", "text": user_text})
        replies = []
        for _ in range(MAX_TOOL_ROUNDS):
            response = self._call_model()
            if response.stop_reason == "refusal":
                reply = "Sorry, I can't help with that request. If this is a home repair issue, could you describe it another way?"
                self.transcript.append({"role": "assistant", "text": reply})
                return reply

            content = _echoable_content(response.content)
            if response.stop_reason == "max_tokens":
                content = [b for b in content if b.type != "tool_use"]
            self.messages.append({"role": "assistant", "content": content})
            replies += [b.text for b in content if b.type == "text" and b.text.strip()]

            tool_uses = [b for b in content if b.type == "tool_use"]
            if not tool_uses:
                break
            results = []
            for tu in tool_uses:
                text, is_error = self._run_tool(tu.name, tu.input)
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": text, "is_error": is_error})
            self.messages.append({"role": "user", "content": results})

        reply = "\n\n".join(replies).strip() or "Sorry, something went wrong on my side. Could you repeat that?"
        self.transcript.append({"role": "assistant", "text": reply})
        if self.lead_path:
            # Keep the saved lead's transcript in sync with the full conversation.
            save_lead(self.lead, self.transcript, self.leads_dir)
        return reply
