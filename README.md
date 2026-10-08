# Nearby AI — Home Service Provider Agent (solution)

The assignment brief is in `ASSIGNMENT.md`. This file covers what was built and how to run it.

**Time spent:** about 3 hours, built with Claude Code. Most of the time went into testing with real provider data,
running the evaluation, and verifying providers.

A conversational agent (Claude `claude-opus-5-5` with tool use) that turns a homeowner's description of a problem
into a validated, dispatchable lead addressed to a **real** local business.

```
user ──► HomeServiceAgent (Claude, multi-turn, tool use)
            ├─ search_providers ──► geocode (Nominatim) ──► Google Places API  (if GOOGLE_PLACES_API_KEY)
            │                                          └─► OpenStreetMap Overpass (free fallback)
            │                       ──► rank (contactable, distance, 24/7, rating, specialization)
            └─ create_lead ──► validate (contact, address, consent, real provider_id) ──► score ──► leads/*.json
```

## Setup

```bash
/opt/homebrew/bin/python3.14 -m venv .venv      # any Python >= 3.10
source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export GOOGLE_PLACES_API_KEY=...                 # optional; better coverage, ratings, open-now
```

## Run

```bash
python -m nearby_agent -v                 # interactive chat; -v shows tool calls
python -m nearby_agent --backend osm      # force OpenStreetMap
python -m evals.simulate -v               # simulated homeowners -> conversion rate & lead quality
python -m pytest -q                       # offline tests (no API keys needed)
```

In the chat, `/lead` prints the current lead JSON and `/quit` exits. Leads are written to `leads/<lead_id>.json`
with the full transcript.

Env knobs: `NEARBY_MODEL` (default `claude-opus-5-5`), `NEARBY_EFFORT` (default `medium`), `SIM_MODEL`,
`NEARBY_LEADS_DIR`, `NEARBY_CACHE_DIR`.

## How the requirements are met

| Requirement | Implementation |
|---|---|
| Natural multi-turn conversation | `agent.py`: full message history (including thinking blocks) resent each turn; system prompt caps questions to two per message and asks for the ZIP code early |
| Clarifying questions | Prompt lists what a technician needs (what, where, extent, since when, what was tried, urgency); safety guidance first for gas, electrical, or sewage hazards |
| Service classification | 18-category taxonomy (`categories.py`), enforced as an enum in both tools |
| Real local providers | `providers.py`: Google Places (New) Text Search, or OpenStreetMap via Nominatim and Overpass. Every provider has a `source_url` (Google Maps / osm.org) for verification. Closed and disused businesses are dropped, and name-only matches must also be tagged as a trade or contractor (filters out e.g. "Electric Kitten Tattoo" and supply houses) |
| Provider matching | `rank_providers`: contactability (phone > website > email), distance (weighted 1.5x when urgent), 24/7 or emergency signals and open-now for urgent jobs, rating × review volume, specialization keywords |
| No fabricated providers | `create_lead` only accepts a `recommended_provider_id` returned by `search_providers` in this conversation. Otherwise it returns an error, and the model has to use a real result |
| Dispatchable lead | `leads.validate_lead`: name, valid US phone or email, street address with number, city/state/ZIP, category, urgency, a concrete problem summary, **explicit consent to share**, and a real provider. Errors are written as instructions the agent passes back as questions |
| Lead quality | `score_lead` (0–100): core fields plus enrichment providers care about (3+ job details, availability window, property type, owner/renter, phone and email, backup provider). Missing items are listed |
| Conversion | Prompt pushes for an early provider search (show value first), then a direct offer to send the request, collecting contact info in one or two messages. Measured by `evals/simulate.py` |

Reliability details: refusals are handled (`stop_reason == "refusal"`), server-side model fallback is enabled
(`fallbacks: "default"`), the tool loop is capped at 8 rounds per user turn, Overpass has mirror failover with
backoff, and search results are cached on disk for 24h (`.cache/`).

## Example conversations (from the latest 94087 eval run)

The homeowner side is Claude playing a scripted persona (fictional name, address and 555 phone number). The agent side,
the provider search and the lead are real output. Both come from `evals/results.json`.

### 1. README scenario: storm water in the basement (4 homeowner messages, lead quality 100)

**Homeowner:**
> Water started coming into my basement last night after the storm. I don't know who to call.

**Agent:**
> I'm sorry, that's stressful. For water coming in after a storm, a water damage restoration company is usually the right first call. They can pump out the water and dry things out, and they act fast to prevent mold.
> 
> One safety note first: if the water is near outlets, cords, appliances, or your electrical panel, stay out of the water. Only turn off power to the basement at the breaker if you can reach the panel without standing in water. If you can't, leave the power on and stay out of the basement.
> 
> Two quick questions so I can find someone near you:
> 1. What's your ZIP code?
> 2. About how deep is the water, and is it still coming in?

**Homeowner:**
> It's 94087. Maybe 2 inches across the floor, coming in along the back wall, and the outlets aren't underwater, thankfully.

**Agent:**
> Good that the outlets are dry. Here are the best matches near Sunnyvale:
> 
> 1. Clearway Restoration: 5.8 km away in Santa Clara, open 24/7. This is my top pick. Phone: +1-408-457-0826
> 2. Reactic Restoration: 11.4 km away in San Jose, also open 24/7. Phone: +1-408-998-4840
> 3. Servpro: 6.6 km away in Sunnyvale. I don't have their hours listed. Phone: +1 650-770-2992
> 
> While you wait, take photos and video of the water and anything that got wet, in case you file an insurance claim.
> 
> I can send your request to Clearway Restoration so they call you back. If you'd like that, please send me:
> - Your full name and best phone number (and email if you want)
> - The street address
> - When someone can come (as soon as possible, or a time window)
> - Whether you own or rent, and the type of home (house, townhouse, condo, etc.)
> - Whether you plan to file an insurance claim (yes, no, or not sure)

**Homeowner:**
> Yes please, send it to Clearway. I'm Maria Lopez, 408-555-0142, maria.lopez@example.com, at 1032 Hollenbeck Ave in Sunnyvale. I own it, it's an older single-family house, and I'm home all day so ASAP is great. I have State Farm and will probably file a claim.

**Agent:**
> Thanks, Maria. One last check before I send it.
> 
> Is it OK for me to share your name, phone (408-555-0142), email (maria.lopez@example.com), address (1032 Hollenbeck Ave, Sunnyvale, CA 94087) and the details of the flooding with Clearway Restoration so they can contact you? Please reply yes or no.

**Homeowner:**
> Yes, that's fine. Please send it.

**Agent:**
> I've created your request and it's queued for Clearway Restoration. The lead ID is LEAD-20261008-D4FB68.
> 
> Water is still coming in, so I'd also call them directly at +1-408-457-0826. They're open 24/7. If they can't come soon, call Reactic Restoration at +1-408-998-4840.
> 
> Until help arrives, keep taking photos for your State Farm claim and stay away from any water near electrical equipment.

Resulting lead (`leads/LEAD-20261008-D4FB68.json`):

```
LEAD LEAD-20261008-D4FB68  [EMERGENCY]  Water Damage Restoration  quality=100/100
  Customer : Maria Lopez | (408) 555-0142 | maria.lopez@example.com (prefers phone)
  Location : 1032 Hollenbeck Ave, Sunnyvale, CA 94087 (single_family, owner)
  Problem  : Storm water began entering the basement last night and is still coming in along the back wall. About 2 inches of standing water covers the basement floor. Needs water extraction and drying.
    - Location: basement, water entering along back wall
    - Extent: approx. 2 inches of water across the floor
    - Started last night after the storm
    - Water still coming in
    - Outlets are not underwater
    - Older single-family home, owner-occupied
    - Insurance: State Farm, likely filing a claim
  Available: Home all day, ASAP
  Insurance: yes - likely filing with State Farm
  Safety   : Standing water in basement; homeowner reports outlets not submerged.
  Provider : Clearway Restoration | +1-408-457-0826 | https://clearwayrestoration.com/ | https://www.openstreetmap.org/node/7318153333
  Backup   : Reactic Restoration | +1-408-998-4840
  Backup   : Servpro | +1 650-770-2992
```

### 2. Price shopper who only agrees to be contacted if they'll get a quote (4 messages, lead quality 100)

The agent has no pricing data, so it declines to quote and offers to ask the provider for the fee and a written quote
up front. It still explains likely causes, asks a separate consent question naming the provider and listing what will be
shared, and describes the lead as queued rather than delivered.

**Homeowner:**
> how much does it cost to fix a water heater

**Agent:**
> I can't give you a price, even a rough one. It really depends on what the technician finds, and the provider will give you a quote. When I send your request, I can add a note saying you want the diagnostic/trip fee and a written quote before any work starts.
> 
> I can explain what's likely going on and find a local plumber. Two quick questions:
> 
> 1. What's the water heater doing? For example, no hot water, not enough hot water, leaking, strange noises, or a pilot light that won't stay lit. Is it gas, electric or tankless, and do you know roughly how old it is?
> 2. What's your ZIP code?
> 
> One safety note: if it's a gas unit and you smell gas, leave the house now and call your gas utility or 911 from outside.

**Homeowner:**
> It's a gas tank, 40 gallons, about 12 years old. Only lukewarm water since Sunday, and there's a small puddle under it. No gas smell. ZIP is 94087.

**Agent:**
> Thanks, that helps. A 12-year-old gas tank that's both lukewarm and leaking is near the end of a typical tank's life. Here's what a plumber will look at:
> 
> - Where the water is coming from. A drip from a fitting, the drain valve or the relief valve can often be fixed. Water from the tank itself usually means it needs to be replaced.
> - Why the water is lukewarm. Common causes are heavy sediment buildup, a burner or thermocouple problem, or a broken dip tube.
> 
> Until someone comes:
> - Put a towel or pan under the puddle and keep an eye on it.
> - If the leak gets worse, shut the cold-water valve on the pipe going into the top of the heater. You can also turn the gas control knob to "pilot" or "vacation."
> 
> I found two plumbing businesses near 94087:
> 
> 1. Palo Alto Plumbing Heating & Air, +1-650-856-3400, about 8.9 km away. This is my top pick because they focus on plumbing and heating, so water heaters are core work for them.
> 2. South Bay Builders, +1-408-892-2562, 1265 Lakeside Drive, Sunnyvale, about 5.3 km away. They're closer and listed under plumbing, but they may be more of a general builder.
> 
> I don't have ratings or availability info for either one.
> 
> Want me to send your request to Palo Alto Plumbing Heating & Air so they call you back? If so, please send:
> - Your full name and best phone number (and email if you'd like)
> - The service address
> - When someone can come, whether you own or rent, and the type of home (house, condo, townhouse, etc.)

**Homeowner:**
> Sure, go ahead, but please include that note about wanting the trip fee and a written quote before any work. I'm Linda Park, 408-555-0110, lpark@example.com, at 977 Pome Ave, Sunnyvale CA 94087. I own the house (single family), and I'd like someone this week, mornings are best.

**Agent:**
> Thanks, Linda. I'll set this up as a request for this week, mornings preferred, with your note asking for the trip fee and a written quote before any work.
> 
> Before I queue it, please confirm: can I share your name, phone (408-555-0110), email (lpark@example.com), address (977 Pome Ave, Sunnyvale CA 94087) and the water heater details with Palo Alto Plumbing Heating & Air so they can contact you? Also, would you prefer they reach you by phone, text or email?

**Homeowner:**
> Yes, you can share all of that with them. Phone is best, and a text is fine too if I miss the call.

**Agent:**
> Your request is in. Lead ID: LEAD-20261008-AA3679
> 
> It's queued for Palo Alto Plumbing Heating & Air (+1-650-856-3400). I included your note asking for the trip fee and a written quote before any work, and that mornings this week work best. I also noted they should call you first and text if they miss you.
> 
> I can't see whether they've picked it up yet. If you don't hear back soon, or the puddle gets bigger, call them directly. South Bay Builders (+1-408-892-2562) is listed as the backup.

## Evaluation results (Sunnyvale, CA 94087)

`python -m evals.simulate` with Claude playing six homeowners in 94087 (fictional customers, live OpenStreetMap
providers). Full transcripts are in `evals/results.json` and `evals/run.log`.

| Metric | Result |
|---|---|
| Conversion rate (validated, dispatchable lead) | **6/6 (100%)** |
| Category accuracy | 100% |
| Average lead quality | **97.7 / 100** |
| Average homeowner messages to lead | 4.2 |

| Scenario | Category | Quality | Turns | Recommended provider (real) |
|---|---|---|---|---|
| Storm water in basement (README example) | water_damage_restoration | 100 | 4 | Clearway Restoration |
| Furnace blowing cold air | hvac | 92 | 4 | Palo Alto Plumbing Heating & Air |
| Kitchen outlet sparked, breaker won't reset | electrical | 100 | 5 | Flores Electric |
| Ceiling stain after windstorm | roofing | 97 | 4 | Waterproofing Associates |
| Renter with clogged kitchen sink | plumbing | 97 | 4 | Palo Alto Plumbing Heating & Air |
| "How much to fix a water heater?" price shopper | plumbing | 100 | 4 | Palo Alto Plumbing Heating & Air |

Points lost: customers who gave no email (−3) and the HVAC lead having no backup provider (−5), because only one HVAC
business near 94087 has a phone number on OpenStreetMap.

### Iterations

| | v1 | v2 (prompt fixes) | v3 (provider filtering) |
|---|---|---|---|
| Conversion | 100% | 100% | 100% |
| Avg lead quality | 97.7 | 97.2 | 97.7 |
| Avg messages to lead | 3.8 | 4.2 | 4.2 |

**v1 → v2 (prompt).** v1 converted 6/6, but reading the transcripts showed three problems:
1. It quoted dollar price ranges from general knowledge, which isn't verified data.
2. It told one customer the request "was sent", but leads are only queued (there's no delivery integration).
3. It treated an early "go ahead and send it" as consent before telling the customer what would be shared with whom.

v2 forbids price quotes (it offers to ask the provider for a quote instead), requires "queued" wording, and requires a
direct consent question naming the provider. The tool now records the customer's words of agreement
(`consent_statement`), and validation rejects leads without one. The explicit consent step costs about half an extra
message on average, with no conversion loss.

**v2 → v3 (providers).** A manual spot-check of every provider in the v2 leads (next section) found wrong-trade
backups. v3 returns only providers with a phone number and down-ranks generalist builders. Automated checks on all six
v3 transcripts: 0 dollar amounts, 0 "sent"/"received" claims, 6/6 leads with a consent quote, and every primary
recommendation is a verified business.

Earlier results: `evals/results_v1.json`, `evals/results_v2.json`. A partial run in other cities (Austin, Chicago,
Seattle) converted 3/3 with quality 100/97/90 (`evals/run_multicity_partial.log`).

Caveats: six scenarios is a small sample, and simulated homeowners are more cooperative than real ones. Plumbing and
HVAC leads all go to the same Palo Alto business because OpenStreetMap lists few phone-reachable plumbers near 94087;
Google Places would widen the choice.

## Provider spot-check (2026-10-08)

All 12 providers that appeared in the v2 and v3 94087 eval leads (as primary or backup) were checked by loading the
business's own website and comparing the phone number, plus web searches where the site couldn't be loaded.

| Provider | Used for | Check | Result |
|---|---|---|---|
| Clearway Restoration | storm water (primary) | Website live, (408) 457-0826 on site, "Water Damage Restoration in Santa Clara" | ✅ Verified |
| Reactic Restoration | storm water (backup) | Website live, (408) 998-4840 on site | ✅ Verified |
| Servpro | storm water (backup) | 650-770-2992 is SERVPRO of Mountain View / Los Altos (24/7 franchise) | ✅ Verified (OSM name is generic) |
| Palo Alto Plumbing Heating & Air | furnace, clogged sink, water heater (primary) | Site blocks scripts; 650-856-3400 confirmed by City of Palo Alto contractor list and ServiceMag, 75 Demeter St, East Palo Alto | ✅ Verified; the OSM pin looks out of date, so the 8.9 km distance is probably understated (East Palo Alto is roughly 15 km away) |
| Flores Electric | sparking outlet (primary) | Website live, 408-899-8450 on site, residential electrician | ✅ Verified |
| WCI Electric | sparking outlet (backup) | Website live, (408) 242-2069 on site | ⚠️ Real, but a commercial electrician, so a weak match for a home job |
| Waterproofing Associates | roof leak (primary) | Website live (roofwa.com), (650) 937-1299 on site | ✅ Verified |
| Falcon Roofing | roof leak (backup) | Website live, 650.961.3200 on site (main line 408-225-1705) | ✅ Verified |
| Cosmos Roofing | roof leak (backup) | Website live, 650.969.7663 on site | ✅ Verified |
| ProTemp Mechanical | furnace (backup) | Website live, but the business is "environmental chambers"; no phone in OSM | ❌ Real business, wrong trade (not residential HVAC) |
| University Electric | sparking outlet (v3 backup) | Site blocks scripts; directories list it as "University Electric Home Appliance Center", 408-496-0500, 1500 Martin Ave, Santa Clara | ❌ Real business, but an appliance store, not an electrician |
| South Bay Builders | water heater (backup) | Website unreachable; phone 408-892-2562 not found in any listing; a "South Bay Builder" at the same address holds a general building (B) license | ❌ Phone unverified, and not a plumber |

All 6 primary recommendations are real, reachable businesses in the right trade. The problems were among the
backups: 3 of 12 providers were wrong-trade or unverifiable, and 1 was a commercial-only match. All four trace to
OpenStreetMap tagging (`craft=hvac` / `craft=plumber` on a non-residential business or a general contractor, or a
`shop=appliance` store whose name contains "Electric").

Fixes applied after the spot-check (re-tested live on 94087):
- Only providers with a phone number are returned, since a lead can't be dispatched without one. This removes
  ProTemp Mechanical and other phoneless mis-tags (e.g. an HVAC equipment distributor).
- Businesses named "Builders / Construction / Contracting" are down-ranked outside the general-contractor and
  handyman categories. South Bay Builders drops from #1 to #2 for plumbing, behind Palo Alto Plumbing Heating & Air.
- A name-only match ("Electric", "Plumbing", ...) no longer counts for stores (`shop=appliance/trade/electrical`),
  which removes University Electric. Search results are cached with a version number, so the new rules apply
  immediately instead of after the 24h cache expires.

Current 94087 results after these fixes (each checked in the table above): water damage: Clearway, Servpro, Reactic; electrical:
WCI, Flores; roofing: Waterproofing Associates, Falcon, Cosmos; plumbing: Palo Alto Plumbing, then South Bay Builders;
HVAC: Palo Alto Plumbing only.

Still open: South Bay Builders can still appear as a plumbing backup (it has a phone, but the number couldn't be
verified), and only one HVAC provider near 94087 has a phone on OSM, so HVAC leads have no backup. Google Places
(business status, categories, reviews) is the real fix for both.

## Status

Implemented and verified:
- Live Claude conversations end to end (CLI), including a manual run that produced a 100/100 lead in 3 turns
- Provider search tested live with OpenStreetMap (Sunnyvale, Austin, Chicago, Seattle, Denver, Columbus, New York)
- Offline rule-based demo mode (`--offline`, automatic when no key is set)
- Lead validation (including a recorded consent quote), scoring and persistence; 21 unit tests (`tests/`)

Implemented but not tested: the Google Places backend (no key was available).

Known limitations:
- OpenStreetMap coverage of home-service businesses is sparse outside big metros, and an Overpass query can take 10–50s
  when not cached. Google Places is the recommended production source.
- "Dispatch" means writing a `ready_to_dispatch` JSON lead. There's no SMS or email delivery to the provider yet.
- Provider availability and capacity aren't known; ranking uses proxies (24/7 hours, open now).

Next priorities:
1. Grow the eval with harder personas (users who refuse to give a phone number, angry or confused users) and tune the prompt on the failures.
2. Actual dispatch: email/SMS (Twilio/SendGrid) to the provider with accept/decline links; fall back to the backup provider on decline or timeout.
3. Add a third data source (Yelp Fusion) and merge/dedupe across sources; use review text for specialization matching.
4. Web UI (simple FastAPI + HTML chat) and streaming responses.
5. Photo upload (Claude vision) to assess damage severity for the lead.
