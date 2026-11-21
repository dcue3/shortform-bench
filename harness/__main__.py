"""Command line for the harness.

    python3 -m harness prompt <task id>
    python3 -m harness run --round dev --models <model id> --tasks <task id>
    python3 -m harness status --round dev
    python3 -m harness show <model id> <task id> --round dev
    python3 -m harness viewer --round dev
    python3 -m harness export --round dev
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import prompt, run, tasks, viewer
from .models import OpenRouter
from .tools import Toolbox

ROOT = Path(__file__).parent


def load_config() -> dict:
    return json.loads((ROOT / "config.json").read_text())


def pick_models(cfg: dict, wanted: str | None) -> list[dict]:
    """The lineup in config.json, or the models named with --models.

    "all" means the lineup plus the extra models. Settings for a named model
    are looked up in both lists, so extras run with their configured settings.
    """
    lineup = cfg.get("models", [])
    known = {m["id"]: m for m in lineup + cfg.get("extra_models", [])}
    if wanted == "all":
        return list(known.values())
    if wanted:
        return [known.get(m, {"id": m}) for m in wanted.split(",") if m]
    return list(lineup)


def pick_tasks(args) -> list[tuple[dict, dict]]:
    chosen = list(tasks.iter_tasks(tasks.load_creators()))
    if args.creators:
        keep = set(args.creators.split(","))
        chosen = [(c, p) for c, p in chosen if c["creator_id"] in keep]
    if args.tasks:
        keep = set(args.tasks.split(","))
        chosen = [(c, p) for c, p in chosen if p["task_id"] in keep]
    if args.pitches:
        keep = {int(n) for n in args.pitches.split(",")}
        chosen = [(c, p) for c, p in chosen if int(p["task_id"].rsplit("-", 1)[1]) in keep]
    return chosen


def cmd_prompt(args) -> int:
    cfg = load_config()
    creator, pitch = tasks.find_task(args.task_id)
    print("=" * 30, "SYSTEM", "=" * 30)
    print(prompt.system_prompt(len(creator["past_scripts"]), cfg["limits"]["max_tool_calls"]))
    print("=" * 30, "TASK", "=" * 30)
    print(prompt.task_message(creator, pitch))
    return 0


def cmd_run(args) -> int:
    cfg = load_config()
    round_name = args.round or cfg["round"]
    models = pick_models(cfg, args.models)
    if not models:
        print("No models chosen. List them in config.json or pass --models.", file=sys.stderr)
        return 2
    chosen = pick_tasks(args)
    done = run.load_done(round_name)
    todo = [(m, c, p) for m in models for c, p in chosen
            if args.redo or done.get((m["id"], p["task_id"]), {}).get("status") not in ("ok", "no_script")]
    spent = sum(r.get("usage", {}).get("cost", 0) for r in done.values())
    budget = args.budget if args.budget is not None else cfg["budget_usd"]
    print(f"round {round_name}: {len(models)} model(s) x {len(chosen)} task(s); {len(todo)} to run; "
          f"${spent:.2f} spent of ${budget:.2f}")
    if args.dry or not todo:
        return 0

    client = OpenRouter(cfg["limits"]["request_timeout_s"], cfg.get("openrouter"))
    toolbox = Toolbox(run.RUNS / round_name, args.search or cfg["search"]["provider"],
                      cfg["limits"]["search_results"], cfg["limits"]["page_chars"])
    lock = threading.Lock()
    state = {"spent": spent, "stopped": False, "no_credit": False}

    def one(model, creator, pitch):
        with lock:
            if state["no_credit"]:
                return None
            if state["spent"] >= budget:
                state["stopped"] = True
                return None
        record = run.run_task(creator, pitch, model, client, toolbox, cfg["limits"], round_name)
        run.save(record)
        with lock:
            state["spent"] += record["usage"].get("cost", 0)
            state["no_credit"] = state["no_credit"] or bool(record.get("out_of_credit"))
        return record

    with ThreadPoolExecutor(max_workers=args.workers or cfg["workers"]) as pool:
        futures = [pool.submit(one, m, c, p) for m, c, p in todo]
        for future in as_completed(futures):
            record = future.result()
            if record is None:
                continue
            length = record.get("length") or {}
            print(f"  {record['status']:9} {record['model']:38} {record['task_id']:28} "
                  f"{record['tool_calls_used']:2} tools  {length.get('words', 0):4} words  {length.get('lines', 0):3} lines  "
                  f"~{length.get('estimated_seconds') or 0:5.0f}s  ${record['usage'].get('cost', 0):.3f}  "
                  f"{record['seconds_taken']:.0f}s {(record['error'] or '')[:150]}")
    if state["no_credit"]:
        print("Stopped: the OpenRouter account is out of credit. Unstarted tasks were skipped; "
              "rerun the same command after topping up.", file=sys.stderr)
    if state["stopped"]:
        print(f"Stopped: the ${budget:.2f} budget for this round is used up.", file=sys.stderr)
    print(f"spent in this round so far: ${state['spent']:.2f}")
    return 0


def cmd_status(args) -> int:
    cfg = load_config()
    round_name = args.round or cfg["round"]
    done = run.load_done(round_name)
    if not done:
        print(f"round {round_name}: nothing run yet")
        return 0
    by_model: dict[str, list[dict]] = {}
    for (model_id, _), record in sorted(done.items()):
        by_model.setdefault(model_id, []).append(record)
    print(f"round {round_name}")
    print(f"{'model':40} {'ok':>4} {'none':>5} {'err':>4} {'tools':>6} {'in len':>7} {'unopened src':>13} {'cost':>8}")
    for model_id, records in by_model.items():
        ok = [r for r in records if r["status"] == "ok"]
        tools = sum(r["tool_calls_used"] for r in records) / len(records)
        inside = sum(1 for r in ok if r["length"]["inside_target"])
        sources = [s for r in ok for s in r["sources"]]
        unopened = sum(1 for s in sources if not s["opened"])
        cost = sum(r["usage"].get("cost", 0) for r in records)
        print(f"{model_id:40} {len(ok):4} {sum(r['status'] == 'no_script' for r in records):5} "
              f"{sum(r['status'] == 'error' for r in records):4} {tools:6.1f} "
              f"{inside:3}/{len(ok):<3} {unopened:6}/{len(sources):<6} ${cost:7.2f}")
    return 0


def cmd_export(args) -> int:
    """Write every script in a round to one readable file, grouped by pitch."""
    cfg = load_config()
    round_name = args.round or cfg["round"]
    done = run.load_done(round_name)
    if not done:
        print(f"round {round_name}: nothing to export", file=sys.stderr)
        return 1
    by_task: dict[str, list[dict]] = {}
    for record in done.values():
        by_task.setdefault(record["task_id"], []).append(record)
    out = [f"# Scripts from round `{round_name}`", "",
           "Every script in the round, grouped by pitch, with the model named. For reading and comparing; "
           "this is not the blind form creators will get.", ""]
    for task_id in sorted(by_task):
        creator, pitch = tasks.find_task(task_id)
        lo, hi = pitch["target_length_seconds"]
        out += [f"## {pitch['title']}", "",
                f"`{task_id}` · {creator['niche']} · target {lo}–{hi} seconds", "", pitch["topic"], ""]
        for record in sorted(by_task[task_id], key=lambda r: r["model"]):
            length = record.get("length") or {}
            facts = [f"{length.get('words', 0)} words", f"{length.get('lines', '?')} lines",
                     f"about {length.get('estimated_seconds') or 0:.0f} s",
                     f"{record['tool_calls_used']} tool calls", f"${record['usage'].get('cost', 0):.2f}",
                     f"{record['seconds_taken']:.0f} s to write"]
            out += [f"### {record['model']}", "", " · ".join(facts), ""]
            if record["status"] != "ok":
                out += [f"*No script ({record['status']}).*", ""]
                continue
            # Two trailing spaces keep each spoken line on its own line in Markdown.
            out += ["> " + line + "  " for line in prompt.script_lines(record["script"])]
            out += ["", "Sources:"]
            out += [f"- {'' if s['opened'] else '(not opened) '}{s['url']}" for s in record["sources"]] or ["- none listed"]
            out.append("")
    path = run.RUNS / round_name / "scripts.md"
    path.write_text("\n".join(out))
    print(f"wrote {path.relative_to(ROOT.parent)}: {len(done)} scripts across {len(by_task)} pitches")
    return 0


def cmd_viewer(args) -> int:
    """Write a one-file page for reading a round: pick a pitch, switch between models."""
    cfg = load_config()
    round_name = args.round or cfg["round"]
    done = run.load_done(round_name)
    if not done:
        print(f"round {round_name}: nothing to show", file=sys.stderr)
        return 1
    order = [m["id"] for m in cfg.get("models", []) + cfg.get("extra_models", [])]
    data = viewer.build_data(round_name, list(done.values()), tasks.find_task, order)
    path = run.RUNS / round_name / "viewer.html"
    path.write_text(viewer.render(data))
    print(f"wrote {path.relative_to(ROOT.parent)}: {len(done)} scripts across {len(data['pitches'])} pitches")
    return 0


def cmd_show(args) -> int:
    cfg = load_config()
    path = run.run_path(args.round or cfg["round"], args.model, args.task_id)
    if not path.exists():
        print(f"No saved run at {path}", file=sys.stderr)
        return 1
    record = json.loads(path.read_text())
    creator, pitch = tasks.find_task(args.task_id)
    print(f"{record['model']}  |  {record['task_id']}  |  {record['status']}  |  "
          f"{record['tool_calls_used']} tool calls  |  ${record['usage'].get('cost', 0):.3f}  |  {record['seconds_taken']}s")
    print(f"Pitch: {pitch['title']} ({pitch['target_length_seconds'][0]}-{pitch['target_length_seconds'][1]}s)")
    if record.get("length"):
        print(f"Length: {record['length']['words']} words in {record['length'].get('lines', '?')} lines, "
              f"about {record['length']['estimated_seconds']}s at this creator's pace")
    if record.get("format_flags"):
        print("Format flags:", ", ".join(record["format_flags"]))
    print("\nTOOL CALLS")
    for call in record["tool_calls"]:
        print(f"  {call['n']:2}. {call['name']}  {call['arguments']}  {'' if call['ok'] else '-> ' + str(call.get('error'))}")
    print("\nSCRIPT\n")
    print(record["script"] or "(none)")
    print("\nSOURCES")
    for source in record["sources"]:
        print(f"  {'opened  ' if source['opened'] else 'NOT OPENED'}  {source['url']}\n      {source['supports']}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m harness", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prompt", help="print the exact prompt for one task")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_prompt)
    p = sub.add_parser("run", help="generate scripts")
    p.add_argument("--round")
    p.add_argument("--models", help='comma-separated OpenRouter model ids, or "all" for the lineup plus extra_models (default: the lineup in config.json)')
    p.add_argument("--creators", help="comma-separated creator ids")
    p.add_argument("--tasks", help="comma-separated task ids")
    p.add_argument("--pitches", help="comma-separated pitch numbers, 1-10")
    p.add_argument("--search", help="search provider, overriding config.json")
    p.add_argument("--workers", type=int)
    p.add_argument("--budget", type=float, help="stop when the round has cost this many dollars")
    p.add_argument("--redo", action="store_true", help="run again even if a script is saved")
    p.add_argument("--dry", action="store_true", help="only say what would run")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status", help="summary of a round")
    p.add_argument("--round")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("export", help="write all of a round's scripts to one readable file")
    p.add_argument("--round")
    p.set_defaults(func=cmd_export)
    p = sub.add_parser("viewer", help="write a page for reading a round's scripts by pitch and model")
    p.add_argument("--round")
    p.set_defaults(func=cmd_viewer)
    p = sub.add_parser("show", help="print one script with its sources and tool calls")
    p.add_argument("model")
    p.add_argument("task_id")
    p.add_argument("--round")
    p.set_defaults(func=cmd_show)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except tasks.TasksChanged as err:
        print(f"Stopped: {err}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
