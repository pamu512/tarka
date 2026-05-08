"""``tarka-test`` CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys

from tarka_test.runner import load_suite_file, run_suite


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tarka-test",
        description="Run JSON suite files against POST /v1/decisions/evaluate.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Execute a suite JSON file")
    run_p.add_argument("suite", help="Path to suite JSON")
    run_p.add_argument(
        "--base-url",
        help="Override suite base_url (e.g. https://api.example.com)",
    )
    run_p.add_argument("--verbose", "-v", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "run":
        suite = load_suite_file(args.suite)
        if args.base_url:
            suite.base_url = args.base_url.rstrip("/")
        results = run_suite(suite, verbose=args.verbose)
        failures = [r for r in results if not r.ok]
        for r in results:
            line = f"[{'PASS' if r.ok else 'FAIL'}] {r.case_id}"
            if r.trace_id:
                line += f" trace_id={r.trace_id}"
            if r.status_code is not None:
                line += f" http={r.status_code}"
            print(line)
            if r.errors:
                for e in r.errors:
                    print(f"    {e}")
        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r.ok),
            "failed": len(failures),
        }
        print(json.dumps(summary))
        return 0 if not failures else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
