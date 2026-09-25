"""Polite HTTP helpers for downloading All the Places data.

All requests carry a User-Agent that points back at this repository, and
failed requests are retried a small number of times with growing pauses so
we never hammer the upstream servers.
"""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)

USER_AGENT = "hotel-chain-map (+https://github.com/asherish/hotel-chain-map)"

# Conservative retry policy: a few attempts with a growing pause. Upstream is
# a volunteer-run project; if it is down we prefer to fail the whole run and
# keep the previously published data.
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 15.0
TIMEOUT_SECONDS = 180


def get_json(url: str, session: requests.Session | None = None):
    """Fetch a URL and decode it as JSON, retrying on transient failures."""
    sess = session or requests.Session()
    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = sess.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
            # Client errors (e.g. 404) will not fix themselves; do not retry.
            if 400 <= response.status_code < 500:
                response.raise_for_status()
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as error:
            if error.response is not None and 400 <= error.response.status_code < 500:
                raise
            last_error = error
        except (requests.ConnectionError, requests.Timeout, ValueError) as error:
            last_error = error
        if attempt < MAX_ATTEMPTS:
            pause = BACKOFF_SECONDS * attempt
            log.warning("Fetch failed (%s), retrying in %.0fs: %s", last_error, pause, url)
            time.sleep(pause)
    raise RuntimeError(f"Failed to fetch {url} after {MAX_ATTEMPTS} attempts") from last_error
