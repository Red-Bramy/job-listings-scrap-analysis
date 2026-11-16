"""Shared helpers: config loading, the Claude call and the history folder."""

import json
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent
HISTORY_DIR = ROOT / "history"


def load_config(path=ROOT / "config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_dir_from_args(argv):
    """Use the run folder given on the command line, or the latest one in history/."""
    if len(argv) > 1:
        return Path(argv[1]).resolve()
    runs = sorted(p for p in HISTORY_DIR.iterdir() if p.is_dir()) if HISTORY_DIR.exists() else []
    if not runs:
        raise SystemExit("No runs found in history/. Run `python scrape.py` first.")
    return runs[-1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


_client = None


def ask_claude(config, prompt, output_format, effort="low", tools=None):
    """Send one prompt to Claude and return the answer parsed into `output_format` (a pydantic model)."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment / .env

    messages = [{"role": "user", "content": prompt}]
    while True:
        with _client.messages.stream(
            model=config["model"],
            max_tokens=64000,
            output_config={"effort": effort},
            output_format=output_format,
            messages=messages,
            **({"tools": tools} if tools else {}),
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason != "pause_turn":
            break
        # A long web fetch can pause; send the turn back so the server continues it.
        messages.append({"role": "assistant", "content": response.content})

    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined the request: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Response was cut off (max_tokens).")
    return response.parsed_output
