import copy
import base64
import json
import tempfile
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from bridge import Council, CouncilError, atomic_json, command, make_server, prompt_for


def agent(name="a", provider="codex", role="debater"):
    return dict(id=name, name=name, provider=provider, role=role, model="default",
                effort="default", rules="Preserve uncertainty", tools={"readLocal": True, "writeNotes": role == "scribe"})


def request(**changes):
    return dict(sessionId="session", kind="independent", question="Compare approaches",
                agents=[agent()], packet={"documents": [{"name": "evidence.md", "text": "OBSERVED FACT"}]}, **changes)


def signed_in(provider):
    return {"provider": provider, "installed": True, "loggedIn": True}


def wait(council, job):
    deadline = time.monotonic()+5
    while time.monotonic() < deadline:
        result = council.public(council.jobs[job["id"]])
        if result["status"] in ("complete", "failed", "cancelled"):
            return result
        time.sleep(.01)
    raise AssertionError("Job never finished")


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        def runner(a, prompt, job):
            self.calls.append((copy.deepcopy(a), prompt))
            return {"text": "ANSWER_"+a["id"], "effectiveModel": "fixture", "usage": {}}
        self.c = Council(self.tmp.name, runner=runner, auth=signed_in)

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def test_independent_calls_share_evidence_without_peer_leak(self):
        body = request()
        body["agents"] = [agent("a"), agent("b")]
        body["transcript"] = [{"text": "UNPUBLISHED_PEER"}]
        done = wait(self.c, self.c.start(body))
        self.assertEqual(done["status"], "complete")
        self.assertEqual(len(done["results"]), 2)
        for _, prompt in self.calls:
            self.assertIn("OBSERVED FACT", prompt)
            self.assertNotIn("UNPUBLISHED_PEER", prompt)
            self.assertNotIn("ANSWER_a", prompt)
            self.assertNotIn("ANSWER_b", prompt)

    def test_context_precedes_both_debaters(self):
        body = request(contextAgent=agent("context", role="context"))
        body["agents"] = [agent("a"), agent("b")]
        done = wait(self.c, self.c.start(body))
        self.assertEqual(done["context"]["text"], "ANSWER_context")
        self.assertEqual(self.calls[0][0]["id"], "context")
        for _, prompt in self.calls[1:]:
            self.assertIn("ANSWER_context", prompt)

    def test_debate_sees_actual_published_answers(self):
        body = request()
        body.update(kind="debate", agents=[agent("a"), agent("b")], transcript=[
            {"type": "independent", "id": "a", "text": "PUBLISHED_INITIAL_A"},
            {"type": "independent", "id": "b", "text": "PUBLISHED_INITIAL_B"},
            {"type": "agent", "id": "a", "round": 1, "text": "PUBLISHED_REPLY_A"},
            {"type": "agent", "id": "b", "round": 1, "text": "PUBLISHED_REPLY_B"}])
        done = wait(self.c, self.c.start(body))
        self.assertEqual(done["status"], "complete")
        self.assertEqual({a["id"] for a, _ in self.calls}, {"a", "b"})
        for _, prompt in self.calls:
            for turn in body["transcript"]:
                self.assertIn(turn["text"], prompt)
            self.assertNotIn("ANSWER_a", prompt)
            self.assertNotIn("ANSWER_b", prompt)

    def test_rules_snapshot_is_immutable(self):
        gate = threading.Event()
        def runner(a, prompt, job):
            gate.wait(2)
            return {"text": prompt}
        self.c.runner = runner
        body = request()
        job = self.c.start(body)
        body["agents"][0]["rules"] = "MUTATED_RULES"
        gate.set()
        done = wait(self.c, job)
        self.assertNotIn("MUTATED_RULES", done["results"][0]["text"])
        self.assertEqual(len(done["results"][0]["rulesHash"]), 64)

    def test_duplicate_request_is_idempotent(self):
        body = request(requestId="unique")
        a = self.c.start(body)
        b = self.c.start(body)
        self.assertEqual(a["id"], b["id"])
        wait(self.c, a)
        self.assertEqual(len(self.calls), 1)

    def test_request_id_cannot_change_payload(self):
        body = request(requestId="unique")
        wait(self.c, self.c.start(body))
        body["question"] = "Different question"
        with self.assertRaises(CouncilError):
            self.c.start(body)

    def test_partial_failure_keeps_successful_answers(self):
        def runner(a, prompt, job):
            if a["id"] == "bad":
                raise CouncilError("cli_failed", "model unavailable")
            return {"text": "SUCCESS"}
        self.c.runner = runner
        body = request()
        body["agents"] = [agent("bad"), agent("good")]
        done = wait(self.c, self.c.start(body))
        self.assertEqual(done["status"], "failed")
        self.assertEqual(done["results"][0]["agentId"], "good")
        self.assertEqual(done["failures"][0]["agentId"], "bad")

    def test_targeted_moderator_is_not_leaked_to_other_agent(self):
        body = request()
        body.update(kind="debate", moderator=[{"to": "a", "text": "ONLY_FOR_A"}],
                    transcript=[{"type": "user", "to": "a", "text": "PRIVATE_DIRECTIVE"}])
        self.assertIn("ONLY_FOR_A", prompt_for(agent("a"), body))
        self.assertNotIn("ONLY_FOR_A", prompt_for(agent("b"), body))
        self.assertNotIn("PRIVATE_DIRECTIVE", prompt_for(agent("b"), body))

    def test_shared_startup_instructions_are_equal_for_independent_agents(self):
        body = request(initialInstructions=[{"to": "all", "text": "SHARED_CONSTRAINT"},
                                            {"to": "a", "text": "TARGETED_CONSTRAINT"}])
        for name in ("a", "b"):
            prompt = prompt_for(agent(name), body)
            self.assertIn("SHARED_CONSTRAINT", prompt)
            self.assertNotIn("TARGETED_CONSTRAINT", prompt)

    def test_native_codex_event_parser_and_model_failure(self):
        self.c.runner = self.c.run_cli
        script = "import sys,json;sys.stdin.read();print('non-json diagnostic');print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'REAL PARSER'}}));print(json.dumps({'type':'turn.completed','usage':{'output_tokens':2}}))"
        with patch("bridge.command", return_value=[sys.executable, "-c", script]):
            done = wait(self.c, self.c.start(request()))
        self.assertEqual(done["results"][0]["text"], "REAL PARSER")
        self.assertEqual(done["results"][0]["usage"]["output_tokens"], 2)
        script = "import sys,json;sys.stdin.read();print(json.dumps({'type':'turn.failed','error':{'message':'invalid model'}}))"
        with patch("bridge.command", return_value=[sys.executable, "-c", script]):
            done = wait(self.c, self.c.start(request()))
        self.assertEqual(done["status"], "failed")
        self.assertIn("invalid model", done["error"]["detail"])

    def test_native_claude_result_parser(self):
        self.c.runner = self.c.run_cli
        script = "import sys,json;sys.stdin.read();print(json.dumps({'type':'system','subtype':'init','model':'claude-fixture'}));print(json.dumps({'type':'result','result':'CLAUDE PARSER','is_error':False,'usage':{'input_tokens':3}}))"
        body = request()
        body["agents"] = [agent(provider="claude")]
        with patch("bridge.command", return_value=[sys.executable, "-c", script]):
            done = wait(self.c, self.c.start(body))
        self.assertEqual(done["results"][0]["text"], "CLAUDE PARSER")
        self.assertEqual(done["results"][0]["effectiveModel"], "claude-fixture")

    def test_process_timeout_is_reported_and_process_reaped(self):
        self.c.runner = self.c.run_cli
        self.c.timeout = .1
        script = "import sys,time;sys.stdin.read();time.sleep(60)"
        with patch("bridge.command", return_value=[sys.executable, "-c", script]):
            done = wait(self.c, self.c.start(request()))
        self.assertEqual(done["error"]["code"], "timeout")
        self.assertEqual(self.c.active, {})

    def test_overlapping_task_for_same_session_is_rejected(self):
        gate = threading.Event()
        self.c.runner = lambda a,p,j: (gate.wait(2), {"text": "done"})[1]
        a = self.c.start(request())
        try:
            with self.assertRaises(CouncilError) as error:
                self.c.start(request())
            self.assertEqual(error.exception.code, "busy")
        finally:
            gate.set()
            wait(self.c, a)

    def test_cancel_propagates_to_runner(self):
        def runner(a, prompt, job):
            job["cancel"].wait(2)
            if job["cancel"].is_set():
                raise CouncilError("cancelled")
            return {"text": "late"}
        self.c.runner = runner
        job = self.c.start(request())
        self.c.cancel(job["id"])
        self.assertEqual(wait(self.c, job)["status"], "cancelled")

    def test_auth_failure_never_invokes_model(self):
        self.c.auth = lambda p: {"installed": True, "loggedIn": False}
        with self.assertRaises(CouncilError) as error:
            self.c.start(request())
        self.assertEqual(error.exception.code, "login_required")
        self.assertEqual(self.calls, [])

    def test_unknown_provider_is_rejected(self):
        body = request()
        body["agents"][0]["provider"] = "grok"
        with self.assertRaises(CouncilError):
            self.c.start(body)

    def test_failed_cli_does_not_become_success(self):
        def runner(*args):
            raise CouncilError("cli_failed", "unsupported model")
        self.c.runner = runner
        done = wait(self.c, self.c.start(request()))
        self.assertEqual(done["status"], "failed")
        self.assertIn("unsupported model", done["error"]["detail"])
        self.assertEqual(done["results"], [])

    def test_save_revision_prevents_overwrite_and_survives_restart(self):
        state = {"sessions": [{"id": "s"}], "library": [], "theme": "light"}
        self.c.save_state({"revision": 0, "state": state})
        with self.assertRaises(CouncilError) as error:
            self.c.save_state({"revision": 0, "state": {"sessions": [], "library": []}})
        self.assertEqual(error.exception.code, "state_conflict")
        restored = Council(self.tmp.name)
        try:
            self.assertEqual(restored.state, state)
            self.assertEqual(restored.revision, 1)
        finally:
            restored.close()

    def test_running_job_is_marked_interrupted_after_restart(self):
        atomic_json(Path(self.tmp.name)/"jobs/job.json", {"id": "job", "status": "running", "request": {}})
        restored = Council(self.tmp.name)
        try:
            self.assertEqual(restored.jobs["job"]["status"], "interrupted")
        finally:
            restored.close()

    def test_corrupt_state_is_not_silently_overwritten(self):
        (Path(self.tmp.name)/"state.json").write_text("broken")
        with self.assertRaises(ValueError):
            Council(self.tmp.name)
        self.assertEqual((Path(self.tmp.name)/"state.json").read_text(), "broken")

    def test_adapter_argv_keeps_prompt_out_of_shell(self):
        a = agent()
        a["model"] = 'model; $(echo PRIVATE)'
        with patch("bridge.locate", return_value="/bin/codex"):
            args = command(a, Path("/tmp/work"))
        self.assertIn(a["model"], args)
        self.assertIn("read-only", args)
        self.assertIn("features.shell_tool=false", args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = make_server(0, self.tmp.name, runner=lambda a,p,j:{"text":"fixture"}, auth=signed_in)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.council.close()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def fetch(self, path, headers=None, data=None):
        req = urllib.request.Request(self.url+path, headers=headers or {}, data=data)
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_static_allowlist_blocks_source_and_private_data(self):
        for path in ("/.git/config", "/bridge.py", "/.research-council/state.json", "/../README.md"):
            self.assertEqual(self.fetch(path)[0], 404)
        code, html = self.fetch("/index.html")
        self.assertEqual(code, 200)
        self.assertIn(b'<style data-source="themes.css">', html)
        self.assertIn(b'<style data-source="runtime.css">', html)
        self.assertNotIn(b'<link rel="stylesheet"', html)
        self.assertIn(b'<script data-source="marked.umd.js">', html)
        self.assertIn(b'<script data-source="conversation-scroll.js">', html)
        self.assertNotIn(b'<script src=', html)
        for script in ("/marked.umd.js", "/markdown.js", "/conversation-scroll.js"):
            self.assertEqual(self.fetch(script)[0], 200)

    def test_image_upload_and_preview_require_token_and_never_expose_paths(self):
        from test_images import PNG
        data=json.dumps({'mime':'image/png','data':base64.b64encode(PNG).decode(),'path':'/private/ignored'}).encode()
        self.assertEqual(self.fetch('/api/images',{'Content-Type':'application/json'},data)[0],403)
        headers={'Content-Type':'application/json','X-Council-Token':self.server.council.token}
        code,raw=self.fetch('/api/images',headers,data);self.assertEqual(code,201);im=json.loads(raw)
        self.assertNotIn('path',im)
        self.assertEqual(self.fetch('/api/images/'+im['id'])[0],403)
        code,raw=self.fetch('/api/images/'+im['id'],headers);self.assertEqual(code,200)
        self.assertNotIn('path',json.loads(raw));self.assertEqual(base64.b64decode(json.loads(raw)['data']),PNG)
        self.assertEqual(self.fetch('/images/'+im['id'])[0],404)

    def test_job_requires_token(self):
        self.assertEqual(self.fetch("/api/capabilities")[0], 403)
        code, raw = self.fetch("/api/bootstrap")
        self.assertEqual(code, 200)
        token = json.loads(raw)["token"]
        self.assertEqual(self.fetch("/api/capabilities", {"X-Council-Token": token})[0], 200)

    def test_cross_origin_and_rebound_host_are_rejected(self):
        for headers in ({"Origin": "https://example.com"}, {"Host": "attacker.example"}, {"Sec-Fetch-Site": "cross-site"}):
            self.assertEqual(self.fetch("/api/bootstrap", headers)[0], 403)

    def test_external_document_navigation_can_open_only_the_public_homepage(self):
        navigation={'Sec-Fetch-Site':'cross-site','Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'}
        for path in ('/','/index.html'):
            self.assertEqual(self.fetch(path,navigation)[0],200)
        for path in ('/api/bootstrap','/api/capabilities','/app.js'):
            self.assertEqual(self.fetch(path,navigation)[0],403)
        for headers in ({**navigation,'Sec-Fetch-Dest':'iframe'},{**navigation,'Origin':'https://example.com'},{**navigation,'Host':'attacker.example'}):
            self.assertEqual(self.fetch('/index.html',headers)[0],403)

    def test_invalid_json_returns_structured_error(self):
        token = self.server.council.token
        headers = {"X-Council-Token": token, "Content-Type": "application/json"}
        self.assertEqual(self.fetch("/api/jobs", headers, b"not-json")[0], 400)


if __name__ == "__main__":
    unittest.main()
