"""Human-like pacing: random pauses so a run looks like one person browsing, not a bot.

Every HTTP request JobSpy makes (search pages, job pages, descriptions) goes through one session class.
`install()` wraps it so each request waits a random few seconds first, with an occasional longer
"reading" pause. `wait()` gives the same pauses to code outside JobSpy (Welcome to the Jungle).
"""

import random
import time

DEFAULTS = {
    "request_delay": [5, 14],      # seconds between two requests to a site
    "long_pause_chance": 0.15,     # chance that a pause is a longer one, like reading a listing
    "long_pause": [20, 45],
    "site_delay": [30, 90],        # seconds between two sites
}

_settings = dict(DEFAULTS)
_installed = False


def configure(config):
    _settings.update(DEFAULTS)
    _settings.update(config.get("pacing") or {})


def wait():
    """Pause before a request: usually a few seconds, sometimes longer."""
    if random.random() < _settings["long_pause_chance"]:
        time.sleep(random.uniform(*_settings["long_pause"]))
    else:
        time.sleep(random.uniform(*_settings["request_delay"]))


def wait_between_sites():
    seconds = random.uniform(*_settings["site_delay"])
    print(f"  (pausing {seconds:.0f}s before the next site)")
    time.sleep(seconds)


def install(config):
    """Make every JobSpy request wait a random, human-like delay first."""
    global _installed
    configure(config)
    if _installed:
        return
    from jobspy.util import RotatingProxySession  # base of all JobSpy sessions (requests and curl)

    original = RotatingProxySession.request

    def paced_request(self, *args, **kwargs):
        wait()
        return original(self, *args, **kwargs)

    RotatingProxySession.request = paced_request
    _installed = True
