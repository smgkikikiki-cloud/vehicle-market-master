#!/usr/bin/env python3
"""Ask each source whether we may poll it, and record the answer.

Two things are checked, and both are refusals we honour:

* an ordinary ``Disallow`` for our user-agent or for ``*``;
* Cloudflare's ``Content-Signal`` line.  ``ai-train=no`` and ``use=reference``
  are the operator saying what their words may be used for.  We store numbers
  and link back rather than reproducing their text, but a site that names AI
  crawlers in ``Disallow`` is refusing the fetch itself, not just the reuse.

    python tools/robots_check.py
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.robotparser import RobotFileParser

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vehreg.catalog import DATA_DIR, DEFAULT_YEAR  # noqa: E402
from vehreg.pricefeed import load_sources  # noqa: E402

AGENT = "vehicle-market-master"
# Names an operator uses when they mean "no automated agents like this one".
AI_AGENTS = ("claudebot", "gptbot", "google-extended", "ccbot", "anthropic-ai",
             "perplexitybot", "applebot-extended", "meta-externalagent",
             "bytespider", "amazonbot")


def fetch(url: str, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError):
        return ""


def content_signal(text: str) -> dict[str, str]:
    match = re.search(r"^\s*Content-Signal:\s*(.+)$", text, re.I | re.M)
    if not match:
        return {}
    signals = {}
    for part in match.group(1).split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            signals[key.strip().lower()] = value.strip().lower()
    return signals


def blocked_agents(text: str) -> list[str]:
    """AI crawler names the site disallows outright."""
    blocked, current = [], None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip().lower()
        if key == "user-agent":
            current = value
        elif key == "disallow" and value == "/" and current in AI_AGENTS:
            blocked.append(current)
    return sorted(set(blocked))


def audit(base_url: str) -> dict:
    root = f"{urllib.parse.urlsplit(base_url).scheme}://{urllib.parse.urlsplit(base_url).netloc}"
    text = fetch(root + "/robots.txt")
    parser = RobotFileParser()
    parser.parse(text.splitlines())
    return {
        "base_url": root,
        "robots_txt": bool(text.strip()),
        "may_fetch": parser.can_fetch(AGENT, root + "/") if text.strip() else True,
        "content_signal": content_signal(text),
        "ai_agents_disallowed": blocked_agents(text),
    }


def verdict(report: dict) -> str:
    if not report["may_fetch"]:
        return "refused: robots.txt disallows this agent"
    if report["ai_agents_disallowed"]:
        return ("refused: the site disallows automated agents of this kind ("
                + ", ".join(report["ai_agents_disallowed"]) + ")")
    if report["content_signal"].get("ai-input") == "no":
        return "refused: Content-Signal says ai-input=no"
    if not report["robots_txt"]:
        return "allowed: no robots.txt; poll gently and identify honestly"
    return "allowed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--year", type=int, default=DEFAULT_YEAR)
    parser.add_argument("--url", action="append", default=None,
                        help="check an arbitrary base URL as well")
    args = parser.parse_args(argv)

    targets = {s.id: s.base_url for s in load_sources(args.data_dir, args.year).values()
               if s.base_url}
    for url in args.url or []:
        targets[url] = url
    out = {}
    for name, url in targets.items():
        report = audit(url)
        report["verdict"] = verdict(report)
        out[name] = report
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if all(r["verdict"].startswith("allowed") for r in out.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
