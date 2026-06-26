"""
Bronze layer: writes raw data into the database exactly as received.

The Bronze layer is the "landing zone" — we store everything we get from
the source with no changes other than adding timestamps and a source label.
This means we can always replay or re-derive later layers from this record.
"""

import json
import logging
from datetime import datetime, timezone

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def writeTmdbTrending(
    conn: duckdb.DuckDBPyConnection,
    records: list[dict],
    ingestedAt: datetime | None = None,
) -> int:
    """
    Insert raw TMDB trending records into bronze_tmdb_trending.

    Returns the number of rows written.
    """
    if not records:
        return 0

    ts = ingestedAt or datetime.now(timezone.utc)

    rows = []
    for r in records:
        rows.append({
            "ingestedAt":    ts,
            "source":        "tmdb_trending",
            "mediaType":     r.get("media_type", "unknown"),
            "tmdbId":        r.get("id"),
            "title":         r.get("title") or r.get("name"),
            "originalTitle": r.get("original_title") or r.get("original_name"),
            "overview":      r.get("overview"),
            "popularity":    r.get("popularity"),
            "voteAverage":   r.get("vote_average"),
            "voteCount":     r.get("vote_count"),
            "releaseDate":   r.get("release_date") or r.get("first_air_date"),
            "genreIds":      json.dumps(r.get("genre_ids", [])),
            "rawJson":       json.dumps(r),
        })

    df = pd.DataFrame(rows)
    conn.execute("INSERT INTO bronze_tmdb_trending SELECT * FROM df")
    logger.info("Bronze: wrote %d TMDB trending rows", len(rows))
    return len(rows)


def writeTmdbDetails(
    conn: duckdb.DuckDBPyConnection,
    detailRecords: list[dict],
    ingestedAt: datetime | None = None,
) -> int:
    """
    Insert enriched TMDB detail records into bronze_tmdb_details.

    Returns the number of rows written.
    """
    if not detailRecords:
        return 0

    ts = ingestedAt or datetime.now(timezone.utc)

    rows = []
    for r in detailRecords:
        mediaType = r.get("_media_type", "movie")
        externalIds = r.get("external_ids", {})
        rows.append({
            "ingestedAt": ts,
            "source":     "tmdb_details",
            "mediaType":  mediaType,
            "tmdbId":     r.get("id"),
            "imdbId":     externalIds.get("imdb_id"),
            "runtime":    r.get("runtime") or (r["episode_run_time"][0] if r.get("episode_run_time") else None),
            "revenue":    r.get("revenue"),
            "budget":     r.get("budget"),
            "genres":     json.dumps(r.get("genres", [])),
            "networks":   json.dumps(r.get("networks", [])),
            "rawJson":    json.dumps(r),
        })

    df = pd.DataFrame(rows)
    conn.execute("INSERT INTO bronze_tmdb_details SELECT * FROM df")
    logger.info("Bronze: wrote %d TMDB detail rows", len(rows))
    return len(rows)


def writeImdbBasics(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    ingestedAt: datetime | None = None,
) -> int:
    """
    Insert IMDb title.basics rows into bronze_imdb_basics.

    Renames columns to camelCase to match our schema convention.
    Returns the number of rows written.
    """
    if df.empty:
        return 0

    ts = ingestedAt or datetime.now(timezone.utc)

    bronzeDf = df.rename(columns={
        "tconst":          "tconst",
        "titleType":       "titleType",
        "primaryTitle":    "primaryTitle",
        "originalTitle":   "originalTitle",
        "isAdult":         "isAdult",
        "startYear":       "startYear",
        "endYear":         "endYear",
        "runtimeMinutes":  "runtimeMinutes",
        "genres":          "genres",
    }).copy()

    bronzeDf.insert(0, "ingestedAt", ts)
    bronzeDf.insert(1, "source", "imdb_basics")

    conn.execute("INSERT INTO bronze_imdb_basics SELECT * FROM bronzeDf")
    logger.info("Bronze: wrote %d IMDb basics rows", len(bronzeDf))
    return len(bronzeDf)


def writeImdbRatings(
    conn: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    ingestedAt: datetime | None = None,
) -> int:
    """
    Insert IMDb title.ratings rows into bronze_imdb_ratings.

    Returns the number of rows written.
    """
    if df.empty:
        return 0

    ts = ingestedAt or datetime.now(timezone.utc)

    bronzeDf = df.copy()
    bronzeDf.insert(0, "ingestedAt", ts)
    bronzeDf.insert(1, "source", "imdb_ratings")

    conn.execute("INSERT INTO bronze_imdb_ratings SELECT * FROM bronzeDf")
    logger.info("Bronze: wrote %d IMDb ratings rows", len(bronzeDf))
    return len(bronzeDf)
