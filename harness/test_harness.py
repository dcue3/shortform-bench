"""Offline tests for the harness. No network, no API keys.

    python3 -m unittest harness.test_harness
"""

import json
import tempfile
import unittest
from pathlib import Path

from harness import prompt, run, tasks, tools

LIMITS = {"max_tool_calls": 3, "max_model_requests": 8, "max_output_tokens": 1000}
CREATOR = {
    "creator_id": "testcreator", "niche": "science", "channel_description": "I explain physics.",
    "past_scripts": [{"id": str(k), "duration_s": 40, "transcript": f"Past transcript {k}."} for k in range(10)],
    "pace_words_per_second": 2.0, "content_sha": "abc",
    "pitches": [{"task_id": "testcreator-01", "title": "Why the sky is blue", "topic": "Rayleigh scattering.",
                 "target_length_seconds": [4, 6]}],
}
PITCH = CREATOR["pitches"][0]
GOOD = ("<script>\nThe sky is blue.\nWhy?\nBecause air scatters blue light\nthe most.\n</script>\n"
        "<sources>\nhttps://example.org/sky | blue light scatters most\nhttps://never-opened.org/x | something else\n</sources>")


def tool_call(name, **args):
    return {"id": f"call_{name}_{len(json.dumps(args))}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class FakeClient:
    """Plays back a fixed list of assistant messages and records what it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def complete(self, model, messages, tools_, tool_choice, max_tokens, extra=None):
        self.requests.append({"tool_choice": tool_choice, "n_messages": len(messages), "last": messages[-1]})
        message = self.replies.pop(0)
        return {"message": {"role": "assistant", **message}, "finish_reason": "stop",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}, "provider": "Fake", "id": "x"}


class FakeToolbox:
    search_provider = "fake"

    def __init__(self):
        self.calls = []

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        args = json.loads(arguments)
        if name == "fetch_page":
            return "Page text.", {"ok": True, "page_id": "p1", "url": args["url"], "final_url": args["url"]}
        return "1. Result", {"ok": True, "search_id": "s1"}


def go(replies, limits=LIMITS):
    client, toolbox = FakeClient(replies), FakeToolbox()
    record = run.run_task(CREATOR, PITCH, {"id": "fake/model"}, client, toolbox, limits, "test")
    return record, client, toolbox


class LoopTests(unittest.TestCase):
    def test_search_fetch_then_script(self):
        record, client, toolbox = go([
            {"content": None, "tool_calls": [tool_call("web_search", query="why is the sky blue")]},
            {"content": None, "tool_calls": [tool_call("fetch_page", url="https://www.example.org/sky/")]},
            {"content": GOOD},
        ])
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["tool_calls_used"], 2)
        self.assertEqual(record["model_requests"], 3)
        self.assertIn("scatters blue light", record["script"])
        self.assertIn("one spoken line on each line of text", record["messages"][0]["content"])
        self.assertEqual([s["opened"] for s in record["sources"]], [True, False])
        self.assertEqual(record["sources"][0]["page_id"], "p1")
        self.assertEqual(record["length"]["words"], 12)
        self.assertEqual(record["length"]["lines"], 4)
        self.assertEqual(record["length"]["longest_line_words"], 5)
        self.assertEqual(record["format_flags"], [])
        self.assertEqual(record["length"]["estimated_seconds"], 6.0)
        self.assertTrue(record["length"]["inside_target"])
        self.assertAlmostEqual(record["usage"]["cost"], 0.03)
        self.assertEqual(record["messages"][0]["role"], "system")
        self.assertEqual(record["messages"][3]["role"], "tool")

    def test_creator_id_is_never_sent_to_the_model(self):
        record, _, _ = go([{"content": GOOD}])
        self.assertNotIn("testcreator", json.dumps(record["messages"][:2]))

    def test_tool_limit_is_enforced(self):
        four = [tool_call("web_search", query=f"q{k}") for k in range(4)]
        record, client, toolbox = go([
            {"content": None, "tool_calls": four},
            {"content": GOOD},
        ])
        self.assertEqual(len(toolbox.calls), 3)            # the fourth was never run
        self.assertEqual(record["tool_calls_used"], 3)
        self.assertEqual([c["counted"] for c in record["tool_calls"]], [True, True, True, False])
        self.assertEqual(client.requests[1]["tool_choice"], "none")
        self.assertIn("used all 3 tool calls", record["messages"][5]["content"])   # notice on the last allowed call
        self.assertNotIn("used all", record["messages"][4]["content"])
        self.assertEqual(record["status"], "ok")

    def test_one_format_reminder_then_ok(self):
        record, client, _ = go([{"content": "Here is your script: The sky is blue."}, {"content": GOOD}])
        self.assertTrue(record["format_retry"])
        self.assertEqual(record["status"], "ok")
        self.assertEqual(client.requests[1]["last"]["content"], prompt.FORMAT_REMINDER)

    def test_no_script_after_reminder(self):
        record, _, _ = go([{"content": "no tags"}, {"content": "still no tags"}])
        self.assertEqual(record["status"], "no_script")
        self.assertIsNone(record["script"])
        self.assertEqual(record["model_requests"], 2)

    def test_model_that_never_stops_calling_tools(self):
        replies = [{"content": None, "tool_calls": [tool_call("web_search", query=f"q{k}")]} for k in range(20)]
        record, _, toolbox = go(replies)
        self.assertEqual(record["status"], "no_script")
        self.assertEqual(record["model_requests"], LIMITS["max_model_requests"])
        self.assertEqual(len(toolbox.calls), 3)

    def test_service_failure_is_an_error_not_a_score(self):
        class Broken:
            def complete(self, *a, **k):
                raise RuntimeError("service down")
        record = run.run_task(CREATOR, PITCH, {"id": "fake/model"}, Broken(), FakeToolbox(), LIMITS, "test")
        self.assertEqual(record["status"], "error")
        self.assertIn("service down", record["error"])

    def test_out_of_credit_is_marked(self):
        from harness.models import OutOfCredit

        class Empty:
            def complete(self, *a, **k):
                raise OutOfCredit("no credit")
        record = run.run_task(CREATOR, PITCH, {"id": "fake/model"}, Empty(), FakeToolbox(), LIMITS, "test")
        self.assertEqual(record["status"], "error")
        self.assertTrue(record["out_of_credit"])

    def test_reasoning_blocks_are_sent_back(self):
        record, _, _ = go([
            {"content": None, "tool_calls": [tool_call("web_search", query="q")],
             "reasoning_details": [{"type": "reasoning.encrypted", "data": "zzz"}], "reasoning": "dropped"},
            {"content": GOOD},
        ])
        assistant = record["messages"][2]
        self.assertEqual(assistant["reasoning_details"][0]["data"], "zzz")
        self.assertNotIn("reasoning", assistant)


class ParseTests(unittest.TestCase):
    def test_parse_and_flags(self):
        parsed = prompt.parse_reply("Sure!\n<script>\n[Cut to b-roll] **Hi** #fyp\n</script><sources>\n- https://a.com/x. | fact\n</sources>")
        self.assertEqual(parsed["sources"], [{"url": "https://a.com/x", "supports": "fact"}])
        self.assertEqual(set(prompt.format_flags(parsed["script"])), {"markdown", "stage_direction", "hashtag", "not_line_by_line"})
        lined = "So here's the thing.\nMoney isn't real.\nNumber 1, it's debt.\nAnd number 2?\nIt's trust."
        self.assertEqual(prompt.format_flags(lined), [])
        self.assertEqual(prompt.line_stats(lined), {"lines": 5, "words_per_line": 3.2, "longest_line_words": 4})
        paragraph = " ".join(["word"] * 120)
        self.assertEqual(prompt.format_flags(paragraph), ["not_line_by_line"])
        self.assertIn("blank_lines", prompt.format_flags("One.\nTwo.\n\nThree.\nFour."))
        self.assertIn("bullets_or_numbers", prompt.format_flags("- One.\n- Two.\n- Three.\n- Four."))
        self.assertEqual(prompt.script_lines(" a \n\n b "), ["a", "b"])
        self.assertIsNone(prompt.parse_reply("<script>   </script>"))
        self.assertIsNone(prompt.parse_reply(None))

    def test_task_message(self):
        text = prompt.task_message(CREATOR, PITCH)
        self.assertIn("Target length: 4 to 6 seconds", text)
        self.assertEqual(text.count("## Past video"), 10)


class ToolTests(unittest.TestCase):
    def test_html_to_text(self):
        title, text = tools.html_to_text(
            "<html><head><title>My  page</title><style>p{}</style></head><body><nav>Menu</nav>"
            "<h1>Heading</h1><p>First&nbsp;para <a href='#'>link</a>.</p><script>var x</script>"
            "<p>Second<br>line</p><footer>Foot</footer></body></html>")
        self.assertEqual(title, "My page")
        self.assertEqual(text, "Heading\n\nFirst para link.\n\nSecond\nline")

    def test_private_addresses_are_refused(self):
        for url in ("file:///etc/passwd", "http://127.0.0.1:8000/", "http://localhost/", "http://192.168.1.1/",
                    "http://169.254.169.254/latest/meta-data/", "ftp://example.org/"):
            with self.assertRaises(tools.ToolError, msg=url):
                tools.check_public_url(url)

    def test_toolbox_saves_and_reuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            hits = []
            tools.SEARCH_PROVIDERS["fake"] = lambda q, n: hits.append(q) or [{"title": "T", "url": "https://a.org", "snippet": "S"}]
            try:
                box = tools.Toolbox(Path(tmp), "fake", 5, 100)
                text, log = box.call("web_search", '{"query": "Blue  Sky"}')
                text2, log2 = box.call("web_search", '{"query": "blue sky"}')
                self.assertEqual(hits, ["Blue Sky"])                    # second call reused the saved result
                self.assertFalse(log["reused"]); self.assertTrue(log2["reused"])
                self.assertIn("https://a.org", text)
                self.assertEqual(len(list((Path(tmp) / "searches").glob("*.json"))), 1)
                self.assertFalse(box.call("fetch_page", '{"url": "http://127.0.0.1/"}')[1]["ok"])
                self.assertFalse(box.call("web_search", "not json")[1]["ok"])
                self.assertFalse(box.call("run_code", "{}")[1]["ok"])
            finally:
                del tools.SEARCH_PROVIDERS["fake"]


class TaskTests(unittest.TestCase):
    def test_task_files_are_well_formed(self):
        creators = tasks.load_creators()
        self.assertGreaterEqual(len(creators), 1)
        ids = [p["task_id"] for _, p in tasks.iter_tasks(creators)]
        self.assertEqual(len(ids), len(set(ids)))
        for creator in creators:
            self.assertEqual(len(creator["past_scripts"]), 10)
            self.assertLessEqual(len(creator["channel_description"].split()), 150)
            self.assertEqual(creator["content_sha"], tasks.content_sha(creator))
            self.assertGreaterEqual(len(creator["pitches"]), 1)
            for pitch in creator["pitches"]:
                lo, hi = pitch["target_length_seconds"]
                self.assertTrue(20 <= lo <= hi <= 180)
                self.assertNotIn(creator["creator_id"], prompt.task_message(creator, pitch))

    def test_lock_catches_a_changed_task(self):
        lock = tasks.read_lock()
        if lock is None:
            self.skipTest("tasks are not locked")
        creators = tasks.load_creators(check=False)
        tasks.check_against_lock(creators)                       # unchanged tasks pass
        creators[0] = {**creators[0], "content_sha": "different"}
        with self.assertRaises(tasks.TasksChanged):
            tasks.check_against_lock(creators)


if __name__ == "__main__":
    unittest.main()
