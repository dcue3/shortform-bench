"""Load benchmark tasks.

A task is one creator plus one pitch. Tasks are stored one file per creator:

    {
      "creator_id": "example-finance",
      "niche": "personal finance and business",
      "channel_description": "...",              up to 150 words, first person
      "past_scripts": [                          ten published videos
        {"id": "past-01", "duration_s": 74, "transcript": "..."}
      ],
      "pace_words_per_second": 3.4,              the creator's speaking pace (not shown to the model)
      "pitches": [
        {"task_id": "example-finance-01", "title": "...", "topic": "...", "target_length_seconds": [60, 90]}
      ],
      "content_sha": "..."                       fingerprint of everything the model is shown
    }

The benchmark's 250 tasks are private. Three example tasks are in examples/tasks/.
The harness reads harness/data/tasks/ when it exists and examples/tasks/ otherwise.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).parent
LOCK = ROOT / "tasks.lock.json"
_PRIVATE = ROOT / "data" / "tasks"
_EXAMPLES = ROOT.parent / "examples" / "tasks"


class TasksChanged(RuntimeError):
    """The tasks no longer match what the creators approved."""


def tasks_dir() -> Path:
    return _PRIVATE if _PRIVATE.exists() else _EXAMPLES


def content_sha(creator: dict) -> str:
    """Fingerprint of what a model is shown for this creator's tasks."""
    shown = json.dumps([creator["channel_description"], creator["past_scripts"], creator["pitches"]], sort_keys=True)
    return hashlib.sha256(shown.encode()).hexdigest()[:12]


def read_lock() -> dict | None:
    return json.loads(LOCK.read_text()) if LOCK.exists() else None


def check_against_lock(creators: list[dict]) -> None:
    """Raise if any task differs from the version the creators approved."""
    lock = read_lock()
    if lock is None:
        return
    now = {c["creator_id"]: c["content_sha"] for c in creators}
    changed = sorted(k for k in set(now) | set(lock["creators"]) if now.get(k) != lock["creators"].get(k))
    if changed:
        raise TasksChanged(
            f"Tasks were locked on {lock['locked_on']} and these creators' tasks no longer match: "
            f"{', '.join(changed)}. Scripts written from changed tasks can't be compared with the rest."
        )


def load_creators(check: bool = True) -> list[dict]:
    folder = tasks_dir()
    files = sorted(folder.glob("*.json")) if folder.exists() else []
    if not files:
        raise FileNotFoundError(f"No task files found in {folder}")
    creators = [json.loads(p.read_text()) for p in files]
    if check and folder == _PRIVATE:
        check_against_lock(creators)
    return creators


def iter_tasks(creators: list[dict]):
    """Yield (creator, pitch) for every task."""
    for creator in creators:
        for pitch in creator["pitches"]:
            yield creator, pitch


def find_task(task_id: str) -> tuple[dict, dict]:
    for creator, pitch in iter_tasks(load_creators()):
        if pitch["task_id"] == task_id:
            return creator, pitch
    raise KeyError(f"No task with id {task_id}")
