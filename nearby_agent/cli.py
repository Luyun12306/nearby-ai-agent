"""Interactive terminal chat with the home-service agent."""

import argparse
import json
import os
import sys

import anthropic

from .agent import MODEL, HomeServiceAgent
from .leads import format_lead
from .offline import OfflineAgent
from .providers import GooglePlacesBackend, OSMBackend, default_backend
from .env import load_env


def main():
    load_env()
    parser = argparse.ArgumentParser(description="Chat with the Nearby home-service agent.")
    parser.add_argument("--backend", choices=["auto", "google", "osm"], default="auto",
                        help="Provider data source (auto = Google Places if GOOGLE_PLACES_API_KEY is set, else OpenStreetMap)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show tool calls")
    parser.add_argument("--offline", action="store_true",
                        help="Rule-based demo mode, no Anthropic key needed (used automatically when no key is set)")
    args = parser.parse_args()

    if args.backend == "google":
        key = os.environ.get("GOOGLE_PLACES_API_KEY")
        if not key:
            sys.exit("GOOGLE_PLACES_API_KEY is not set")
        backend = GooglePlacesBackend(key)
    elif args.backend == "osm":
        backend = OSMBackend()
    else:
        backend = default_backend()

    log = (lambda m: print(f"\033[2m{m}\033[0m")) if args.verbose else None
    def on_search(a):
        print(f"\n(Searching for real {a['category'].replace('_', ' ')} providers near {a['location']}... "
              f"this can take up to a minute)", flush=True)

    offline = args.offline or not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
    if offline:
        agent = OfflineAgent(provider_backend=backend, log=log, on_search=on_search)
        mode = "OFFLINE demo mode, rule-based, no AI"
    else:
        agent = HomeServiceAgent(provider_backend=backend, log=log, on_search=on_search)
        mode = MODEL
    print(f"Nearby home-service agent ({mode}, providers: {backend.name}). Type /quit to exit, /lead to show the lead.\n")
    print("Agent: Hi! What's going on at home? Tell me what happened and I'll find the right local pro.\n")

    while True:
        try:
            user = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user:
            continue
        if user in ("/quit", "/exit"):
            break
        if user == "/lead":
            print(json.dumps(agent.lead, indent=2) if agent.lead else "(no lead yet)")
            continue
        print("(thinking...)", flush=True)
        try:
            reply = agent.send(user)
        except anthropic.AuthenticationError:
            sys.exit("Anthropic authentication failed - set ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            print("Agent: (rate limited - please try again in a moment)\n")
            continue
        except anthropic.APIStatusError as e:
            print(f"Agent: (API error {e.status_code}: {e.message})\n")
            continue
        except anthropic.APIConnectionError:
            print("Agent: (network error talking to Claude - please retry)\n")
            continue
        print(f"\nAgent: {reply}\n")

    if agent.lead:
        print("\n" + format_lead(agent.lead))
        print(f"\nSaved to {agent.lead_path}")


if __name__ == "__main__":
    main()
