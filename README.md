# Job Skills Scraper

I wanted to see which skills employers really ask for in a job. This tool gets job listings, has Claude read them, and tells you what comes up most.

Sites: Indeed, LinkedIn, Glassdoor, HelloWork and Welcome to the Jungle.

## How it works

1. `scrape.py` gets the listings that match your search. Free.
2. `extract.py` has Claude read each listing and fill a table (skills, tools, certifications, tasks...).
3. `synthesize.py` makes a short summary of what comes up most.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        
pip install -r requirements.txt
cp .env.example .env             # add your Anthropic API key here
```

## Run it

Set your search in `config.yaml` (job title, location, dates, salary, experience), then:

```bash
python scrape.py
python extract.py
python synthesize.py
```

By default it uses the last run. To use an older one: `python synthesize.py history/<run-folder>`

## Filters

- **Job title**: must contain a word from `title_must_contain` and none from `title_must_not_contain`
- **Dates**: between `date_from` and `date_to`
- **Salary**: checked only if the listing shows one
- **Experience**: read by Claude. If the listing doesn't say, it's kept

The same job on several sites only counts once.

## Results

Each run gets its own folder in `history/`:

- `listings.csv`: the full table (open it in Excel)
- `synthesis.md`: the summary
- `history.csv`: one line per run, to compare over time

## Cost

Scraping is free. Claude Haiku costs about $0.05 per 100 listings. Listings you already did are saved, so you don't pay twice.

## Good to know

- Scraping uses [JobSpy](https://github.com/speedyapply/JobSpy) (Indeed, LinkedIn, Glassdoor, HelloWork).
- Scraping is slow on purpose: at most 25 listings per site, and a random pause of a few seconds before every request (sometimes longer), plus 30-90 s between sites. A full run takes about 10 minutes. Tune it under `pacing` in `config.yaml`.
- LinkedIn and Welcome to the Jungle may block you if you ask for too much. The scraper then stops and keeps what it has.
- For Welcome to the Jungle you can let Claude read the pages instead (about $0.003 a page): set `wttj_use_ai: true` in `config.yaml`.
- No Apec, there's no free scraper for it.

## Please be reasonable

Scraping goes against the rules of some sites (LinkedIn, Indeed). Keep it personal, keep volumes low, and don't share the raw listings, only the summaries.

## API key

Put your key in `.env` only, never in the code. Before you commit, run `git status` and check that `.env` and `history/` aren't listed. It's also smart to set a monthly spend limit in the Anthropic Console.