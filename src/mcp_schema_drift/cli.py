"""``mcp-surface`` — lock and verify the tool surface an MCP server advertises.

    mcp-surface snapshot --out mcp-surface.lock.json -- npx -y @modelcontextprotocol/server-github
    mcp-surface check --baseline mcp-surface.lock.json -- npx -y @modelcontextprotocol/server-github
    mcp-surface check --tools-json captured_tools_list.json     # offline: a saved tools/list result

Exit codes: 0 ok · 1 total schema loss · 2 breaking drift from the baseline · 3 probe/usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import ProbeError, fetch_tools
from .surface import check, lockfile


def _load_tools(path: str) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("result", data)
        data = data.get("tools", data)
    if not isinstance(data, list):
        raise TypeError(f"{path}: expected a tools/list result (a list, or an object with 'tools')")
    return data


def _get_tools(args: argparse.Namespace) -> tuple[list[dict], dict]:
    if args.tools_json:
        return _load_tools(args.tools_json), {"source": args.tools_json}
    if not args.command:
        raise ValueError("give a server command after --, or --tools-json FILE")
    return fetch_tools(args.command, timeout=args.timeout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mcp-surface", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="action", required=True)
    for name, help_text in (("snapshot", "record the current surface as a lockfile"),
                            ("check", "fail on total schema loss or drift from a lockfile")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--tools-json", metavar="FILE", help="read a saved tools/list result")
        p.add_argument("--timeout", type=float, default=60.0, help="handshake timeout, seconds")
        p.add_argument("command", nargs=argparse.REMAINDER, help="-- server command and args")
        if name == "snapshot":
            p.add_argument("--out", metavar="FILE", help="write the lockfile here (default: stdout)")
        else:
            p.add_argument("--baseline", metavar="FILE", help="lockfile from `mcp-surface snapshot`")
            p.add_argument("--json", action="store_true", help="machine-readable report")

    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]

    try:
        tools, info = _get_tools(args)
        if args.action == "snapshot":
            body = json.dumps(lockfile(tools, server=info), indent=2) + "\n"
            if args.out:
                Path(args.out).write_text(body, encoding="utf-8")
                print(f"locked {len(tools)} tools to {args.out}", file=sys.stderr)
            else:
                sys.stdout.write(body)
            return 0

        baseline = json.loads(Path(args.baseline).read_text()) if args.baseline else None
        report = check(tools, baseline)
    except (ProbeError, ValueError, TypeError, OSError) as e:
        print(f"mcp-surface: {e}", file=sys.stderr)
        return 3

    if args.json:
        print(json.dumps({
            "total_loss": report.total_loss,
            "exit_code": report.exit_code(),
            "findings": [f.__dict__ for f in report.findings],
        }, indent=2))
    else:
        for finding in report.findings:
            print(finding)
        verdict = {0: "OK", 1: "TOTAL SCHEMA LOSS", 2: "BREAKING DRIFT"}[report.exit_code()]
        print(f"{verdict}: {len(tools)} tools checked", file=sys.stderr)
    return report.exit_code()


def entrypoint() -> None:
    sys.exit(main())


if __name__ == "__main__":
    entrypoint()
