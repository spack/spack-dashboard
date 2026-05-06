#!/usr/bin/env python3
"""
Fetch weekly open-issue and open-PR counts for tracked repositories
and write data/dashboard.json for the GitHub Pages dashboard.

Uses the GitHub GraphQL API so all ~216 search counts are batched into
a handful of HTTP requests, avoiding the REST Search API's 30 req/min
rate limit that caused 403 errors.

Uses only the stdlib — no pip install needed.
"""

import json
import os
import time
import urllib.request
from datetime import date, datetime, timedelta

REPOS = ["spack/spack", "spack/spack-packages"]
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GRAPHQL_URL = "https://api.github.com/graphql"
# Keep each batch well under GitHub's per-request complexity limit.
# 50 search aliases × ~7 pts each ≈ 350 pts (limit is 500 000).
BATCH_SIZE = 50


# ---------------------------------------------------------------------------
# GraphQL helpers
# ---------------------------------------------------------------------------

def graphql_request(query: str) -> dict:
    payload = json.dumps({"query": query}).encode()
    req = urllib.request.Request(GRAPHQL_URL, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    if "errors" in data:
        raise RuntimeError(f"GraphQL errors: {data['errors']}")
    return data["data"]


def fetch_counts(aliases_and_queries: list[tuple[str, str]]) -> dict[str, int]:
    """
    Send batched GraphQL requests and return {alias: issueCount}.
    Each alias maps to one GitHub search string.
    """
    results: dict[str, int] = {}
    for start in range(0, len(aliases_and_queries), BATCH_SIZE):
        batch = aliases_and_queries[start : start + BATCH_SIZE]
        # Build: { alias: search(query: "...", type: ISSUE) { issueCount } }
        body = "\n".join(
            f'  {alias}: search(query: {json.dumps(q)}, type: ISSUE) {{ issueCount }}'
            for alias, q in batch
        )
        gql = "{\n" + body + "\n}"
        print(f"  batch {start // BATCH_SIZE + 1}: {len(batch)} queries … ", end="", flush=True)
        data = graphql_request(gql)
        for alias, _ in batch:
            results[alias] = data[alias]["issueCount"]
        print("done")
        if start + BATCH_SIZE < len(aliases_and_queries):
            time.sleep(1)   # brief pause between batches
    return results


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def repo_key(repo: str) -> str:
    """Safe GraphQL alias prefix from repo name (must match [_A-Za-z][_0-9A-Za-z]*)."""
    return repo.replace("/", "_").replace("-", "_")


def weekly_dates(weeks: int = 26) -> list[str]:
    today = date.today()
    d = today - timedelta(weeks=weeks)
    dates: list[str] = []
    while d <= today:
        dates.append(d.isoformat())
        d += timedelta(weeks=1)
    return dates


def build_queries(repos: list[str], dates: list[str]) -> list[tuple[str, str]]:
    """
    For each repo × item_type × snapshot date we need two counts:
      open_i  : is:open created<=snapshot          (still open today, created before T)
      closed_i: is:closed closed>snapshot created<=snapshot  (closed after T → was open at T)
    Plus one current-count query per repo × item_type.
    Total: 2 repos × 2 types × 26 dates × 2 halves + 2 repos × 2 types × 1 = 216 queries.
    """
    queries: list[tuple[str, str]] = []
    for repo in repos:
        rk = repo_key(repo)
        for kind, type_filter in [("issue", "is:issue"), ("pr", "is:pr")]:
            for i, snap in enumerate(dates):
                queries.append((
                    f"{rk}_{kind}_open_{i}",
                    f"repo:{repo} {type_filter} is:open created:<={snap}",
                ))
                queries.append((
                    f"{rk}_{kind}_closed_{i}",
                    f"repo:{repo} {type_filter} is:closed closed:>{snap} created:<={snap}",
                ))
            queries.append((
                f"{rk}_{kind}_current",
                f"repo:{repo} {type_filter} is:open",
            ))
    return queries


def assemble(repos: list[str], dates: list[str], counts: dict[str, int]) -> dict:
    result: dict = {}
    for repo in repos:
        rk = repo_key(repo)
        open_issues = [
            counts[f"{rk}_issue_open_{i}"] + counts[f"{rk}_issue_closed_{i}"]
            for i in range(len(dates))
        ]
        open_prs = [
            counts[f"{rk}_pr_open_{i}"] + counts[f"{rk}_pr_closed_{i}"]
            for i in range(len(dates))
        ]
        result[repo] = {
            "dates":               dates,
            "open_issues":         open_issues,
            "open_prs":            open_prs,
            "current_open_issues": counts[f"{rk}_issue_current"],
            "current_open_prs":    counts[f"{rk}_pr_current"],
            "updated_at":          datetime.utcnow().isoformat() + "Z",
        }
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    dates = weekly_dates(26)
    queries = build_queries(REPOS, dates)
    print(f"Fetching {len(queries)} counts across {-(-len(queries) // BATCH_SIZE)} batches …")
    counts = fetch_counts(queries)
    all_data = assemble(REPOS, dates, counts)

    os.makedirs("data", exist_ok=True)
    out = "data/dashboard.json"
    with open(out, "w") as f:
        json.dump(all_data, f, indent=2)
    print(f"\nWrote {out}")
    for repo, d in all_data.items():
        print(f"  {repo}: {d['current_open_issues']} open issues, {d['current_open_prs']} open PRs")


if __name__ == "__main__":
    main()
