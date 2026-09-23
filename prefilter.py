#!/usr/bin/env python3
"""
prefilter.py -- cheap second-pass filter between find_jobs.py's coarse gather
and Claude's judge step. Drops over-level titles, enforces the salary floor
(keeping undisclosed as plausible), and dedupes by (company, title).

Usage:
    python3 prefilter.py [in_path] [out_path] [--min-salary N]
Defaults: in_path=job_candidates.json, out_path=job_candidates_prefiltered.json,
min-salary=200000, both resolved relative to this script's directory.
"""

import argparse
import json
import re
from pathlib import Path

OVER_LEVEL_TERMS = [
    "staff", "principal", "distinguished", "director", "vp ", "head of",
    "manager", "architect", "tech lead", "technical lead", "lead engineer",
]


def is_over_level(title):
    tl = title.lower()
    return any(term in tl for term in OVER_LEVEL_TERMS)


def salary_ok(salary, floor):
    return salary is None or salary >= floor


def norm_title(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser()
    parser.add_argument("in_path", nargs="?", default=str(here / "job_candidates.json"))
    parser.add_argument("out_path", nargs="?", default=str(here / "job_candidates_prefiltered.json"))
    parser.add_argument("--min-salary", type=int, default=200000)
    args = parser.parse_args()

    data = json.loads(Path(args.in_path).read_text(encoding="utf-8"))

    seen = set()
    out = []
    for j in data:
        if is_over_level(j["title"]):
            continue
        if not salary_ok(j["salary"], args.min_salary):
            continue
        key = (j["company"].lower(), norm_title(j["title"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(j)

    Path(args.out_path).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(data)} -> {len(out)} after level+salary+dedupe pre-filter")


if __name__ == "__main__":
    main()
