#!/usr/bin/env python3
"""
prefilter.py -- cheap second-pass filter between find_jobs.py's coarse gather
and Claude's judge step. Drops over-level titles, enforces the salary floor
(keeping undisclosed as plausible), drops roles with no sign of frontend work,
and dedupes by (company, title).

Usage:
    python3 prefilter.py [in_path] [out_path] [--min-salary N]
Defaults: in_path=job_candidates.json, out_path=job_candidates_prefiltered.json,
min-salary=175000, both resolved relative to this script's directory.
"""

import argparse
import json
import re
from pathlib import Path

OVER_LEVEL_TERMS = [
    "principal", "distinguished", "director", "vp ", "head of",
    "manager", "architect", "tech lead", "technical lead", "lead engineer",
]


def is_over_level(title):
    tl = title.lower()
    return any(term in tl for term in OVER_LEVEL_TERMS)


# A role with no sign of frontend work: its full JD names no frontend framework (find_jobs.py's
# `stack`) and its title isn't a frontend-shaped one. A fullstack or web role whose JD never
# names its framework is kept for the judge, who scores the framework as unstated.
FRONTEND_STACK = {"vue", "angular", "react", "svelte"}
FRONTEND_TITLE = re.compile(
    r"front.?end|full.?stack|\bweb\b|\bui\b|\bux\b|user interface|design (?:engineer|systems?)|"
    r"product engineer|javascript|typescript|client|interface", re.I)


def no_frontend_signal(j):
    # Records from an older gather have no `stack`; keep them rather than guess.
    if "stack" not in j:
        return False
    return not (FRONTEND_STACK & set(j["stack"])) and not FRONTEND_TITLE.search(j["title"])


def salary_ok(salary, floor):
    return salary is None or salary >= floor


def norm_title(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("in_path", nargs="?", default=str(here / "job_candidates.json"))
    parser.add_argument("out_path", nargs="?", default=str(here / "job_candidates_prefiltered.json"))
    parser.add_argument("--min-salary", type=int, default=175000)
    args = parser.parse_args()

    data = json.loads(Path(args.in_path).read_text(encoding="utf-8"))

    seen = set()
    out = []
    dropped = {"level": 0, "salary": 0, "no frontend": 0, "duplicate": 0}
    for j in data:
        if is_over_level(j["title"]):
            dropped["level"] += 1
            continue
        if not salary_ok(j["salary"], args.min_salary):
            dropped["salary"] += 1
            continue
        if no_frontend_signal(j):
            dropped["no frontend"] += 1
            continue
        key = (j["company"].lower(), norm_title(j["title"]))
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        out.append(j)

    Path(args.out_path).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(data)} -> {len(out)} after the pre-filter; dropped "
          + ", ".join(f"{n} {why}" for why, n in dropped.items()))


if __name__ == "__main__":
    main()
