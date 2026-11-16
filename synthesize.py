"""Step 3 (AI): summarise a run's listings as bullet points, and add a row to history/history.csv.

Usage:  python synthesize.py              (uses the latest run)
        python synthesize.py history/2026-11-16_1200_data-scientist
"""

import csv
import json
import sys
from collections import Counter

from pydantic import BaseModel

from common import HISTORY_DIR, ROOT, ask_claude, load_config, read_json, run_dir_from_args, write_json

SKILL_FIELDS = ["company_type", "hard_skills", "soft_skills", "platforms_and_tools", "certifications"]


class Item(BaseModel):
    name: str
    count: int  # number of listings that mention it


class Synthesis(BaseModel):
    hard_skills: list[Item]
    soft_skills: list[Item]
    certifications: list[Item]
    platforms: list[Item]
    company_types: list[Item]


def bullets(items):
    return [f"- {i.name} ({i.count})" for i in items] or ["- none"]


def main():
    run_dir = run_dir_from_args(sys.argv)
    config = load_config(run_dir / "config.yaml")
    listings = read_json(run_dir / "listings.json")
    if not listings:
        raise SystemExit(f"No listings in {run_dir}. Run `python extract.py` first.")

    # Counted in code: no need for AI here.
    companies = Counter(j["company"] for j in listings if j["company"]).most_common(10)
    by_site = Counter(j["site"] for j in listings)

    # Only send the fields needed for the summary, to keep the request small and cheap.
    analysed = [{k: j[k] for k in SKILL_FIELDS} for j in listings if "hard_skills" in j]
    print(f"Synthesising {len(analysed)} analysed listings from {run_dir.name}...")
    prompt = f"""Here are {len(analysed)} job listings for "{config['job_title']}" as JSON.

For each category, list the items that come up most, merging synonyms (e.g. "scikit-learn" and "sklearn"),
with the number of listings that mention each one, sorted by count (highest first). Max 20 items per category.
- hard_skills: technical skills (languages, methods, domains)
- soft_skills
- certifications
- platforms: software, cloud platforms and tools
- company_types: kinds of companies hiring (e.g. "startup", "bank", "consulting firm")

<listings>
{json.dumps(analysed, ensure_ascii=False)}
</listings>"""
    s = ask_claude(config, prompt, output_format=Synthesis, effort="medium")

    md = [f"# Synthesis - {config['job_title']}", f"_{run_dir.name}_", "",
          f"**Number of listings:** {len(listings)} "
          f"({', '.join(f'{site}: {n}' for site, n in by_site.items())})", "",
          "## Hard skills", *bullets(s.hard_skills), "",
          "## Soft skills", *bullets(s.soft_skills), "",
          "## Certifications", *bullets(s.certifications), "",
          "## Platforms", *bullets(s.platforms), "",
          "## Types of companies hiring", *bullets(s.company_types), "",
          "## Companies hiring the most", *[f"- {c} ({n})" for c, n in companies], ""]
    (run_dir / "synthesis.md").write_text("\n".join(md), encoding="utf-8")

    write_json(run_dir / "synthesis.json", s.model_dump() | {
        "number_of_listings": len(listings), "listings_per_site": dict(by_site),
        "top_companies": [{"name": c, "count": n} for c, n in companies]})

    # One row per run -> easy to load in Excel / pandas to see how things evolve over time.
    history_csv = HISTORY_DIR / "history.csv"
    is_new = not history_csv.exists()
    top = lambda items: "; ".join(f"{i.name} ({i.count})" for i in items[:10])
    with open(history_csv, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["run", "job_title", "location", "number_of_listings", "top_hard_skills",
                        "top_soft_skills", "top_certifications", "top_platforms", "top_company_types",
                        "top_companies"])
        w.writerow([run_dir.name, config["job_title"], config["location"], len(listings),
                    top(s.hard_skills), top(s.soft_skills), top(s.certifications), top(s.platforms),
                    top(s.company_types), "; ".join(f"{c} ({n})" for c, n in companies)])

    print("\n".join(md))
    print(f"Saved to {run_dir.relative_to(ROOT)}/synthesis.md and added a row to history/history.csv")


if __name__ == "__main__":
    main()
