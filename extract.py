"""Step 2 (AI): read each scraped listing and build the final table.

Each listing is analysed once: results are cached in history/extraction_cache.json, so a listing seen
again in a later run costs nothing.

Usage:  python extract.py              (uses the latest run)
        python extract.py history/2026-11-16_1200_data-scientist
"""

import csv
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from pydantic import BaseModel

from common import HISTORY_DIR, ROOT, ask_claude, load_config, read_json, run_dir_from_args, write_json

CACHE_FILE = HISTORY_DIR / "extraction_cache.json"


class Extracted(BaseModel):
    company_type: str  # e.g. "startup", "bank", "consulting firm", "big tech"
    remote_policy: str
    salary_range: str
    min_years_experience: int | None  # None if the listing doesn't say
    years_of_experience: str
    contract_type: str
    hard_skills: list[str]
    soft_skills: list[str]
    platforms_and_tools: list[str]
    certifications: list[str]
    education: str
    languages: list[str]
    tasks: list[str]
    job_objectives: list[str]
    recruiting_process: list[str]
    benefits: list[str]


def extract(config, job):
    prompt = f"""Extract information from this job listing. Only use what the listing says; write "not specified"
(or an empty list) when something is missing. Keep skill and tool names short and canonical
(e.g. "Python", "SQL", "Machine Learning", "AWS", "Communication"). Write everything in English.

Title: {job['title']}
Company: {job['company']}
Location: {job['location']}

<description>
{job['description']}
</description>"""
    return ask_claude(config, prompt, output_format=Extracted).model_dump()


def experience_ok(config, years):
    if years is None:
        return True
    lo, hi = config.get("experience_min"), config.get("experience_max")
    return (lo is None or years >= lo) and (hi is None or years <= hi)


def to_markdown(config, rows):
    lines = [f"# {config['job_title']} - {len(rows)} listings",
             f"_{config['location']} | {config['date_from']} to {config['date_to']}_", ""]
    for i, row in enumerate(rows, 1):
        lines += [f"## {i}. {row['title']} - {row['company']}", ""]
        for field, value in row.items():
            if field in ("title", "company", "description"):
                continue
            label = field.replace("_", " ").capitalize()
            if isinstance(value, list):
                lines.append(f"**{label}:**")
                lines += [f"- {v}" for v in value] or ["- not specified"]
            else:
                lines.append(f"**{label}:** {value if value is not None else 'not specified'}")
        lines += ["", "---", ""]
    return "\n".join(lines)


def main():
    run_dir = run_dir_from_args(sys.argv)
    config = load_config(run_dir / "config.yaml")
    jobs = read_json(run_dir / "raw_listings.json")
    cache = read_json(CACHE_FILE) if CACHE_FILE.exists() else {}

    todo = [j for j in jobs if j["description"] and j["job_url"] not in cache]
    print(f"{len(jobs)} listings, {len(jobs) - len(todo)} already analysed or without description, "
          f"{len(todo)} to analyse with {config['model']}...")

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(extract, config, j): j for j in todo}
        for n, future in enumerate(as_completed(futures), 1):
            job = futures[future]
            try:
                cache[job["job_url"]] = future.result()
            except Exception as e:
                print(f"  ! failed on {job['job_url']}: {e}")
            if n % 20 == 0:
                write_json(CACHE_FILE, cache)  # save progress
                print(f"  {n}/{len(todo)}")
    write_json(CACHE_FILE, cache)

    rows = []
    for job in jobs:
        info = cache.get(job["job_url"])
        if info and not experience_ok(config, info["min_years_experience"]):
            continue
        rows.append({k: v for k, v in job.items() if k != "description"} | (info or {"analysed": False}))

    write_json(run_dir / "listings.json", rows)
    (run_dir / "listings.md").write_text(to_markdown(config, rows), encoding="utf-8")
    columns = list(dict.fromkeys(k for r in rows for k in r))
    with open(run_dir / "listings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows({k: "; ".join(v) if isinstance(v, list) else v for k, v in r.items()} for r in rows)

    print(f"\n{len(rows)} listings kept after the experience filter.")
    print(f"Saved the table to {run_dir.relative_to(ROOT)}/listings.csv (and .md, .json)")
    print("Next: python synthesize.py")


if __name__ == "__main__":
    main()
