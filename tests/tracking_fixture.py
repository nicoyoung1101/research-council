"""Deterministic structured output for UI integration tests only."""
import copy
import json


def output(data):
    previous = data.get("previous") or {}
    pending = data["checkpoints"][len(previous.get("snapshots", [])):]
    additions = [] if previous.get("claims") else [
        {"id": "c1", "text": "The baseline needs independent validation.", "introducedAt": 0},
        {"id": "c2", "text": "The current approach is ready for deployment.", "introducedAt": 0},
        {"id": "c3", "text": "Current evidence resolves generalization concerns.", "introducedAt": 0}]
    if pending[-1] > 0 and not any(c["id"] == "c4" for c in previous.get("claims", [])):
        additions.append({"id": "c4", "text": "A new control group would improve the experiment.", "introducedAt": max(1, pending[0])})
    claims = previous.get("claims", []) + additions
    snapshots = []
    for point in pending:
        rows = []
        for claim in claims:
            if claim["introducedAt"] > point:
                continue
            positions = []
            for i, agent in enumerate(data["agents"]):
                stance = "support"
                if claim["id"] == "c2" and point == 0 and i:
                    stance = "oppose"
                if claim["id"] == "c3" and i:
                    stance = "not_stated"
                if claim["id"] == "c4":
                    stance = "uncertain"
                source = next(s for s in data["sources"] if s["agentId"] == agent["id"] and s["checkpoint"] == point)
                evidence = [] if stance == "not_stated" else [{"sourceId": source["id"], "quote": source["text"][:160]}]
                positions.append({"agentId": agent["id"], "stance": stance, "evidence": evidence})
            rows.append({"claimId": claim["id"], "positions": positions})
        snapshots.append({"checkpoint": point, "assessments": rows})
    return json.dumps({"newClaims": additions, "snapshots": snapshots}, ensure_ascii=False)
