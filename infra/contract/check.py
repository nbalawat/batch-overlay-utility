#!/usr/bin/env python3
"""Fail when a cloud's machine module stops honouring the cloud-neutral machine contract.

For every cloud that has modules/<cloud>/machine:
  1. its contract.tf is byte-identical to contract/machine-variables.tf, and
  2. its `machine` output has exactly the keys listed in contract/machine-outputs.md.

Run with --fix to copy the contract variables into each module. Standard library only.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Set

INFRA = Path(__file__).resolve().parent.parent
CLOUDS = ("aws", "azure", "gcp")
MACHINE_SOURCE = INFRA / "contract" / "machine-variables.tf"
MACHINE_OUTPUTS = INFRA / "contract" / "machine-outputs.md"


def output_keys(text: str, output: str = "machine") -> Set[str]:
    """Top-level keys of an output's object value, read from the HCL text by brace depth."""
    body = text[text.index(f'output "{output}"'):]
    body = body[body.index("value = {") + len("value = {"):]
    keys: Set[str] = set()
    depth = 0
    for raw in body.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
        if m and depth == 0:
            keys.add(m.group(1))
        depth += line.count("{") - line.count("}")
        if depth < 0:
            break
    return keys


def documented_keys() -> Set[str]:
    """The keys in the table of contract/machine-outputs.md: rows that start with | `key` |."""
    return set(re.findall(r"^\| `([a-z_]+)` \|", MACHINE_OUTPUTS.read_text(), flags=re.M))


def check(fix: bool = False, infra: Path = INFRA) -> List[str]:
    problems: List[str] = []
    source = (infra / "contract" / "machine-variables.tf").read_bytes()
    expected = documented_keys()
    clouds = [c for c in CLOUDS if (infra / "modules" / c / "machine").is_dir()]
    if not clouds:
        return ["no cloud has a machine module"]
    found: Dict[str, Set[str]] = {}
    for cloud in clouds:
        module = infra / "modules" / cloud / "machine"
        target = module / "contract.tf"
        if fix:
            shutil.copyfile(infra / "contract" / "machine-variables.tf", target)
        elif not target.exists() or target.read_bytes() != source:
            problems.append(f"{target.relative_to(infra)} differs from contract/machine-variables.tf (run: python3 infra/contract/check.py --fix)")
        found[cloud] = output_keys((module / "outputs.tf").read_text())
        if found[cloud] != expected:
            problems.append(f"{cloud}: machine output keys are {sorted(found[cloud])}, contract/machine-outputs.md lists {sorted(expected)}")
    if not problems:
        print(f"contract: machine modules for {', '.join(clouds)} match the machine contract ({len(expected)} output keys)")
    return problems


def main() -> int:
    problems = check(fix="--fix" in sys.argv)
    for p in problems:
        print(f"contract: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
