#!/usr/bin/env python3
"""
Fetch weekly open-issue and open-PR counts for tracked repositories
and write data/dashboard.json for the GitHub Pages dashboard.

Uses only the stdlib so no pip install is needed.
Rate-limited to stay within GitHub Search API's 30 req/min cap.
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

REPOS = ["spack/spack", "spack/spack-packages"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
SEARCH_URL = "https://api.github.com/search/issues"
# 2.1 s sleep → ~28 req/min, safely under the 30/min search limit
SLEEP = 2.1


def gh_request(url: str, params: dict | None = None) -> dict:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def search_count(query: str) -> int:
    result = gh_request(SEARCH_URL, {"q": query, "per_page": 1})
    count = result["total_count"]
    time.sleep(SLEEP)
    return count


def open_count_at(repo: str, item_type: str, snapshot: str) -> int:
    """
    Estimate the number of open issues/PRs in `repo` on `snapshot` (ISO date).

    Open at T means: created <= T AND (still open  OR  closed > T).
    Two search queries cover both halves:
      q1: currently open, created on or before T
      q2: closed after T, created on or before T
    """
    t = f"is:{item_type}"
    q1 = f"repo:{repo} {t} is:open  created:<={snapshot}"
    q2 = f"repo:{repo} {t} is:closed closed:>{snapshot} created:<={snapshot}"
    return search_count(q1) + search_count(q2)


def weekly_dates(weeks: int = 26) -> list[str]:
    today = date.today()
    start = today - timedelta(weeks=weeks)
    dates = []
    d = start
    while d <= today:
        dates.append(d.isoformat())
        d += timedelta(weeks=1)
    return dates


def main() -> None:
    dates = weekly_dates(26)
    all_data: dict = {}

    for repo in REPOS:
        print(f"\n── {repo} ──")
        issues: list[int] = []
        prs: list[int] = []

        for snapshot in dates:
            print(f"  {snapshot}", end="", flush=True)
            n_issues = open_count_at(repo, "issue", snapshot)
            n_prs    = open_count_at(repo, "pr",    snapshot)
            issues.append(n_issues)
            prs.append(n_prs)
            print(f"  issues={n_issues}  prs={n_prs}")

        current_issues = search_count(f"repo:{repo} is:issue is:open")
        current_prs    = search_count(f"repo:{repo} is:pr    is:open")
        print(f"  current  issues={current_issues}  prs={current_prs}")

        all_data[repo] = {
            "dates":               dates,
            "open_issues":         issues,
            "open_prs":            prs,
            "current_open_issues": current_issues,
            "current_open_prs":    current_prs,
            "updated_at":          datetime.utcnow().isoformat() + "Z",
        }

    os.makedirs("data", exist_ok=True)
    out = "data/dashboard.json"
    with open(out, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
