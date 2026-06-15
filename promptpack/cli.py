"""Command-line interface for PROMPTPACK."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Optional

from . import TOOL_NAME, TOOL_VERSION
from .core import Registry, PromptPackError, DEFAULT_DB


def _emit(obj: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(obj, indent=2, sort_keys=True))
        return
    # table / human-readable
    if isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            cols = list(obj[0].keys())
            print("  ".join(cols))
            for row in obj:
                print("  ".join(str(row.get(c, "")) for c in cols))
        else:
            for line in obj:
                print(line)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            print(f"{k}: {v}")
    else:
        print(obj)


def _parse_vars(pairs: Optional[List[str]]) -> dict:
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise PromptPackError(f"bad --var {p!r}; expected key=value")
        k, v = p.split("=", 1)
        out[k] = v
    return out


def _parse_variants(specs: List[str]) -> List[dict]:
    out = []
    for s in specs:
        # form: version:weight  e.g.  2:3
        if ":" in s:
            ver, w = s.split(":", 1)
        else:
            ver, w = s, "1"
        try:
            version_int = int(ver)
        except ValueError:
            raise PromptPackError(
                f"bad variant {s!r}; version part must be an integer (got {ver!r})"
            )
        try:
            weight_float = float(w)
        except ValueError:
            raise PromptPackError(
                f"bad variant {s!r}; weight part must be a number (got {w!r})"
            )
        out.append({"version": version_int, "weight": weight_float})
    return out


def build_parser() -> argparse.ArgumentParser:
    # Shared parent that adds --format to every subcommand so it can appear
    # either before or after the subcommand name.
    fmt_parent = argparse.ArgumentParser(add_help=False)
    fmt_parent.add_argument("--format", choices=["table", "json"], default="table")

    ap = argparse.ArgumentParser(prog=TOOL_NAME,
                                 description="Versioned prompt registry with A/B and rollbacks.",
                                 parents=[fmt_parent])
    ap.add_argument("--version", action="version",
                    version=f"{TOOL_NAME} {TOOL_VERSION}")
    ap.add_argument("--db", default=DEFAULT_DB, help="registry file path")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("commit", help="add a new immutable version", parents=[fmt_parent])
    p.add_argument("name")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--body")
    g.add_argument("--file", help="read body from file ('-' for stdin)")
    p.add_argument("-m", "--message", default="")

    p = sub.add_parser("list", help="list prompts", parents=[fmt_parent])

    p = sub.add_parser("get", help="show a version's body", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("--ref", help="version number, tag, or 'latest'")

    p = sub.add_parser("history", help="version history of a prompt", parents=[fmt_parent])
    p.add_argument("name")

    p = sub.add_parser("tag", help="point a tag at a version", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("tag")
    p.add_argument("--ref")

    p = sub.add_parser("rollback", help="roll a tag back to a prior version", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("tag")
    p.add_argument("ref")

    p = sub.add_parser("render", help="render a version with variables", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("--ref")
    p.add_argument("--var", action="append", help="key=value (repeatable)")

    p = sub.add_parser("diff", help="unified diff between two refs", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("ref_a")
    p.add_argument("ref_b")

    p = sub.add_parser("ab", help="attach weighted A/B variants to a tag", parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("tag")
    p.add_argument("variant", nargs="+", help="version[:weight] e.g. 2:3")

    p = sub.add_parser("choose", help="select an A/B variant (deterministic with --key)",
                       parents=[fmt_parent])
    p.add_argument("name")
    p.add_argument("tag")
    p.add_argument("--key", help="stable bucketing key (e.g. user id)")

    return ap


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    try:
        reg = Registry(args.db)
    except PromptPackError as exc:
        fmt = getattr(args, "format", "table")
        if fmt == "json":
            import json as _json
            print(_json.dumps({"error": str(exc)}), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        if args.cmd == "commit":
            if args.file:
                if args.file == "-":
                    body = sys.stdin.read()
                else:
                    try:
                        with open(args.file, "r", encoding="utf-8") as fh:
                            body = fh.read()
                    except OSError as exc:
                        raise PromptPackError(f"cannot read file {args.file!r}: {exc}") from exc
            else:
                body = args.body
            res = reg.commit(args.name, body, args.message)
            reg.save()
            _emit({k: v for k, v in res.items() if k != "body"}, args.format)

        elif args.cmd == "list":
            _emit(reg.list_prompts(), args.format)

        elif args.cmd == "get":
            obj = reg.get(args.name, args.ref)
            if args.format == "json":
                _emit(obj, args.format)
            else:
                print(obj["body"])

        elif args.cmd == "history":
            _emit(reg.history(args.name), args.format)

        elif args.cmd == "tag":
            res = reg.tag(args.name, args.tag, args.ref)
            reg.save()
            _emit(res, args.format)

        elif args.cmd == "rollback":
            res = reg.rollback(args.name, args.tag, args.ref)
            reg.save()
            _emit(res, args.format)

        elif args.cmd == "render":
            text = reg.render(args.name, _parse_vars(args.var), args.ref)
            if args.format == "json":
                _emit({"name": args.name, "rendered": text}, args.format)
            else:
                print(text)

        elif args.cmd == "diff":
            lines = reg.diff(args.name, args.ref_a, args.ref_b)
            _emit(lines, args.format)

        elif args.cmd == "ab":
            res = reg.set_ab(args.name, args.tag, _parse_variants(args.variant))
            reg.save()
            _emit(res, args.format)

        elif args.cmd == "choose":
            res = reg.choose(args.name, args.tag, args.key)
            _emit(res, args.format)

        else:  # pragma: no cover
            ap.error(f"unknown command {args.cmd!r}")
    except PromptPackError as exc:
        msg = {"error": str(exc)}
        if args.format == "json":
            print(json.dumps(msg), file=sys.stderr)
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
