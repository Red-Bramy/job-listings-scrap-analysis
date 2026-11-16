"""Welcome to the Jungle scraper (no AI).

Uses only what the site offers to search engines: its public sitemap (the list of all job pages) and the
structured job data (schema.org JobPosting) embedded in each job page. Search pages are not used, as the
site's robots.txt disallows them.
"""

import gzip
import html
import json
import re
import xml.etree.ElementTree as ET

import requests
from pydantic import BaseModel

import pacing
from common import ask_claude

BASE = "https://www.welcometothejungle.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (job-skills-scrapper; personal research)"}
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r


def get_xml(url):
    data = get(url).content
    if data[:2] == b"\x1f\x8b":  # still gzipped (sometimes the server already decompressed it)
        data = gzip.decompress(data)
    return ET.fromstring(data)


def sitemap_jobs():
    """Yield (url, lastmod) for every job in the sitemap."""
    index = get_xml(f"{BASE}/sitemaps/index.xml.gz")
    for loc in index.findall("s:sitemap/s:loc", NS):
        if "job-listings" not in loc.text:
            continue
        urlset = get_xml(loc.text)
        for url in urlset.findall("s:url", NS):
            yield url.findtext("s:loc", namespaces=NS), url.findtext("s:lastmod", "", NS)


def html_to_text(raw):
    raw = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", raw or "")
    raw = re.sub(r"<li[^>]*>", "- ", raw)
    return re.sub(r"\n{3,}", "\n\n", html.unescape(re.sub(r"<[^>]+>", "", raw))).strip()


def parse_job_page(url, page):
    """Read the JobPosting data embedded in a job page."""
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]):
            if item.get("@type") != "JobPosting":
                continue
            places = item.get("jobLocation") or []
            places = places if isinstance(places, list) else [places]
            location = ", ".join(p.get("address", {}).get("addressLocality", "") for p in places)

            salary = (item.get("baseSalary") or {}).get("value") or {}
            factor = {"YEAR": 1, "MONTH": 12}.get(salary.get("unitText"))
            lo, hi = salary.get("minValue"), salary.get("maxValue")

            description = html_to_text(item.get("description"))
            months = (item.get("experienceRequirements") or {}).get("monthsOfExperience")
            if months:  # often only in the structured data, so pass it on to the AI step
                description = f"Experience required: {months / 12:g} years\n\n{description}"

            return {
                "site": "welcometothejungle",
                "title": item.get("title"),
                "company": (item.get("hiringOrganization") or {}).get("name"),
                "location": location,
                "date_posted": (item.get("datePosted") or "")[:10] or None,
                "salary_min": lo * factor if lo and factor else None,
                "salary_max": hi * factor if hi and factor else None,
                "salary_currency": (item.get("baseSalary") or {}).get("currency"),
                "job_type": item.get("employmentType"),
                "company_industry": None,
                "job_url": url,
                "description": description,
            }
    return None


class AIJobPage(BaseModel):
    available: bool  # False if the page could not be read or is not a job listing
    title: str
    company: str
    location: str
    date_posted: str  # YYYY-MM-DD, or "" if unknown
    salary_min: float | None  # yearly
    salary_max: float | None
    salary_currency: str
    job_type: str
    years_of_experience: str
    description: str


def read_page_with_claude(config, url):
    """AI mode: Claude's web fetch tool reads the page (costs a fraction of a cent per page)."""
    tools = [{"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 1,
              "allowed_domains": ["welcometothejungle.com"]}]
    prompt = f"""Fetch this Welcome to the Jungle job page: {url}

Return the job information exactly as the page states it. For description, copy the full job description
text (missions, profile, recruiting process, etc.) without summarising. Salaries are yearly (multiply
monthly ones by 12); use null if not stated. Set available to false if the page can't be read or is not
a job listing."""
    page = ask_claude(config, prompt, output_format=AIJobPage, tools=tools)
    if not page.available:
        return None
    description = page.description
    if page.years_of_experience:
        description = f"Experience required: {page.years_of_experience}\n\n{description}"
    return {
        "site": "welcometothejungle", "title": page.title, "company": page.company,
        "location": page.location, "date_posted": page.date_posted or None,
        "salary_min": page.salary_min, "salary_max": page.salary_max,
        "salary_currency": page.salary_currency or None, "job_type": page.job_type,
        "company_industry": None, "job_url": url, "description": description,
    }


def scrape(config, title_ok, use_ai=False):
    """Return Welcome to the Jungle listings matching the job title, city and date range.

    use_ai=False: read the pages directly (free, but the site may block after a few pages).
    use_ai=True:  let Claude's web fetch tool read the pages (small cost per page).
    """
    city = slugify(config["location"].split(",")[0])
    date_from = str(config["date_from"])

    # 1. Pre-filter on the URL (it contains the job title and the city) and the last-modified date.
    candidates, seen = [], set()
    for url, lastmod in sitemap_jobs():
        company_job = url.split("/companies/")[-1]
        title_slug, _, place_slug = company_job.split("/jobs/")[-1].partition("_")
        if (lastmod[:10] < date_from or city not in place_slug
                or not title_ok(title_slug.replace("-", " ")) or company_job in seen):
            continue
        seen.add(company_job)  # same job can be listed in French and English
        candidates.append(url)
    print(f"  {len(candidates)} candidate pages in the sitemap")

    # 2. Read each job page.
    jobs = []
    if use_ai:
        print(f"  reading pages with Claude ({config['model']})...")
        failures = 0
        for url in candidates:
            if len(jobs) >= config["results_per_site"]:
                break
            try:
                job = read_page_with_claude(config, url)
            except Exception as e:
                print(f"  ! {url}: {e}")
                job = None
            failures = 0 if job else failures + 1
            if failures >= 5:  # don't keep paying if pages can't be read
                print("  ! 5 pages in a row could not be read; stopping.")
                break
            if job and title_ok(job["title"]):
                jobs.append(job)
        return jobs

    for url in candidates:  # without AI: politely, with human-like pauses between pages
        if len(jobs) >= config["results_per_site"]:
            break
        pacing.wait()
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
        except requests.RequestException:
            continue
        if r.status_code in (202, 403, 429):  # bot protection: stop instead of insisting
            print(f"  ! Welcome to the Jungle is blocking automated access (HTTP {r.status_code}); "
                  f"stopping with {len(jobs)} listings. Try again later.")
            break
        job = parse_job_page(url, r.text) if r.ok else None  # not ok = expired listing
        if job and title_ok(job["title"]):
            jobs.append(job)
    return jobs
