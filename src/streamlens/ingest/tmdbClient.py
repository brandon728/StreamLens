"""
Fetches movie and TV data from The Movie Database (TMDB) API.

TMDB is a free, community-maintained database with millions of titles.
This client handles authentication, pagination, and rate-limit courtesy delays
so the rest of the pipeline can treat it as a simple list of records.

To use this module you need a free TMDB API key:
  1. Sign up at https://www.themoviedb.org/signup
  2. Request an API key at https://www.themoviedb.org/settings/api
  3. Add it to your .env file as: TMDB_API_KEY=your_key_here
"""

import os
import time
import json
import logging
from typing import Generator

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"

# Courtesy delay between requests (seconds). TMDB allows ~40 req/sec;
# 0.1s keeps us well under that and avoids triggering rate-limit responses.
REQUEST_DELAY = 0.1


def _getApiKey() -> str:
    apiKey = os.getenv("TMDB_API_KEY", "")
    if not apiKey:
        raise EnvironmentError(
            "TMDB_API_KEY is not set. Add it to your .env file.\n"
            "Get a free key at https://www.themoviedb.org/settings/api"
        )
    return apiKey


def _get(client: httpx.Client, path: str, params: dict = {}) -> dict:
    """Make a single authenticated GET request and return the parsed JSON."""
    response = client.get(
        f"{BASE_URL}{path}",
        params={"api_key": _getApiKey(), **params},
        timeout=15,
    )
    response.raise_for_status()
    time.sleep(REQUEST_DELAY)
    return response.json()


def fetchTrending(mediaType: str = "all", timeWindow: str = "day") -> list[dict]:
    """
    Return today's trending titles from TMDB.

    Args:
        mediaType:  'all', 'movie', or 'tv'
        timeWindow: 'day' or 'week'

    Returns a list of raw TMDB result objects (dicts), each representing one title.
    """
    allResults = []
    with httpx.Client() as client:
        page = 1
        while True:
            data = _get(client, f"/trending/{mediaType}/{timeWindow}", {"page": page})
            results = data.get("results", [])
            if not results:
                break
            allResults.extend(results)
            if page >= data.get("total_pages", 1) or page >= 5:
                # Cap at 5 pages (100 titles) to keep the demo practical
                break
            page += 1
    logger.info("Fetched %d trending titles (mediaType=%s)", len(allResults), mediaType)
    return allResults


def fetchTitleDetails(tmdbId: int, mediaType: str) -> dict:
    """
    Return the full detail record for one movie or TV show.

    This enriches the trending data with fields like revenue, runtime,
    budget, and network — the dimensions a product team cares about.
    """
    path = f"/{'movie' if mediaType == 'movie' else 'tv'}/{tmdbId}"
    with httpx.Client() as client:
        return _get(client, path, {"append_to_response": "external_ids"})


def fetchDetailsForTrending(trendingRecords: list[dict]) -> Generator[dict, None, None]:
    """
    Yield an enriched detail dict for each record in a trending list.

    Skips any title that fails to fetch (network hiccup, removed title, etc.)
    and logs a warning instead of crashing the whole pipeline.
    """
    with httpx.Client() as client:
        for record in trendingRecords:
            tmdbId = record.get("id")
            mediaType = record.get("media_type", "movie")
            if not tmdbId or mediaType not in ("movie", "tv"):
                continue
            try:
                path = f"/{'movie' if mediaType == 'movie' else 'tv'}/{tmdbId}"
                detail = _get(client, path, {"append_to_response": "external_ids"})
                detail["_media_type"] = mediaType  # carry media_type into detail record
                yield detail
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch details for tmdbId=%s: %s", tmdbId, exc)
