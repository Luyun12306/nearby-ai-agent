"""Simulated-homeowner evaluation: conversion rate and lead quality.

Claude plays a homeowner from a scenario card (only revealing facts when asked);
the real agent talks to it with live provider search. We measure:
- conversion: a validated, dispatchable lead was created
- category accuracy: lead category is in the scenario's acceptable set
- lead quality: leads.score_lead (0-100)
- turns to lead

Usage:  python -m evals.simulate [--only ID ...] [--max-turns 14]
Costs real API calls (agent + simulator) and hits OSM/Google for providers.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import anthropic

from nearby_agent.agent import HomeServiceAgent
from nearby_agent.env import load_env

SIM_MODEL = os.environ.get("SIM_MODEL", "claude-opus-5-5")
DONE = "<<END>>"

# All scenarios are in Sunnyvale, CA 94087 (customers are fictional; providers come from live search).
SCENARIOS = [
    {
        "id": "storm_basement",
        "opening": "Water started coming into my basement last night after the storm. I don't know who to call.",
        "expected": ["water_damage_restoration", "basement_waterproofing"],
        "facts": "Name Maria Lopez, phone 408-555-0142, email maria.lopez@example.com. House at 1032 Hollenbeck Ave, "
                 "Sunnyvale CA 94087, you own it (single family, older home with a small basement). About 2 inches of "
                 "water across the basement floor, coming in along the back wall; rug soaked, bottom of drywall wet. "
                 "No outlets underwater. You're home all day today. You have State Farm insurance and might file.",
        "temperament": "stressed but cooperative",
    },
    {
        "id": "no_heat",
        "opening": "my furnace stopped working and the house is getting really cold",
        "expected": ["hvac"],
        "facts": "Name Dave Kowalski, phone (408) 555-0199. Address 1455 Remington Dr, Sunnyvale CA 94087, you own the "
                 "house. Gas furnace, about 15 years old, fan runs but blows cold air since this morning; thermostat set "
                 "to 70, house is 57F. You already replaced the thermostat batteries. No gas smell. Toddler at home. "
                 "Available any time today or tomorrow.",
        "temperament": "terse, types in lowercase",
    },
    {
        "id": "sparking_outlet",
        "opening": "One of the outlets in my kitchen sparked and now half the kitchen has no power.",
        "expected": ["electrical"],
        "facts": "Name Priya Raman, phone 408-555-0163, email priya.r@example.com. Townhouse at 820 E Fremont Ave Unit 12, "
                 "Sunnyvale CA 94087, you own it. Outlet next to the toaster sparked yesterday evening with a pop; breaker "
                 "tripped and won't stay reset for that circuit. No burning smell now. Prefer weekday afternoons this week.",
        "temperament": "detail-oriented, asks why info is needed",
    },
    {
        "id": "roof_leak",
        "opening": "Hi, there's a brown stain spreading on my ceiling, I think the roof is leaking",
        "expected": ["roofing"],
        "facts": "Name Tom Becker, phone 408-555-0127. Address 1268 Inverness Way, Sunnyvale CA 94087, owner, single "
                 "family one-story. Stain about the size of a dinner plate in the hallway ceiling, drips only during "
                 "heavy rain, noticed after last week's windstorm, a few shingles in the yard. Composition shingle roof "
                 "about 20 years old. Any weekday morning works, prefers text.",
        "temperament": "friendly, a bit chatty",
    },
    {
        "id": "clogged_drain_renter",
        "opening": "kitchen sink totally clogged, water won't go down at all",
        "expected": ["plumbing"],
        "facts": "Name Jordan Ellis, phone 408-555-0188. Address 1111 Bernardo Ave Apt 7, Sunnyvale CA 94087. You RENT; "
                 "your landlord said you can call someone and he'll reimburse. Standing water in both basins since last "
                 "night, tried a plunger and Drano. The garbage disposal hums but doesn't spin. Available after 5pm on weekdays.",
        "temperament": "cooperative but initially reluctant to share phone number until it's clear why",
    },
    {
        "id": "vague_price_shopper",
        "opening": "how much does it cost to fix a water heater",
        "expected": ["plumbing"],
        "facts": "Name Linda Park, phone 408-555-0110, email lpark@example.com. Address 977 Pome Ave, Sunnyvale CA 94087, "
                 "owner, single family. 40-gallon gas tank water heater in the garage, 12 years old, only lukewarm water "
                 "since Sunday, small puddle under it. Wants someone this week, mornings best.",
        "temperament": "price-focused; only agrees to be contacted if the agent explains the provider will give a quote",
    },
]

SIM_SYSTEM = """You are role-playing a homeowner chatting with a home-services assistant. Stay in character.

Your situation and personal details (reveal only what is asked, in a natural way; never volunteer everything at once):
{facts}

Temperament: {temperament}

Rules:
- Write short, natural chat messages (1-3 sentences), like a real person texting.
- Answer the assistant's questions truthfully from the details above. If asked something not covered, give a plausible short answer.
- Agree to share your contact info with the recommended provider once the assistant asks for consent (unless your temperament says otherwise and the condition isn't met).
- When the assistant confirms a request/lead has been sent with an ID, or the conversation is clearly finished, reply with exactly {done}."""


def simulate(scenario: dict, max_turns: int, verbose: bool) -> dict:
    client = anthropic.Anthropic()
    agent = HomeServiceAgent(client=client, log=print if verbose else None)
    user_msg = scenario["opening"]
    # Simulator's view: agent messages are "user", homeowner messages are "assistant".
    sim_messages = [
        {"role": "user", "content": "Hi! What's going on at home? Tell me what happened and I'll find the right local pro."},
        {"role": "assistant", "content": user_msg},
    ]
    turns = 0
    started = time.time()
    error = None
    try:
        while turns < max_turns:
            turns += 1
            if verbose:
                print(f"\n  USER: {user_msg}")
            reply = agent.send(user_msg)
            if verbose:
                print(f"  AGENT: {reply}")
            if agent.lead:
                break
            sim_messages.append({"role": "user", "content": reply})
            sim = client.messages.create(
                model=SIM_MODEL,
                max_tokens=2000,
                system=SIM_SYSTEM.format(facts=scenario["facts"], temperament=scenario["temperament"], done=DONE),
                messages=sim_messages,
                output_config={"effort": "low"},
            )
            user_msg = next((b.text for b in sim.content if b.type == "text"), "").strip()
            if not user_msg or DONE in user_msg:
                break
            sim_messages.append({"role": "assistant", "content": user_msg})
    except anthropic.APIError as e:
        error = f"{type(e).__name__}: {e}"

    lead = agent.lead
    return {
        "id": scenario["id"],
        "converted": bool(lead),
        "category": lead["job"]["category"] if lead else None,
        "category_ok": bool(lead) and lead["job"]["category"] in scenario["expected"],
        "quality": lead["quality"]["score"] if lead else 0,
        "quality_missing": lead["quality"]["missing"] if lead else [],
        "provider": lead["recommended_provider"]["name"] if lead else None,
        "provider_source_url": lead["recommended_provider"].get("source_url") if lead else None,
        "turns": turns,
        "seconds": round(time.time() - started, 1),
        "lead_path": str(agent.lead_path) if agent.lead_path else None,
        "error": error,
        "transcript": agent.transcript,
    }


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="scenario ids to run")
    parser.add_argument("--max-turns", type=int, default=14)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--out", default="evals/results.json")
    args = parser.parse_args()

    scenarios = [s for s in SCENARIOS if not args.only or s["id"] in args.only]
    if not scenarios:
        sys.exit(f"No scenarios match. Available: {[s['id'] for s in SCENARIOS]}")
    results = []
    for s in scenarios:
        print(f"=== {s['id']} ===", flush=True)
        r = simulate(s, args.max_turns, args.verbose)
        results.append(r)
        print(f"converted={r['converted']} category={r['category']} ok={r['category_ok']} "
              f"quality={r['quality']} turns={r['turns']} provider={r['provider']} {r['error'] or ''}", flush=True)

    n = len(results)
    converted = [r for r in results if r["converted"]]
    summary = {
        "scenarios": n,
        "conversion_rate": round(len(converted) / n, 3),
        "category_accuracy": round(sum(r["category_ok"] for r in results) / n, 3),
        "avg_lead_quality": round(sum(r["quality"] for r in converted) / len(converted), 1) if converted else 0,
        "avg_turns_to_lead": round(sum(r["turns"] for r in converted) / len(converted), 1) if converted else None,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print("\nSUMMARY", json.dumps(summary, indent=2))
    print(f"Full results: {args.out}")


if __name__ == "__main__":
    main()
