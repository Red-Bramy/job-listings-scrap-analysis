"""Step 1 (no AI, free): collect job listings matching config.yaml into history/<run>/.

Usage:  python scrape.py [path/to/config.yaml] [--wttj-ai | --no-wttj-ai]
"""

import argparse
import csv
import re
import shutil
from datetime import date, datetime

import pandas as pd
from jobspy import scrape_jobs

import pacing
import wttj
from common import HISTORY_DIR, ROOT, load_config, write_json

FIELDS = ["site", "title", "company", "location", "date_posted", "salary_min", "salary_max",
          "salary_currency", "job_type", "company_industry", "job_url", "description"]

MAX_RESULTS_PER_SITE = 25  # keep volumes low, like one person browsing


def scrape_site(config, site):
    days = (date.today() - date.fromisoformat(str(config["date_from"]))).days + 1
    df = scrape_jobs(
        site_name=[site],
        search_term=config["job_title"],
        location=config["location"],
        country_indeed=config["country"],
        results_wanted=config["results_per_site"],  # capped to MAX_RESULTS_PER_SITE in main()
        hours_old=days * 24,
        fetch_description=True,
        enforce_annual_salary=True,  # convert monthly/hourly salaries to yearly
        description_format="markdown",
    )
    df = df.rename(columns={"min_amount": "salary_min", "max_amount": "salary_max", "currency": "salary_currency"})
    df = df.reindex(columns=FIELDS).astype(object)
    return df.where(pd.notna(df), None).to_dict("records")


def title_ok(config, title):
    title = (title or "").lower()
    keywords = [k.lower() for k in config.get("title_must_contain") or []]
    if keywords and not any(k in title for k in keywords):
        return False
    # whole words only, so "intern" doesn't exclude "International"
    return not any(re.search(rf"\b{re.escape(w.lower())}\b", title)
                   for w in config.get("title_must_not_contain") or [])


def matches(config, job):
    """Filters that don't need AI: title, posting date and (when stated) salary."""
    if not title_ok(config, job["title"]):
        return False

    posted = job["date_posted"]
    if posted and not (str(config["date_from"]) <= str(posted)[:10] <= str(config["date_to"])):
        return False

    lo, hi = job["salary_min"], job["salary_max"]
    if config.get("salary_min") and (hi or lo) and (hi or lo) < config["salary_min"]:
        return False
    if config.get("salary_max") and (lo or hi) and (lo or hi) > config["salary_max"]:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Collect job listings matching config.yaml (no AI by default).")
    parser.add_argument("config", nargs="?", default=ROOT / "config.yaml", help="config file (default: config.yaml)")
    parser.add_argument("--wttj-ai", action=argparse.BooleanOptionalAction, default=None,
                        help="read Welcome to the Jungle pages with Claude (--wttj-ai) or directly, "
                             "for free (--no-wttj-ai). Default: wttj_use_ai in the config.")
    args = parser.parse_args()
    config_path = args.config
    config = load_config(config_path)
    wttj_ai = config.get("wttj_use_ai", False) if args.wttj_ai is None else args.wttj_ai
    if config["results_per_site"] > MAX_RESULTS_PER_SITE:
        print(f"results_per_site lowered from {config['results_per_site']} to {MAX_RESULTS_PER_SITE}.")
        config["results_per_site"] = MAX_RESULTS_PER_SITE
    pacing.install(config)  # random pauses before every request

    slug = re.sub(r"[^a-z0-9]+", "-", config["job_title"].lower()).strip("-")
    run_dir = HISTORY_DIR / f"{datetime.now():%Y-%m-%d_%H%M}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(config_path, run_dir / "config.yaml")  # remember the settings used

    jobs, seen = [], set()
    print("Requests are spaced out with random pauses, so this takes several minutes.")
    for i, site in enumerate(config["sites"]):
        if i:
            pacing.wait_between_sites()
        print(f"Scraping {site}...")
        try:
            if site == "welcometothejungle":
                found = wttj.scrape(config, lambda title: title_ok(config, title), use_ai=wttj_ai)
            else:
                found = scrape_site(config, site)
        except Exception as e:  # one site failing should not stop the others
            print(f"  ! {site} failed: {e}")
            continue
        kept = 0
        for job in found:
            key = ((job["title"] or "").lower().strip(), (job["company"] or "").lower().strip())
            if key in seen or not matches(config, job):  # skip duplicates posted on several sites
                continue
            seen.add(key)
            jobs.append(job)
            kept += 1
        print(f"  {len(found)} found, {kept} kept")

    write_json(run_dir / "raw_listings.json", jobs)
    with open(run_dir / "raw_listings.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS[:-1], extrasaction="ignore")  # no description: keeps it readable
        w.writeheader()
        w.writerows(jobs)

    missing = sum(1 for j in jobs if not j["description"])
    print(f"\nSaved {len(jobs)} listings to {run_dir.relative_to(ROOT)}/")
    if missing:
        print(f"({missing} have no description - the site blocked it - so the AI step will skip their skills)")
    print("Next: python extract.py")


if __name__ == "__main__":
    main()
