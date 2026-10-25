import copy
import json
import tempfile
import unittest

from bridge import Council, CouncilError
from tracking import tracking_result, validate_input, classify
from tests.test_bridge import agent, signed_in, wait


def data(points=1, previous=None):
    return {"agents": [{"id": "a", "name": "Claude"}, {"id": "b", "name": "Codex"}],
            "sources": [{"id": f"s{n}{a}", "agentId": a, "checkpoint": n,
                         "text": f"Agent {a} in round {n}. We need independent validation before deployment."}
                        for n in range(points) for a in ("a", "b")],
            "checkpoints": list(range(points)), "previous": previous}


def raw_result(inp, positions=("support", "oppose")):
    previous = inp.get("previous") or {}
    claims = previous.get("claims") or [{"id": "c1", "text": "Deployment requires independent validation.", "introducedAt": 0}]
    snapshots = []
    for point in inp["checkpoints"][len(previous.get("snapshots", [])):]:
        snapshots.append({"checkpoint": point, "assessments": [{"claimId": claim["id"], "positions": [
            {"agentId": a, "stance": stance, "evidence": [] if stance == "not_stated" else [
                {"sourceId": f"s{point}{a}", "quote": "We need independent validation before deployment."}]}
            for a, stance in zip(("a", "b"), positions)]} for claim in claims if claim["introducedAt"] <= point]})
    return {"newClaims": [] if previous.get("claims") else claims, "snapshots": snapshots}


class TrackingTests(unittest.TestCase):
    def test_counts_follow_positions_not_model_scores(self):
        for stances, category in [(("support", "support"), "aligned"), (("oppose", "oppose"), "aligned"),
                                  (("support", "oppose"), "contested"), (("support", "uncertain"), "contested"),
                                  (("support", "not_stated"), "unresolved"), (("uncertain", "uncertain"), "unresolved")]:
            with self.subTest(stances=stances):
                inp = data()
                raw = raw_result(inp, stances)
                raw["snapshots"][0]["assessments"][0]["category"] = "aligned"
                result = tracking_result(json.dumps(raw), inp)
                self.assertEqual(result["snapshots"][0]["counts"][category], 1)

    def test_cannot_quote_another_agent_or_future_round(self):
        inp = data(2)
        for source_id in ("s0b", "s1a"):
            raw = raw_result(inp)
            raw["snapshots"][0]["assessments"][0]["positions"][0]["evidence"][0]["sourceId"] = source_id
            with self.subTest(source=source_id), self.assertRaisesRegex(ValueError, "another agent or a future"):
                tracking_result(json.dumps(raw), inp)

    def test_fabricated_quote_is_rejected(self):
        inp = data()
        raw = raw_result(inp)
        raw["snapshots"][0]["assessments"][0]["positions"][0]["evidence"][0]["quote"] = "This was never said."
        with self.assertRaisesRegex(ValueError, "not present"):
            tracking_result(json.dumps(raw), inp)

    def test_silence_cannot_be_cited_as_support(self):
        inp = data()
        raw = raw_result(inp)
        raw["snapshots"][0]["assessments"][0]["positions"][0]["evidence"] = []
        with self.assertRaisesRegex(ValueError, "require a source quote"):
            tracking_result(json.dumps(raw), inp)

    def test_earlier_snapshot_and_claim_are_preserved(self):
        first = tracking_result(json.dumps(raw_result(data(), ("support", "not_stated"))), data())
        inp = data(2, first)
        second = tracking_result(json.dumps(raw_result(inp, ("support", "support"))), inp)
        self.assertEqual(second["claims"], first["claims"])
        self.assertEqual(second["snapshots"][0], first["snapshots"][0])
        self.assertEqual(second["snapshots"][1]["counts"]["aligned"], 1)
        self.assertEqual(first["snapshots"][0]["counts"]["unresolved"], 1)

    def test_new_claim_is_not_added_to_old_baseline(self):
        first = tracking_result(json.dumps(raw_result(data())), data())
        inp = data(2, first)
        raw = raw_result(inp)
        raw["newClaims"] = [{"id": "c2", "text": "A new proposition.", "introducedAt": 0}]
        with self.assertRaisesRegex(ValueError, "earlier baseline"):
            tracking_result(json.dumps(raw), inp)
        raw["newClaims"][0]["introducedAt"] = 1
        extra = copy.deepcopy(raw["snapshots"][0]["assessments"][0])
        extra["claimId"] = "c2"
        raw["snapshots"][0]["assessments"].append(extra)
        second = tracking_result(json.dumps(raw), inp)
        self.assertEqual(len(second["snapshots"][0]["assessments"]), 1)
        self.assertEqual(len(second["snapshots"][1]["assessments"]), 2)

    def test_altered_prior_quotes_and_source_cannot_rewrite_history(self):
        first = tracking_result(json.dumps(raw_result(data())), data())
        inp = data(2, first)
        inp["sources"][0]["text"] += " Edited later."
        with self.assertRaisesRegex(ValueError, "source changed"):
            validate_input(inp)
        inp = data(2, copy.deepcopy(first))
        inp["previous"]["snapshots"][0]["counts"]["aligned"] = 50
        with self.assertRaisesRegex(ValueError, "altered"):
            validate_input(inp)

    def test_partial_round_and_malformed_shape_are_rejected(self):
        inp = data(2)
        inp["sources"].pop()
        with self.assertRaisesRegex(ValueError, "every debater"):
            validate_input(inp)
        with self.assertRaises(ValueError):
            tracking_result("not JSON", data())

    def test_tracking_job_uses_existing_cli_runner_and_no_research_tools(self):
        inp = data()
        calls = []
        def runner(a, prompt, job):
            calls.append(prompt)
            return {"text": "```json\n"+json.dumps(raw_result(inp))+"\n```"}
        with tempfile.TemporaryDirectory() as folder:
            council = Council(folder, runner=runner, auth=signed_in)
            try:
                analyst = agent("scribe", role="reviewer")
                analyst["tools"] = {}
                request = {"sessionId": "tracking", "kind": "tracking", "question": "A test", "agents": [analyst],
                           "trackingInput": inp, "transcript": [{"text": "PRIVATE_MODERATOR_TEXT"}], "packet": {"documents": []}}
                result = wait(council, council.start(request))
                self.assertEqual(result["status"], "complete")
                self.assertEqual(result["results"][0]["tracking"]["snapshots"][0]["counts"]["contested"], 1)
                self.assertNotIn("PRIVATE_MODERATOR_TEXT", calls[0])
                analyst["tools"]["webSearch"] = True
                with self.assertRaises(CouncilError):
                    council.start(request)
            finally:
                council.close()

    def test_invalid_model_report_is_a_visible_job_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            council = Council(folder, runner=lambda a,p,j: {"text": "I guess 80%"}, auth=signed_in)
            try:
                a = agent("scribe", role="reviewer"); a["tools"] = {}
                result = wait(council, council.start({"sessionId": "x", "kind": "tracking", "question": "A test", "agents": [a], "trackingInput": data()}))
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], "invalid_tracking_output")
            finally:
                council.close()
