"""The two tools every model gets: web_search and fetch_page.

Both run on this machine, not on the model provider's side, so every model
searches the same index and reads pages through the same reader. Everything a
model sees is saved:

  data/runs/<round>/searches/<id>.json   one file per distinct query
  data/runs/<round>/pages/<id>.json      one file per distinct URL

Within a round the first result for a query or URL is reused for every later
call, so two models that ask the same thing get the same answer.

Standard library only.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import ipaddress
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

USER_AGENT = "Mozilla/5.0 (compatible; research-page-reader/0.1)"
MAX_BYTES = 3_000_000
MIN_USEFUL_CHARS = 200

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Returns the top results, each with a title, URL and short snippet.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query."}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetch_page",
            "description": "Open a web page and return its text. Long pages are cut off.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Full URL of the page, starting with http:// or https://."}},
                "required": ["url"],
            },
        },
    },
]


class ToolError(Exception):
    """A failure the model is told about as the tool's result."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _post_json(url: str, body: dict, headers: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as err:
        raise ToolError(f"HTTP {err.code} from {urllib.parse.urlsplit(url).netloc}") from err
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise ToolError(f"could not reach {urllib.parse.urlsplit(url).netloc}: {err}") from err


# ---------------------------------------------------------------- search

def search_tavily(query: str, n: int) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set. Set it, or change search.provider in config.json.")
    data = _post_json(
        "https://api.tavily.com/search",
        {"query": query, "max_results": n, "search_depth": "basic", "topic": "general",
         "include_answer": False, "include_raw_content": False},
        {"Authorization": "Bearer " + key},
    )
    return [{"title": r.get("title") or "", "url": r["url"], "snippet": r.get("content") or ""}
            for r in data.get("results", []) if r.get("url")][:n]


def search_serper_composio(query: str, n: int) -> list[dict]:
    """Google results through Serper, called through the Composio command-line tool.

    A stand-in for trying the harness out before a search key exists. It starts
    a new process for every search, so it is slow.
    """
    body = json.dumps({"query": query, "result_count": n, "country_code": "us", "language_code": "en"})
    try:
        proc = subprocess.run(["composio", "execute", "SERPER_SEARCH_WEB", "-d", body],
                              capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise ToolError(f"search failed: {err}") from err
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError as err:
        raise ToolError("search returned no readable result") from err
    if not out.get("successful"):
        raise ToolError(f"search failed: {str(out.get('error'))[:200]}")
    rows = (out.get("data") or {}).get("organic_results") or []
    return [{"title": r.get("title") or "", "url": r["link"], "snippet": r.get("snippet") or ""}
            for r in rows if r.get("link")][:n]


SEARCH_PROVIDERS = {"tavily": search_tavily, "serper_composio": search_serper_composio}


# ---------------------------------------------------------------- page reading

class _TextExtractor(HTMLParser):
    """Turn an HTML page into plain text: drop scripts, menus and footers, keep paragraphs."""

    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "nav", "footer", "aside", "form", "button", "select"}
    BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "main", "header",
             "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "figcaption", "dt", "dd"}
    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed", "track"}
    MAIN = {"main", "article"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.main_parts: list[str] = []      # text inside <main> or <article>, when the page has one
        self.title = ""
        self._skip_depth = 0
        self._main_depth = 0
        self._in_title = False

    def _add(self, text: str) -> None:
        self.parts.append(text)
        if self._main_depth:
            self.main_parts.append(text)

    def handle_starttag(self, tag, attrs):
        if tag in self.VOID:
            if tag == "br":
                self._add("\n")
            return
        if tag in self.MAIN:
            self._main_depth += 1
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self._add("\n")
        if tag in self.MAIN:
            self._main_depth = max(0, self._main_depth - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self._add(data)


def _tidy(parts: list[str]) -> str:
    text = "".join(parts)
    text = re.sub(r"[ \t\r\f\v ]+", " ", text)
    text = re.sub(r" ?\n ?", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def html_to_text(markup: str) -> tuple[str, str]:
    """Return (title, text) for an HTML document."""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # malformed HTML: keep whatever was read so far
        pass
    whole, main = _tidy(parser.parts), _tidy(parser.main_parts)
    # Use the page's main content area when it has one and it holds a fair share of the text.
    text = main if len(main) >= max(MIN_USEFUL_CHARS, 0.3 * len(whole)) else whole
    return " ".join(parser.title.split()), text


def check_public_url(url: str) -> None:
    """Refuse anything that is not an ordinary public web address.

    The model chooses the URL, so this stops it reaching files or services on
    this machine or the local network.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("only http:// and https:// web pages can be opened")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except OSError as err:
        raise ToolError(f"could not find the site {parts.hostname}") from err
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if not address.is_global:
            raise ToolError("that address is not a public web page")


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_direct(url: str, timeout: int = 30) -> dict:
    """Download a page ourselves and turn it into text."""
    check_public_url(url)
    opener = urllib.request.build_opener(_CheckedRedirects())
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en",
    })
    try:
        with opener.open(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
            if (resp.headers.get("Content-Encoding") or "").lower() == "gzip":
                raw = gzip.decompress(raw)
            final_url = resp.geturl()
            charset = resp.headers.get_content_charset()
    except urllib.error.HTTPError as err:
        raise ToolError(f"the site answered with HTTP {err.code}") from err
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as err:
        raise ToolError(f"could not load the page ({type(err).__name__})") from err
    kind = content_type.split(";")[0].strip()
    if kind and not (kind.startswith("text/") or kind in ("application/xhtml+xml", "application/json", "application/xml")):
        raise ToolError(f"the page is not text (it is {kind})")
    if not charset:
        found = re.search(rb"charset=[\"']?([\w-]+)", raw[:4096])
        charset = found.group(1).decode("ascii", "replace") if found else "utf-8"
    try:
        body = raw.decode(charset, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")
    if kind in ("text/plain", "application/json"):
        title, text = "", body.strip()
    else:
        title, text = html_to_text(body)
    return {"final_url": final_url, "title": html.unescape(title), "text": text, "via": "direct"}


def fetch_tavily(url: str) -> dict:
    """Second reader, used only when ours fails: Tavily's page extractor."""
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise ToolError("no second page reader is configured")
    check_public_url(url)
    data = _post_json("https://api.tavily.com/extract", {"urls": [url], "format": "text"},
                      {"Authorization": "Bearer " + key}, timeout=90)
    results = data.get("results") or []
    if not results or not (results[0].get("raw_content") or "").strip():
        raise ToolError("the page could not be read")
    return {"final_url": results[0].get("url") or url, "title": "", "text": results[0]["raw_content"].strip(), "via": "tavily"}


def fetch_serper_composio(url: str) -> dict:
    """Second reader for the Serper stand-in: Serper's page reader, through the Composio command-line tool."""
    check_public_url(url)
    try:
        proc = subprocess.run(["composio", "execute", "SERPER_SCRAPE_WEBPAGE", "-d", json.dumps({"url": url})],
                              capture_output=True, text=True, timeout=120)
        out = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        raise ToolError("the page could not be read") from err
    data = out.get("data") or {}
    text = (data.get("markdown") or data.get("text") or "").strip()
    if not out.get("successful") or not text:
        raise ToolError("the page could not be read")
    title = ((data.get("metadata") or {}).get("title") or "") if isinstance(data.get("metadata"), dict) else ""
    return {"final_url": url, "title": title, "text": text, "via": "serper"}


# The second reader goes with the search provider, so a round uses one outside service.
SECOND_READERS = {"tavily": fetch_tavily, "serper_composio": fetch_serper_composio}


# ---------------------------------------------------------------- toolbox

class Toolbox:
    """Runs tool calls for one round and saves everything the models saw."""

    def __init__(self, round_dir: Path, search_provider: str, n_results: int, page_chars: int):
        if search_provider not in SEARCH_PROVIDERS:
            raise ValueError(f"Unknown search provider {search_provider!r}. Choose from {sorted(SEARCH_PROVIDERS)}.")
        self.search_provider = search_provider
        self._search = SEARCH_PROVIDERS[search_provider]
        self._second_reader = SECOND_READERS.get(search_provider)
        self.n_results = n_results
        self.page_chars = page_chars
        self.pages = round_dir / "pages"
        self.searches = round_dir / "searches"
        self.pages.mkdir(parents=True, exist_ok=True)
        self.searches.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._in_flight: dict[str, threading.Lock] = {}

    @staticmethod
    def key(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _once(self, path: Path, make) -> tuple[dict, bool]:
        """Return the saved record at path, creating it with make() if absent.

        Only one thread creates a given record; the others wait and reuse it.
        """
        with self._lock:
            gate = self._in_flight.setdefault(str(path), threading.Lock())
        with gate:
            if path.exists():
                return json.loads(path.read_text()), True
            record = make()
            # Failures are not kept: a page that timed out for one model may load for the next.
            if not record.get("error"):
                path.write_text(json.dumps(record, indent=1, ensure_ascii=False))
            return record, False

    # -- web_search

    def web_search(self, query: str) -> tuple[str, dict]:
        query = " ".join(str(query).split())
        if not query:
            return "Error: the search query was empty.", {"ok": False, "error": "empty query"}
        search_id = self.key(self.search_provider + "\n" + query.lower())

        def make():
            try:
                results, error = self._search(query, self.n_results), None
            except ToolError as err:
                results, error = [], str(err)
            return {"id": search_id, "query": query, "provider": self.search_provider,
                    "searched_at": _now(), "results": results, "error": error}

        record, reused = self._once(self.searches / f"{search_id}.json", make)
        log = {"ok": not record["error"], "search_id": search_id, "reused": reused,
               "urls": [r["url"] for r in record["results"]], "error": record["error"]}
        if record["error"]:
            return f"Error: {record['error']}.", log
        if not record["results"]:
            return f'No results for "{query}".', log
        lines = [f'Results for "{query}":', ""]
        for k, r in enumerate(record["results"], 1):
            lines += [f"{k}. {r['title']}", f"   {r['url']}", f"   {r['snippet']}", ""]
        return "\n".join(lines).strip(), log

    # -- fetch_page

    def fetch_page(self, url: str) -> tuple[str, dict]:
        url = str(url).strip()
        page_id = self.key(url)

        def make():
            record = {"id": page_id, "url": url, "fetched_at": _now(), "final_url": url,
                      "title": "", "text": "", "via": None, "error": None}
            try:
                try:
                    got = fetch_direct(url)
                    if len(got["text"]) < MIN_USEFUL_CHARS:
                        raise ToolError("the page had no readable text")
                except ToolError as first:
                    if self._second_reader is None:
                        raise
                    try:
                        got = self._second_reader(url)
                        if len(got["text"]) < MIN_USEFUL_CHARS:
                            raise ToolError("the page had no readable text")
                    except ToolError:
                        raise first from None
                record.update(got)
            except ToolError as err:
                record["error"] = str(err)
            return record

        record, reused = self._once(self.pages / f"{page_id}.json", make)
        shown = record["text"][: self.page_chars]
        log = {"ok": not record["error"], "page_id": page_id, "reused": reused, "url": url,
               "final_url": record["final_url"], "via": record["via"],
               "chars_total": len(record["text"]), "chars_shown": len(shown), "error": record["error"]}
        if record["error"]:
            return f"Error: could not open {url}: {record['error']}.", log
        head = [f"URL: {record['final_url']}"]
        if record["title"]:
            head.insert(0, f"Title: {record['title']}")
        if len(shown) < len(record["text"]):
            head.append(f"(Showing the first {len(shown):,} of {len(record['text']):,} characters.)")
        return "\n".join(head) + "\n\n" + shown, log

    # -- dispatch

    def call(self, name: str, arguments: str | dict | None) -> tuple[str, dict]:
        """Run one tool call. Returns (text shown to the model, log entry)."""
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            if not isinstance(args, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return "Error: the tool arguments were not valid JSON.", {"ok": False, "error": "invalid arguments"}
        if name == "web_search":
            if "query" not in args:
                return "Error: web_search needs a query.", {"ok": False, "error": "missing query"}
            text, log = self.web_search(args["query"])
        elif name == "fetch_page":
            if "url" not in args:
                return "Error: fetch_page needs a url.", {"ok": False, "error": "missing url"}
            text, log = self.fetch_page(args["url"])
        else:
            return f"Error: there is no tool called {name}.", {"ok": False, "error": "unknown tool"}
        return text, log
