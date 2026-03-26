#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ALLOWED_BRANCHES = {
    "axi_lite_slave_baseline",
    "axi_lite_slave_test",
    "axi_lite_slave_golden",
}


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Push an AXI Lite branch to origin."
    )
    parser.add_argument(
        "--branch",
        required=True,
        help="Branch to push: axi_lite_slave_baseline|axi_lite_slave_test|axi_lite_slave_golden",
    )
    parser.add_argument(
        "--force-with-lease",
        action="store_true",
        help="Use force-with-lease when pushing.",
    )
    args = parser.parse_args()

    branch = args.branch.strip()
    if branch not in ALLOWED_BRANCHES:
        print(
            f"Unsupported branch '{branch}'. Allowed: {', '.join(sorted(ALLOWED_BRANCHES))}",
            file=sys.stderr,
        )
        return 2

    repo_root = Path(__file__).resolve().parents[1]

    check_branch = run_git(["show-ref", "--verify", f"refs/heads/{branch}"], repo_root)
    if check_branch.returncode != 0:
        print(f"Local branch not found: {branch}", file=sys.stderr)
        return 1

    cmd = ["push"]
    if args.force_with_lease:
        cmd.append("--force-with-lease")
    cmd.extend(["origin", branch])

    result = run_git(cmd, repo_root)
    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
