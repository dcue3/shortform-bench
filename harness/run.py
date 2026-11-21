"""The run loop: one model writes one script for one task.

    send the prompt
    while the model asks for tools:  run them, send the results back
    read the final reply, pull out the script and sources, save everything

The model client and the toolbox are passed in, so the loop can be tested
without the network.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import VERSION, prompt
from .tools import TOOL_SPECS

ROOT = Path(__file__).parent
RUNS = ROOT / "data" / "runs"
KEEP_FROM_ASSISTANT = ("role", "content", "tool_calls", "reasoning_details")


def slug(model_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model_id)


def run_path(round_name: str, model_id: str, task_id: str) -> Path:
    return RUNS / round_name / "scripts" / slug(model_id) / f"{task_id}.json"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _add_usage(total: dict, usage: dict) -> None:
    for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cost"):
        value = usage.get(key)
        if isinstance(value, (int, float)):
            total[key] = round(total.get(key, 0) + value, 6)
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if isinstance(reasoning, (int, float)):
        total["reasoning_tokens"] = total.get("reasoning_tokens", 0) + reasoning


def _norm_url(url: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", url.strip().lower()).rstrip("/")


def run_task(creator: dict, pitch: dict, model: dict, client, toolbox, limits: dict, round_name: str) -> dict:
    """Run one task with one model and return the full record. Never raises for model output."""
    max_calls = limits["max_tool_calls"]
    n_past = len(creator["past_scripts"])
    messages = [
        {"role": "system", "content": prompt.system_prompt(n_past, max_calls)},
        {"role": "user", "content": prompt.task_message(creator, pitch)},
    ]
    record = {
        "task_id": pitch["task_id"], "creator": creator["creator_id"], "niche": creator["niche"],
        "model": model["id"], "model_settings": model.get("settings") or {}, "round": round_name,
        "harness_version": VERSION, "prompt_version": prompt.PROMPT_VERSION,
        "prompt_sha": prompt.prompt_sha(n_past, max_calls), "task_content_sha": creator.get("content_sha"),
        "search_provider": getattr(toolbox, "search_provider", None), "limits": limits,
        "started": _now(), "status": None, "script": None, "sources": [],
        "tool_calls": [], "model_requests": 0, "format_retry": False, "providers": [],
        "usage": {}, "finish_reason": None, "error": None,
    }
    started = time.time()
    calls_used = 0
    final_text = None

    def ask(tool_choice: str) -> dict:
        reply = client.complete(model["id"], messages, TOOL_SPECS, tool_choice,
                                limits["max_output_tokens"], model.get("settings"))
        record["model_requests"] += 1
        _add_usage(record["usage"], reply.get("usage") or {})
        if reply.get("provider") and reply["provider"] not in record["providers"]:
            record["providers"].append(reply["provider"])
        record["finish_reason"] = reply.get("finish_reason")
        # The assistant turn goes back exactly as it came, including any
        # reasoning blocks, which some providers need to continue a tool loop.
        message = {k: reply["message"][k] for k in KEEP_FROM_ASSISTANT if reply["message"].get(k) is not None}
        message.setdefault("role", "assistant")
        messages.append(message)
        return message

    try:
        while record["model_requests"] < limits["max_model_requests"]:
            tools_open = calls_used < max_calls
            message = ask("auto" if tools_open else "none")
            calls = message.get("tool_calls") or []
            if not calls:
                final_text = message.get("content")
                break
            for call in calls:
                function = call.get("function") or {}
                if calls_used >= max_calls:
                    text, log = prompt.LIMIT_NOTICE.format(max_tool_calls=max_calls), {"ok": False, "error": "over limit"}
                    counted = False
                else:
                    text, log = toolbox.call(function.get("name"), function.get("arguments"))
                    calls_used += 1
                    counted = True
                    if calls_used == max_calls:
                        text += "\n\n" + prompt.LIMIT_NOTICE.format(max_tool_calls=max_calls)
                record["tool_calls"].append({"n": len(record["tool_calls"]) + 1, "counted": counted,
                                             "name": function.get("name"), "arguments": function.get("arguments"), **log})
                messages.append({"role": "tool", "tool_call_id": call.get("id"), "content": text})

        parsed = prompt.parse_reply(final_text if isinstance(final_text, str) else None)
        if parsed is None and final_text is not None and record["model_requests"] < limits["max_model_requests"]:
            # One fixed reminder about the reply format. Nothing about the content.
            record["format_retry"] = True
            messages.append({"role": "user", "content": prompt.FORMAT_REMINDER})
            retry = ask("none")
            parsed = prompt.parse_reply(retry.get("content") if isinstance(retry.get("content"), str) else None)

        if parsed is None:
            record["status"] = "no_script"
        else:
            record["status"] = "ok"
            record["script"] = parsed["script"]
            opened = {_norm_url(u) for c in record["tool_calls"] if c.get("name") == "fetch_page" and c.get("ok")
                      for u in (c.get("url") or "", c.get("final_url") or "")}
            page_ids = {_norm_url(u): c["page_id"] for c in record["tool_calls"]
                        if c.get("name") == "fetch_page" and c.get("ok")
                        for u in (c.get("url") or "", c.get("final_url") or "")}
            for source in parsed["sources"]:
                key = _norm_url(source["url"])
                record["sources"].append({**source, "opened": key in opened, "page_id": page_ids.get(key)})
            words = prompt.word_count(parsed["script"])
            lo, hi = pitch["target_length_seconds"]
            seconds = round(words / creator["pace_words_per_second"], 1) if creator.get("pace_words_per_second") else None
            record["length"] = {"words": words, "estimated_seconds": seconds, "target_seconds": [lo, hi],
                                "inside_target": None if seconds is None else lo <= seconds <= hi,
                                **prompt.line_stats(parsed["script"])}
            record["format_flags"] = prompt.format_flags(parsed["script"])
    except Exception as err:  # a failure of the service, not of the model's writing
        record["status"] = "error"
        record["error"] = f"{type(err).__name__}: {err}"[:600]
        record["out_of_credit"] = bool(getattr(err, "out_of_credit", False))

    record["tool_calls_used"] = calls_used
    record["finished"] = _now()
    record["seconds_taken"] = round(time.time() - started, 1)
    record["messages"] = messages
    return record


def save(record: dict) -> Path:
    path = run_path(record["round"], record["model"], record["task_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
    return path


def load_done(round_name: str) -> dict[tuple[str, str], dict]:
    """Every saved record in a round, keyed by (model id, task id)."""
    done = {}
    for path in (RUNS / round_name / "scripts").glob("*/*.json"):
        record = json.loads(path.read_text())
        done[(record["model"], record["task_id"])] = record
    return done
