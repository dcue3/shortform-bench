"""Build a single-file page for reading a round's scripts.

Pick a pitch from the dropdown, then switch between models with the tabs.
The page is self-contained: the scripts are embedded in it and nothing is
loaded from the network.
"""

from __future__ import annotations

import json

NAMES = {
    "anthropic/claude-fable-5.2": "Claude Fable 5.2",
    "anthropic/claude-opus-5.5": "Claude Opus 5.5",
    "anthropic/claude-haiku-5.5": "Claude Haiku 5.5",
    "google/gemini-4-neon": "Gemini 4 Neon",
    "google/gemini-3.8-flash": "Gemini 3.8 Flash",
    "openai/gpt-6.2-astra": "GPT-6.2 Astra",
    "openai/gpt-6.2-sol": "GPT-6.2 Sol",
    "openai/gpt-6-luna": "GPT-6 Luna",
    "meta/muse-wonder": "Muse Wonder",
    "x-ai/grok-4.7": "Grok 4.7",
    "moonshotai/kimi-k3.1-pro": "Kimi K3.1 Pro",
}


def build_data(round_name: str, records: list[dict], find_task, model_order: list[str]) -> dict:
    """Reduce run records to what the page shows."""
    rank = {model: k for k, model in enumerate(model_order)}
    pitches: dict[str, dict] = {}
    for record in records:
        task_id = record["task_id"]
        if task_id not in pitches:
            creator, pitch = find_task(task_id)
            pitches[task_id] = {
                "id": task_id, "title": pitch["title"], "topic": pitch["topic"],
                "target": pitch["target_length_seconds"], "niche": creator["niche"], "scripts": [],
            }
        length = record.get("length") or {}
        pitches[task_id]["scripts"].append({
            "model": record["model"],
            "name": NAMES.get(record["model"], record["model"].split("/")[-1]),
            "status": record["status"],
            "script": record.get("script") or "",
            "words": length.get("words"),
            "lines": length.get("lines"),
            "seconds": length.get("estimated_seconds"),
            "inside": length.get("inside_target"),
            "tools": record.get("tool_calls_used"),
            "cost": record.get("usage", {}).get("cost"),
            "took": record.get("seconds_taken"),
            "sources": [{"url": s["url"], "supports": s.get("supports", ""), "opened": s.get("opened", False)}
                        for s in record.get("sources", [])],
        })
    for pitch in pitches.values():
        pitch["scripts"].sort(key=lambda s: (rank.get(s["model"], len(rank)), s["model"]))
    return {"round": round_name, "pitches": [pitches[k] for k in sorted(pitches)]}


def render(data: dict) -> str:
    # "</" must not appear inside the embedded data, or the browser would end the block early.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.replace("__ROUND__", data["round"]).replace("__DATA__", blob)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scripts: __ROUND__</title>
<style>
  :root {
    --bg: #f6f5f1; --card: #ffffff; --ink: #1c1b19; --muted: #6b675f; --line: #e2dfd7;
    --accent: #1f5fbf; --accent-ink: #ffffff; --good: #1e7a46; --warn: #a15c00; --chip: #efede7;
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --bg: #161614; --card: #1f1f1c; --ink: #ecebe6; --muted: #a09c92; --line: #33322d;
      --accent: #7fb0ff; --accent-ink: #10141c; --good: #6fd29a; --warn: #f0b35a; --chip: #2a2a26;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
         font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  main { max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }
  h1 { font-size: 15px; font-weight: 600; color: var(--muted); margin: 0 0 14px; letter-spacing: .02em; }
  .bar { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  select { flex: 1 1 320px; min-width: 0; font: inherit; font-weight: 600; padding: 10px 12px; color: var(--ink);
           background: var(--card); border: 1px solid var(--line); border-radius: 10px; }
  label.blind { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 14px; white-space: nowrap; cursor: pointer; }
  .pitch { margin: 14px 0 18px; padding: 14px 16px; background: var(--card); border: 1px solid var(--line); border-radius: 12px; }
  .pitch p { margin: 0 0 8px; }
  .chips { display: flex; gap: 8px; flex-wrap: wrap; }
  .chip { background: var(--chip); border-radius: 999px; padding: 2px 10px; font-size: 13px; color: var(--muted); }
  .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
  .tab { font: inherit; font-size: 14px; padding: 7px 12px; border-radius: 999px; cursor: pointer;
         color: var(--ink); background: var(--card); border: 1px solid var(--line); }
  .tab[aria-selected="true"] { background: var(--accent); color: var(--accent-ink); border-color: var(--accent); font-weight: 600; }
  .tab:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .panel { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; }
  .meta { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  .meta .ok { color: var(--good); } .meta .off { color: var(--warn); }
  .script p { margin: 0; padding: 7px 0; font-size: 17px; line-height: 1.5; border-bottom: 1px solid var(--line); }
  .script p:last-child { border-bottom: 0; }
  .none { color: var(--muted); font-style: italic; }
  h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin: 22px 0 8px; }
  ul.sources { margin: 0; padding: 0; list-style: none; }
  ul.sources li { padding: 8px 0; border-top: 1px solid var(--line); font-size: 14px; }
  ul.sources a { color: var(--accent); word-break: break-all; }
  ul.sources .sup { color: var(--muted); margin-top: 2px; }
  .hint { color: var(--muted); font-size: 13px; margin-top: 14px; }
</style>
</head>
<body>
<main>
  <h1>Scripts from round __ROUND__</h1>
  <div class="bar">
    <select id="pitch" aria-label="Pitch"></select>
    <label class="blind"><input type="checkbox" id="blind"> Hide model names</label>
  </div>
  <section class="pitch" id="pitchInfo"></section>
  <div class="tabs" id="tabs" role="tablist" aria-label="Models"></div>
  <section class="panel" id="panel" role="tabpanel"></section>
  <p class="hint">Left and right arrow keys switch between scripts. The same model stays selected when you change pitch.</p>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById("data").textContent);
  var pitchSel = document.getElementById("pitch"), blindBox = document.getElementById("blind");
  var tabsEl = document.getElementById("tabs"), panel = document.getElementById("panel"), info = document.getElementById("pitchInfo");
  var state = { pitch: 0, model: null, slot: 0 };

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  // In blind mode the order is shuffled the same way every time for a given pitch.
  function order(pitch) {
    var list = pitch.scripts.slice();
    if (!blindBox.checked) return list;
    var seed = 0;
    for (var i = 0; i < pitch.id.length; i++) seed = (seed * 31 + pitch.id.charCodeAt(i)) >>> 0;
    function rand() { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; }
    for (var j = list.length - 1; j > 0; j--) {
      var k = Math.floor(rand() * (j + 1)), tmp = list[j]; list[j] = list[k]; list[k] = tmp;
    }
    return list;
  }

  function current() {
    var list = order(data.pitches[state.pitch]);
    var at = blindBox.checked ? state.slot : list.findIndex(function (s) { return s.model === state.model; });
    if (at < 0 || at >= list.length) at = 0;
    return { list: list, at: at };
  }

  function draw() {
    var pitch = data.pitches[state.pitch], cur = current(), list = cur.list, at = cur.at, blind = blindBox.checked;
    state.slot = at; if (!blind) state.model = list[at].model;

    info.replaceChildren();
    info.appendChild(el("p", null, pitch.topic));
    var chips = el("div", "chips");
    chips.appendChild(el("span", "chip", "Target " + pitch.target[0] + "–" + pitch.target[1] + " seconds"));
    chips.appendChild(el("span", "chip", pitch.niche));
    chips.appendChild(el("span", "chip", pitch.id));
    info.appendChild(chips);

    tabsEl.replaceChildren();
    list.forEach(function (s, i) {
      var tab = el("button", "tab", blind ? "Script " + (i + 1) : s.name);
      tab.type = "button"; tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", i === at ? "true" : "false");
      tab.tabIndex = i === at ? 0 : -1;
      tab.addEventListener("click", function () { pick(i); });
      tabsEl.appendChild(tab);
    });

    var s = list[at];
    panel.replaceChildren();
    var meta = el("div", "meta");
    if (s.words != null) meta.appendChild(el("span", "chip", s.words + " words"));
    if (s.lines != null) meta.appendChild(el("span", "chip", s.lines + " lines"));
    if (s.seconds != null) {
      var len = el("span", "chip " + (s.inside ? "ok" : "off"),
        "about " + Math.round(s.seconds) + " s" + (s.inside ? ", inside target" : ", outside target"));
      meta.appendChild(len);
    }
    if (!blind) {
      if (s.tools != null) meta.appendChild(el("span", "chip", s.tools + " tool calls"));
      if (s.cost != null) meta.appendChild(el("span", "chip", "$" + (s.cost < 0.01 ? s.cost.toFixed(3) : s.cost.toFixed(2))));
      if (s.took != null) meta.appendChild(el("span", "chip", Math.round(s.took) + " s to write"));
    }
    panel.appendChild(meta);

    var body = el("div", "script");
    if (s.status !== "ok" || !s.script) {
      body.appendChild(el("p", "none", "No script was returned for this pitch."));
    } else {
      // One row per spoken line, exactly as the model broke them.
      s.script.split(/\n/).forEach(function (line) {
        if (line.trim()) body.appendChild(el("p", null, line.trim()));
      });
    }
    panel.appendChild(body);

    if (s.sources && s.sources.length) {
      panel.appendChild(el("h2", null, "Sources (" + s.sources.length + ")"));
      var ul = el("ul", "sources");
      s.sources.forEach(function (src) {
        var li = el("li");
        var a = el("a", null, src.url + (src.opened ? "" : "  (not opened in this run)"));
        if (/^https?:\/\//i.test(src.url)) { a.href = src.url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
        li.appendChild(a);
        if (src.supports) li.appendChild(el("div", "sup", src.supports));
        ul.appendChild(li);
      });
      panel.appendChild(ul);
    }
  }

  function pick(i) {
    var list = order(data.pitches[state.pitch]);
    state.slot = i; state.model = list[i].model; draw();
    var tabs = tabsEl.querySelectorAll(".tab"); if (tabs[i]) tabs[i].focus();
  }

  data.pitches.forEach(function (p, i) {
    var opt = el("option", null, p.title); opt.value = String(i); pitchSel.appendChild(opt);
  });
  pitchSel.addEventListener("change", function () { state.pitch = Number(pitchSel.value); draw(); });
  blindBox.addEventListener("change", function () { state.slot = 0; draw(); });
  document.addEventListener("keydown", function (e) {
    if (e.target === pitchSel || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    var cur = current(), n = cur.list.length;
    pick((cur.at + (e.key === "ArrowRight" ? 1 : n - 1)) % n); e.preventDefault();
  });
  draw();
})();
</script>
</body>
</html>
"""
