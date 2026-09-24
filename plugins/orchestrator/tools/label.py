#!/usr/bin/env python3
"""Label a sample of the router log by hand, and report how often the router was right.

The hooks log what the router said and what Claude did. This tool asks a person
what was right and appends the answers to labels.jsonl in the data directory.

Route mode asks per prompt: should this turn have been delegated?
Tier mode (--workers) asks per worker call: what is the smallest model that would do this well?

The tool only reads local files and never uses the network. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_DATA_DIR = Path.home() / ".claude" / "plugins" / "data" / "orchestrator-egonm12-plugins"
LOG_NAME = "router-log.jsonl"
LABELS_NAME = "labels.jsonl"
TEXT_SHOWN = 600
RANK = {"haiku": 0, "sonnet": 1, "opus": 2}
ROUTE_KEYS = {"d": "delegate", "s": "self", "k": "skip"}
TIER_KEYS = {"o": "opus", "s": "sonnet", "h": "haiku", "k": "skip"}
MARGIN_BUCKETS = ((0.0, 0.05, "<0.05"), (0.05, 0.15, "0.05-0.15"), (0.15, 0.3, "0.15-0.3"), (0.3, float("inf"), ">=0.3"))
LINK_KEYS = ("agent_id", "tool_use_id")

Key = Tuple[str, str, int, Optional[int]]


def now_iso() -> str:
    """The current UTC time in ISO 8601 with seconds and a Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_dir(given: Optional[str]) -> Path:
    """The data directory: the flag, else ORCHESTRATOR_DATA_DIR, else the plugin default."""
    if given:
        return Path(given).expanduser()
    env = os.environ.get("ORCHESTRATOR_DATA_DIR", "")
    return Path(env).expanduser() if env else DEFAULT_DATA_DIR


def read_jsonl(path: Path) -> Tuple[List[Dict[str, Any]], int]:
    """All JSON object lines of a file, and the count of lines that were not. A missing file is empty."""
    rows: List[Dict[str, Any]] = []
    bad = 0
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return rows, 0
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if isinstance(row, dict):
                rows.append(row)
            else:
                bad += 1
    return rows, bad


def as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def num(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    return float(value) if isinstance(value, (int, float)) else None


def collapse(text: Any, limit: int = TEXT_SHOWN) -> str:
    """The text with all whitespace runs made one space, cut to the limit."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit] + " [...]"


def route_margin(prompt: Dict[str, Any]) -> Optional[float]:
    """The logged delegate-self gap, else the gap computed from the route probabilities."""
    margin = num(prompt.get("margin"))
    if margin is not None:
        return margin
    probs = (prompt.get("verdict") or {}).get("route_probs") or {}
    delegate, self_ = num(probs.get("delegate")), num(probs.get("self"))
    return abs(delegate - self_) if delegate is not None and self_ is not None else None


# ---- the log, joined ----------------------------------------------------------------------


class Log:
    """The router log, grouped by session id and turn."""

    def __init__(self, rows: List[Dict[str, Any]], bad: int) -> None:
        self.bad = bad
        self.prompts: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.outcomes: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.calls: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        self.results: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
        for row in rows:
            session, turn = row.get("session_id"), as_int(row.get("turn"))
            if not isinstance(session, str) or turn is None:
                self.bad += 1
                continue
            key = (session, turn)
            kind = row.get("kind")
            if kind == "prompt":
                self.prompts[key] = row
            elif kind == "prompt_outcome":
                self.outcomes[key] = row  # the last outcome line of a turn wins
            elif kind == "agent_call":
                self.calls.setdefault(key, []).append(row)
            elif kind == "agent_result":
                self.results.setdefault(key, []).append(row)

    @classmethod
    def load(cls, path: Path) -> "Log":
        return cls(*read_jsonl(path))

    def route_items(self) -> List[Dict[str, Any]]:
        items = []
        for (session, turn), prompt in self.prompts.items():
            items.append({"kind": "route", "session_id": session, "turn": turn, "index": None,
                          "prompt": prompt, "outcome": self.outcomes.get((session, turn)),
                          "calls": self.calls.get((session, turn), []), "ts": str(prompt.get("ts") or "")})
        return items

    def tier_items(self) -> List[Dict[str, Any]]:
        items = []
        for (session, turn), calls in self.calls.items():
            links = link_results(calls, self.results.get((session, turn), []))
            for index, call in enumerate(calls):
                if call.get("subagent_type") == "fork" or call.get("action") == "fork":
                    continue
                items.append({"kind": "tier", "session_id": session, "turn": turn, "index": index,
                              "call": call, "result": links[index], "ts": str(call.get("ts") or "")})
        return items


def link_results(calls: List[Dict[str, Any]], results: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
    """Each call's agent_result: by a shared link key when both have one, else by order within the turn."""
    links: List[Optional[Dict[str, Any]]] = [None] * len(calls)
    left = list(results)
    for index, call in enumerate(calls):
        for name in LINK_KEYS:
            if call.get(name):
                match = next((r for r in left if r.get(name) == call.get(name)), None)
                if match is not None:
                    links[index] = match
                    left.remove(match)
                    break
    for index in range(len(calls)):
        if links[index] is None and left:
            links[index] = left.pop(0)
    return links


def route_used(prompt: Dict[str, Any]) -> str:
    """The route the hooks acted on. Old lines lack it, so fall back to the raw route."""
    return str(prompt.get("route_effective") or (prompt.get("verdict") or {}).get("route") or "none")


def route_group(item: Dict[str, Any]) -> int:
    """0 unsure, 1 delegate without a worker, 2 self with real work, 3 the rest."""
    prompt, outcome = item["prompt"], item["outcome"] or {}
    used = route_used(prompt)
    if used == "unsure":
        return 0
    if used == "delegate" and not item["calls"] and not (as_int(outcome.get("n_agent")) or 0):
        return 1
    if used == "self" and ((as_int(outcome.get("n_exploratory")) or 0) > 2 or (as_int(outcome.get("n_edit")) or 0) > 0):
        return 2
    return 3


def order_items(items: List[Dict[str, Any]], group: Callable[[Dict[str, Any]], int]) -> List[Dict[str, Any]]:
    """By group, then newest first within a group."""
    items = sorted(items, key=lambda item: (item["ts"], item["turn"]), reverse=True)
    return sorted(items, key=group)


def filter_items(items: List[Dict[str, Any]], since: Optional[str], session: Optional[str]) -> List[Dict[str, Any]]:
    if since:
        items = [item for item in items if item["ts"][:10] >= since]
    if session:
        items = [item for item in items if item["session_id"].startswith(session)]
    return items


# ---- labels -------------------------------------------------------------------------------


def label_key(row: Dict[str, Any]) -> Key:
    index = row.get("index")
    return (str(row.get("kind")), str(row.get("session_id")), as_int(row.get("turn")) or 0,
            as_int(index) if index is not None else None)


def item_key(item: Dict[str, Any]) -> Key:
    return (item["kind"], item["session_id"], item["turn"], item["index"])


def current_labels(path: Path) -> Dict[Key, Dict[str, Any]]:
    """The last line per key. A retraction (label null) removes the key."""
    latest: Dict[Key, Dict[str, Any]] = {}
    for row in read_jsonl(path)[0]:
        if row.get("kind") in ("route", "tier"):
            latest[label_key(row)] = row
    return {key: row for key, row in latest.items() if row.get("label")}


def label_line(item: Dict[str, Any], label: Optional[str]) -> Dict[str, Any]:
    """One labels.jsonl line, with a copy of the router's decision so stats need no join."""
    line: Dict[str, Any] = {"kind": item["kind"], "session_id": item["session_id"], "turn": item["turn"]}
    if item["kind"] == "tier":
        call = item["call"]
        line.update(index=item["index"], label=label, ts=now_iso(), model_set=call.get("model_set"),
                    model_given=call.get("model_given"), reason=call.get("reason"))
    else:
        prompt = item["prompt"]
        line.update(label=label, ts=now_iso(), route_effective=route_used(prompt),
                    route_raw=(prompt.get("verdict") or {}).get("route"), margin=route_margin(prompt))
    if label is None:
        line["retract"] = True
    return line


def append_line(path: Path, line: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()


# ---- showing an item ----------------------------------------------------------------------


def fmt_probs(probs: Any) -> str:
    if not isinstance(probs, dict) or not probs:
        return "-"
    return " ".join(f"{name}={value:.2f}" if num(value) is not None else f"{name}={value}"
                    for name, value in probs.items())


def fmt(value: Any, digits: int = 3) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def show_route(item: Dict[str, Any]) -> str:
    prompt, outcome = item["prompt"], item["outcome"] or {}
    verdict = prompt.get("verdict") or {}
    carried = prompt.get("carried_from_turn")
    lines = [
        f"session {item['session_id'][:8]} turn {item['turn']}  {item['ts']}  "
        f"cwd {Path(str(prompt.get('cwd') or '')).name or '-'}",
        f"text: {collapse(prompt.get('text'))}",
        f"route used: {route_used(prompt)}   raw: {verdict.get('route', '-')} ({fmt_probs(verdict.get('route_probs'))})"
        f"   margin: {fmt(route_margin(prompt))}   carried: {'from turn ' + str(carried) if carried is not None else 'no'}",
    ]
    if outcome:
        parts = [f"exploratory {fmt(outcome.get('n_exploratory'))}", f"tools {fmt(outcome.get('n_tool'))}"]
        if "n_edit" in outcome:
            parts.append(f"edits {fmt(outcome.get('n_edit'))}")
        parts.append(f"workers {fmt(outcome.get('n_agent'))}")
        if num(outcome.get("duration_s")) is not None:
            parts.append(f"duration {num(outcome.get('duration_s')):.0f}s")
        start, end = num(outcome.get("context_tokens_start")), num(outcome.get("context_tokens_end"))
        if start is not None and end is not None:
            parts.append(f"context +{end - start:.0f} tokens")
        lines.append("outcome: " + ", ".join(parts))
    else:
        lines.append("outcome: none logged")
    return "\n".join(lines)


def show_tier(item: Dict[str, Any]) -> str:
    call, result = item["call"], item["result"]
    lines = [
        f"session {item['session_id'][:8]} turn {item['turn']} call {item['index']}  {item['ts']}",
        f"description: {collapse(call.get('description'), 200)}",
        f"prompt: {collapse(call.get('prompt'))}",
        f"subagent: {call.get('subagent_type') or '-'}   model given: {fmt(call.get('model_given'))}"
        f"   model set: {fmt(call.get('model_set'))}   reason: {fmt(call.get('reason'))}",
        f"tier probs: {fmt_probs((call.get('verdict') or {}).get('tier_probs'))}",
    ]
    if result:
        fields = ("agent_type", "model", "duration_s", "context_tokens_end", "report_chars")
        lines.append("result: " + ", ".join(f"{name} {fmt(result.get(name), 1)}" for name in fields
                                            if result.get(name) is not None))
    return "\n".join(lines)


# ---- the review loop ----------------------------------------------------------------------


def key_reader(stream: Any) -> Callable[[], Optional[str]]:
    """Read one key. A TTY gives single key presses. Otherwise read lines. None means end of input."""
    if stream.isatty():
        try:
            import termios
            import tty

            def read_key() -> Optional[str]:
                fd = stream.fileno()
                old = termios.tcgetattr(fd)
                try:
                    tty.setcbreak(fd)  # keeps Ctrl-C as KeyboardInterrupt
                    char = stream.read(1)
                finally:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                print(char)
                return char or None
            return read_key
        except (ImportError, OSError, ValueError):
            pass

    def read_line() -> Optional[str]:
        line = stream.readline()
        if not line:
            return None
        return line.strip()[:1].lower()
    return read_line


def review(items: List[Dict[str, Any]], keys: Dict[str, str], question: str, show: Callable[[Dict[str, Any]], str],
           labels_path: Path, read_key: Callable[[], Optional[str]], out: Any) -> int:
    """Ask about each item in turn. Every answer is appended at once, so a quit or Ctrl-C loses nothing."""
    help_text = " ".join(f"{k}={v}" for k, v in keys.items()) + " u=undo q=quit"
    done: List[Dict[str, Any]] = []
    position = 0
    answered = 0
    try:
        while position < len(items):
            item = items[position]
            print(f"\n[{position + 1}/{len(items)}]", file=out)
            print(show(item), file=out)
            print(f"{question}  ({help_text})", file=out, end="  ", flush=True)
            key = read_key()
            if key is None or key == "q":
                break
            if key == "u":
                if not done:
                    print("nothing to undo", file=out)
                    continue
                last = done.pop()
                append_line(labels_path, label_line(last, None))
                answered -= 1
                position = items.index(last)
                print("undone", file=out)
                continue
            if key not in keys:
                print(f"unknown key {key!r}", file=out)
                continue
            append_line(labels_path, label_line(item, keys[key]))
            done.append(item)
            answered += 1
            position += 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=out)
    print(f"\n{answered} labelled this run, saved to {labels_path}", file=out)
    return answered


# ---- stats and export ---------------------------------------------------------------------


def table(title: str, rows: List[str], cols: List[str], counts: Dict[Tuple[str, str], int]) -> List[str]:
    width = max([len(title)] + [len(r) for r in rows]) + 2
    out = [title.ljust(width) + "".join(c.rjust(10) for c in cols) + "total".rjust(10)]
    for row in rows:
        cells = [counts.get((row, col), 0) for col in cols]
        out.append(row.ljust(width) + "".join(str(c).rjust(10) for c in cells) + str(sum(cells)).rjust(10))
    return out


def pct(hit: int, total: int) -> str:
    return f"{100.0 * hit / total:.0f}% ({hit}/{total})" if total else "- (0/0)"


def stats_text(labels: Dict[Key, Dict[str, Any]], unlabelled_routes: int, unlabelled_tiers: int) -> str:
    lines: List[str] = []
    routes = [row for row in labels.values() if row.get("kind") == "route" and row.get("label") != "skip"]
    tiers = [row for row in labels.values() if row.get("kind") == "tier" and row.get("label") != "skip"]
    skipped = sum(1 for row in labels.values() if row.get("label") == "skip")

    lines.append(f"Route labels: {len(routes)}")
    if routes:
        counts: Dict[Tuple[str, str], int] = {}
        for row in routes:
            pair = (str(row.get("route_effective") or "none"), str(row["label"]))
            counts[pair] = counts.get(pair, 0) + 1
        used = sorted({pair[0] for pair in counts})
        lines += table("route used \\ label", used, ["delegate", "self"], counts)
        decided = [row for row in routes if row.get("route_effective") in ("delegate", "self")]
        hits = sum(1 for row in decided if row["route_effective"] == row["label"])
        lines.append(f"agreement (route used was delegate or self): {pct(hits, len(decided))}")
        lines.append("")
        lines.append("agreement of the raw route per margin bucket:")
        for low, limit, name in MARGIN_BUCKETS:
            bucket = [row for row in routes if num(row.get("margin")) is not None and low <= row["margin"] < limit]
            hit = sum(1 for row in bucket if row.get("route_raw") == row["label"])
            lines.append(f"  {name.ljust(10)} {pct(hit, len(bucket))}")
        no_margin = sum(1 for row in routes if num(row.get("margin")) is None)
        if no_margin:
            lines.append(f"  no margin  {no_margin}")
    lines.append("")

    lines.append(f"Tier labels: {len(tiers)}")
    if tiers:
        counts = {}
        for row in tiers:
            pair = (str(row.get("model_set")), str(row["label"]))
            counts[pair] = counts.get(pair, 0) + 1
        lines += table("model set \\ label", sorted({p[0] for p in counts}), ["haiku", "sonnet", "opus"], counts)
        hits = sum(1 for row in tiers if row.get("model_set") == row["label"])
        lines.append(f"agreement: {pct(hits, len(tiers))}")
        downgrades = [row for row in tiers if row.get("model_given") in RANK and row.get("model_set") in RANK
                      and RANK[row["model_set"]] < RANK[row["model_given"]]]
        wrong = [row for row in downgrades if RANK.get(row["label"], -1) > RANK[row["model_set"]]]
        lines.append(f"downgrades: {len(downgrades)}, wrong (label bigger than model set): {len(wrong)}")
    lines.append("")
    lines.append(f"Skipped: {skipped}")
    lines.append(f"Unlabelled: {unlabelled_routes} route items, {unlabelled_tiers} tier items")
    return "\n".join(lines)


def export_rows(log: Log, labels: Dict[Key, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Joined labelled examples for training, and the count of labels whose log line is gone."""
    by_key = {item_key(item): item for item in log.route_items() + log.tier_items()}
    rows, missing = [], 0
    for key, label in labels.items():
        if label.get("label") == "skip":
            continue
        item = by_key.get(key)
        if item is None:
            missing += 1
            continue
        base = {"kind": key[0], "session_id": key[1], "turn": key[2], "label": label["label"]}
        if key[0] == "route":
            prompt, outcome = item["prompt"], item["outcome"] or {}
            verdict = prompt.get("verdict") or {}
            base.update(text=prompt.get("text", ""), route_effective=route_used(prompt), route_raw=verdict.get("route"),
                        route_probs=verdict.get("route_probs"), margin=route_margin(prompt),
                        carried_from_turn=prompt.get("carried_from_turn"), by_regex=verdict.get("by_regex"),
                        outcome={name: outcome.get(name) for name in ("n_exploratory", "n_tool", "n_edit", "n_agent",
                                                                     "duration_s") if name in outcome})
        else:
            call = item["call"]
            base.update(index=key[3], text=f"{call.get('description', '')}\n{call.get('prompt', '')}",
                        subagent_type=call.get("subagent_type"), model_given=call.get("model_given"),
                        model_set=call.get("model_set"), reason=call.get("reason"),
                        tier_probs=(call.get("verdict") or {}).get("tier_probs"))
        rows.append(base)
    return rows, missing


# ---- entry point --------------------------------------------------------------------------


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Label router log items by hand. Local files only.")
    parser.add_argument("--data-dir", help="data directory (default: ORCHESTRATOR_DATA_DIR or the plugin data dir)")
    parser.add_argument("--workers", action="store_true", help="label worker calls with the smallest good model")
    parser.add_argument("--since", help="only items on or after this date, YYYY-MM-DD")
    parser.add_argument("--session", help="only sessions whose id starts with this")
    parser.add_argument("--limit", type=int, help="ask about at most this many items")
    parser.add_argument("--stats", action="store_true", help="print agreement tables and exit")
    parser.add_argument("--export", metavar="FILE", help="write labelled examples as JSONL and exit")
    args = parser.parse_args(argv)
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            parser.error("--since needs YYYY-MM-DD")
    return args


def main(argv: Optional[List[str]] = None, stdin: Any = None, out: Any = None) -> int:
    args = parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    out = out if out is not None else sys.stdout
    directory = data_dir(args.data_dir)
    log_path, labels_path = directory / LOG_NAME, directory / LABELS_NAME
    if not log_path.exists():
        print(f"no log at {log_path}", file=out)
    log = Log.load(log_path)
    if log.bad:
        print(f"skipped {log.bad} malformed log lines", file=out)
    labels = current_labels(labels_path)

    route_items = filter_items(log.route_items(), args.since, args.session)
    tier_items = filter_items(log.tier_items(), args.since, args.session)
    route_left = [item for item in route_items if item_key(item) not in labels]
    tier_left = [item for item in tier_items if item_key(item) not in labels]

    if args.stats:
        print(stats_text(labels, len(route_left), len(tier_left)), file=out)
        return 0
    if args.export:
        rows, missing = export_rows(log, labels)
        with Path(args.export).expanduser().open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"wrote {len(rows)} examples to {args.export}" + (f", {missing} labels had no log line" if missing else ""),
              file=out)
        return 0

    if args.workers:
        items = order_items(tier_left, lambda item: 0)
        keys, question, show = TIER_KEYS, "What is the smallest model that would do this well?", show_tier
    else:
        items = order_items(route_left, route_group)
        keys, question, show = ROUTE_KEYS, "Should this have been delegated?", show_route
    if args.limit is not None:
        items = items[:max(args.limit, 0)]
    if not items:
        print("nothing left to label", file=out)
        return 0
    review(items, keys, question, show, labels_path, key_reader(stdin), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
