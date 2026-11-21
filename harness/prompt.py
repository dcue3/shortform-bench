"""The prompt every model receives, and the parser for what comes back.

There is one system prompt and one task message. Both are identical for every
model; nothing is tuned per model. Change either and PROMPT_VERSION must change,
because scripts written under different prompts can't be compared.
"""

from __future__ import annotations

import hashlib
import re

PROMPT_VERSION = "2"   # 2: scripts are written line by line

SYSTEM = """\
You are writing the script for a short-form video (TikTok or Instagram Reels) for one specific creator.

The creator will read your script and decide whether they would film it for their own channel. Write the script this creator would actually film.

You are given three things:
1. A description of the creator's channel.
2. Transcripts of {n_past} of the creator's published videos, each with its length in seconds. They were transcribed automatically from the audio, so each one is a single unbroken block of text and may contain small transcription errors.
3. A pitch for a new video, with a target length.

Research
You have two tools: web_search and fetch_page. Use them to research the topic, so that the script is specific and its facts are right. You may make at most {max_tool_calls} tool calls in total. Every fact in the script must come from a page you opened with fetch_page.

The script
- Spoken words only: exactly what the creator says out loud, from the first word to the last. No on-screen text, stage directions, headings, speaker labels, emoji or hashtags.
- Written line by line, the way short-form creators write their scripts: one spoken line on each line of text. A line is a single beat the creator says in one breath, usually one sentence or a short phrase. Start a new line for every new beat. No paragraphs, no blank lines between lines, no bullets and no numbering.
- Written to run for the target length when this creator says it at their usual pace.
- In this creator's voice, for this creator's audience.
- Do not promise the viewer anything the creator would have to supply, such as a link, a download or a product.

Your final reply must contain exactly these two blocks and nothing else:

<script>
The full script, one spoken line per line.
</script>
<sources>
One line for each page the script relies on, in this form:
URL | the facts in the script that this page supports
</sources>
"""

FORMAT_REMINDER = """\
Your reply was not in the required format. Send your script again, unchanged, in exactly this format and nothing else:

<script>
The full script, one spoken line per line.
</script>
<sources>
URL | the facts in the script that this page supports
</sources>
"""

LIMIT_NOTICE = "You have used all {max_tool_calls} tool calls. No more tools are available. Write your final reply now."


def system_prompt(n_past: int, max_tool_calls: int) -> str:
    return SYSTEM.format(n_past=n_past, max_tool_calls=max_tool_calls)


def task_message(creator: dict, pitch: dict) -> str:
    """Everything the model is told about the creator and the pitch.

    The creator's handle, view counts, captions and video links are left out,
    so the model can't look the creator up.
    """
    lo, hi = pitch["target_length_seconds"]
    parts = ["# Channel description", "", creator["channel_description"], "", "# Past videos", ""]
    for k, video in enumerate(creator["past_scripts"], 1):
        parts += [f"## Past video {k} ({video['duration_s']} seconds)", "", video["transcript"], ""]
    parts += [
        "# Pitch for the new video", "",
        f"Title: {pitch['title']}",
        f"Topic: {pitch['topic']}",
        f"Target length: {lo} to {hi} seconds",
    ]
    return "\n".join(parts)


def prompt_sha(n_past: int, max_tool_calls: int) -> str:
    text = system_prompt(n_past, max_tool_calls) + FORMAT_REMINDER + LIMIT_NOTICE
    return hashlib.sha256(text.encode()).hexdigest()[:12]


# ---------------------------------------------------------------- parsing

_SCRIPT = re.compile(r"<script>\s*(.*?)\s*</script>", re.S | re.I)
_SOURCES = re.compile(r"<sources>\s*(.*?)\s*</sources>", re.S | re.I)
_URL = re.compile(r"https?://[^\s|<>\"')\]]+")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def parse_reply(text: str | None) -> dict | None:
    """Pull the script and the source list out of a final reply.

    Returns None when there is no usable <script> block. The script text is
    never edited: what the model wrote is what the creator reads.
    """
    if not text:
        return None
    found = _SCRIPT.findall(text)
    if not found or not found[-1].strip():
        return None
    script = found[-1].strip()
    sources = []
    block = _SOURCES.findall(text)
    if block:
        for line in block[-1].splitlines():
            urls = _URL.findall(line)
            if not urls:
                continue
            url = urls[0].rstrip(".,;")
            supports = line.split("|", 1)[1].strip() if "|" in line else line.replace(urls[0], "").strip(" -:|\t")
            sources.append({"url": url, "supports": supports})
    return {"script": script, "sources": sources}


def format_flags(script: str) -> list[str]:
    """Signs that a script contains something other than spoken words.

    These are recorded for diagnosis only. They never change the script and
    never change a score.
    """
    flags = []
    if re.search(r"^\s*#{1,6}\s", script, re.M) or "**" in script:
        flags.append("markdown")
    if re.search(r"\[[^\]]{2,}\]|\([A-Za-z ]*(?:on screen|cut to|b-roll|pause|beat)[^)]*\)", script, re.I):
        flags.append("stage_direction")
    if re.search(r"^\s*(?:hook|intro|body|outro|cta|narrator|host|creator|voiceover)\s*:", script, re.I | re.M):
        flags.append("label")
    if _EMOJI.search(script):
        flags.append("emoji")
    if re.search(r"(?<!\w)#\w+", script):
        flags.append("hashtag")
    lines = script_lines(script)
    if re.search(r"^\s*(?:[-*\u2022]|\d+[.)])\s", script, re.M):
        flags.append("bullets_or_numbers")
    if re.search(r"\n\s*\n", script.strip()):
        flags.append("blank_lines")
    # A script that is one block, or has lines far too long to say in a breath,
    # was written as paragraphs and not line by line.
    if len(lines) < 4 or max(len(line.split()) for line in lines) > LONG_LINE_WORDS:
        flags.append("not_line_by_line")
    return flags


LONG_LINE_WORDS = 40


def script_lines(script: str) -> list[str]:
    """The script's spoken lines: one per line of text, blank lines dropped."""
    return [line.strip() for line in script.splitlines() if line.strip()]


def line_stats(script: str) -> dict:
    lines = script_lines(script)
    counts = [len(line.split()) for line in lines] or [0]
    return {"lines": len(lines), "words_per_line": round(sum(counts) / len(counts), 1), "longest_line_words": max(counts)}


def word_count(script: str) -> int:
    return len(script.split())
