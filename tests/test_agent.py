"""Agent loop tests with a scripted fake Claude client (no network)."""

import json
from types import SimpleNamespace as NS

from nearby_agent import agent as agent_mod
from nearby_agent.agent import HomeServiceAgent, _echoable_content
from nearby_agent.providers import Provider


def text(t):
    return NS(type="text", text=t)


def tool(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def resp(stop, *content):
    return NS(stop_reason=stop, content=list(content))


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs["messages"], default=lambda o: o.__dict__)))
        return self.responses.pop(0)


def fake_search(category_key, location, urgency="flexible", keywords="", backend=None, limit=5):
    return {
        "resolved_location": {"display_name": "78704, Austin, TX"},
        "category": category_key,
        "data_source": "fake",
        "total_found": 1,
        "providers": [Provider("osm:node/1", "Total Restoration of Texas", category_key, "openstreetmap",
                               "https://www.openstreetmap.org/node/1", phone="+1-512-698-8444")],
    }


LEAD_INPUT = {
    "customer": {"name": "Maria Lopez", "phone": "512-555-0142", "consent_to_share": True, "consent_statement": "Yes, OK to share with them"},
    "service_location": {"street_address": "1402 Bluebonnet Ln", "city": "Austin", "state": "TX", "zip": "78704"},
    "job": {"category": "water_damage_restoration", "urgency": "emergency",
            "problem_summary": "Two inches of standing water in the finished basement after a storm last night.",
            "details": ["north wall", "sump pump off"]},
    "recommended_provider_id": "osm:node/1",
}


def test_full_flow_search_then_lead(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_mod, "search_providers", fake_search)
    client = FakeClient([
        resp("tool_use", text("Let me find restoration pros."),
             tool("t1", "search_providers", {"category": "water_damage_restoration", "location": "78704", "urgency": "emergency"})),
        resp("end_turn", text("Total Restoration of Texas is 3 km away. Want me to send them your request?")),
        resp("tool_use", tool("t2", "create_lead", {**LEAD_INPUT, "recommended_provider_id": "invented"})),
        resp("tool_use", tool("t3", "create_lead", LEAD_INPUT)),
        resp("end_turn", text("Done! Your lead ID is ...")),
    ])
    a = HomeServiceAgent(client=client, leads_dir=tmp_path)

    r1 = a.send("Water in my basement after the storm, 78704")
    assert "Total Restoration" in r1 and "Let me find" in r1
    assert "osm:node/1" in a.known_providers

    r2 = a.send("Yes. Maria Lopez, 512-555-0142, 1402 Bluebonnet Ln. OK to share.")
    assert r2.startswith("Done!")
    # The invented provider was rejected with an actionable error before the valid call.
    rejected = client.calls[3][-1]["content"][0]
    assert rejected["is_error"] is True and "Never invent providers" in rejected["content"]
    assert a.lead["recommended_provider"]["name"] == "Total Restoration of Texas"
    saved = json.loads(a.lead_path.read_text())
    assert saved["transcript"][-1]["text"].startswith("Done!")


def test_refusal_returns_message_without_appending(tmp_path):
    client = FakeClient([resp("refusal")])
    a = HomeServiceAgent(client=client, leads_dir=tmp_path)
    assert "can't help" in a.send("something")
    assert a.messages == [{"role": "user", "content": "something"}]


def test_echoable_content_strips_pre_fallback_internal_blocks():
    blocks = [NS(type="thinking"), text("partial"), tool("x", "search_providers", {}), NS(type="fallback"),
              NS(type="thinking"), text("rest")]
    kept = [b.type for b in _echoable_content(blocks)]
    assert kept == ["text", "fallback", "thinking", "text"]
