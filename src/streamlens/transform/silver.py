"""
Silver layer: cleans, validates, and joins data from the Bronze tables.

The Silver layer is the "single source of truth" for analysis. Here we:
  - Cast text fields to proper types (dates, integers, decimals)
  - Join TMDB trending data with TMDB details and IMDb ratings
  - Deduplicate so each title appears only once per snapshot date
  - Drop rows where critical fields are missing

Downstream gold metrics read exclusively from silver_titles.
"""

import json
import logging
from datetime import date

import duckdb

logger = logging.getLogger(__name__)


def _parseGenreNames(genresJson: str | None) -> str:
    """
    Convert a TMDB genres JSON array into a pipe-separated string.

    Example input:  '[{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"}]'
    Example output: 'Action|Adventure'
    """
    if not genresJson:
        return ""
    try:
        genres = json.loads(genresJson)
        return "|".join(g.get("name", "") for g in genres if g.get("name"))
    except (json.JSONDecodeError, TypeError):
        return ""


def _parseNetworkNames(networksJson: str | None) -> str:
    """Convert a TMDB networks JSON array into a pipe-separated string of names."""
    if not networksJson:
        return ""
    try:
        networks = json.loads(networksJson)
        return "|".join(n.get("name", "") for n in networks if n.get("name"))
    except (json.JSONDecodeError, TypeError):
        return ""


def buildSilverTitles(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Populate silver_titles for the given snapshot date (defaults to today).

    Joins:
      bronze_tmdb_trending  (popularity, votes, release date)
      bronze_tmdb_details   (imdb_id, runtime, genres, networks, revenue)
      bronze_imdb_ratings   (imdb rating, imdb vote count)

    Returns the number of rows written.
    """
    targetDate = snapshotDate or date.today()

    # Remove any existing rows for this date so we can re-run safely
    conn.execute(
        "DELETE FROM silver_titles WHERE snapshotDate = ?", [targetDate]
    )

    # Pull from bronze — grab the most recent ingest for each tmdbId on this date
    trendingDf = conn.execute("""
        SELECT DISTINCT ON (tmdbId)
            tmdbId,
            mediaType,
            title,
            popularity,
            voteAverage   AS tmdbVoteAverage,
            voteCount     AS tmdbVoteCount,
            releaseDate
        FROM bronze_tmdb_trending
        WHERE ingestedAt::DATE = ?
        ORDER BY tmdbId, ingestedAt DESC
    """, [targetDate]).df()

    if trendingDf.empty:
        logger.warning("Silver: no bronze trending data found for %s", targetDate)
        return 0

    detailsDf = conn.execute("""
        SELECT DISTINCT ON (tmdbId)
            tmdbId,
            imdbId,
            runtime        AS runtimeMinutes,
            revenue,
            budget,
            genres         AS genresJson,
            networks       AS networksJson
        FROM bronze_tmdb_details
        WHERE ingestedAt::DATE = ?
        ORDER BY tmdbId, ingestedAt DESC
    """, [targetDate]).df()

    # IMDb ratings — join by imdb_id; take today's snapshot if available, else latest
    imdbDf = conn.execute("""
        SELECT DISTINCT ON (tconst)
            tconst         AS imdbId,
            averageRating  AS imdbRating,
            numVotes       AS imdbVoteCount
        FROM bronze_imdb_ratings
        ORDER BY tconst, ingestedAt DESC
    """).df()

    # Merge trending + details on tmdbId
    merged = trendingDf.merge(detailsDf, on="tmdbId", how="left")

    # Merge in IMDb ratings via imdbId
    if not imdbDf.empty:
        merged = merged.merge(imdbDf, on="imdbId", how="left")
    else:
        merged["imdbRating"] = None
        merged["imdbVoteCount"] = None

    # Parse genre and network names from JSON
    merged["genres"] = merged["genresJson"].apply(_parseGenreNames)
    merged["networks"] = merged["networksJson"].apply(_parseNetworkNames)

    # Extract release year from releaseDate string (format: 'YYYY-MM-DD' or 'YYYY')
    merged["releaseYear"] = (
        merged["releaseDate"]
        .astype(str)
        .str[:4]
        .where(merged["releaseDate"].notna())
        .apply(lambda y: int(y) if y and y.isdigit() else None)
    )

    # Build the final silver DataFrame with only the columns we need
    silverDf = merged[[
        "tmdbId", "mediaType", "title", "imdbId",
        "releaseYear", "runtimeMinutes", "genres", "networks",
        "popularity", "tmdbVoteAverage", "tmdbVoteCount",
        "imdbRating", "imdbVoteCount", "revenue", "budget",
    ]].copy()

    # Drop titles with no title or no tmdbId — they're unusable
    silverDf = silverDf.dropna(subset=["tmdbId", "title"])
    silverDf.insert(0, "snapshotDate", targetDate)

    # Write to silver — use BY NAME so column order in the DataFrame doesn't matter
    conn.execute("INSERT INTO silver_titles BY NAME SELECT * FROM silverDf")
    logger.info("Silver: wrote %d rows for %s", len(silverDf), targetDate)
    return len(silverDf)
