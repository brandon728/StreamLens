"""
Gold layer: computes the five business metrics that power the StreamLens dashboard.

Each function reads from silver_titles and writes to its corresponding gold table.
These metrics are designed to answer questions a streaming product team asks daily:
  1. What's trending — and how fast?
  2. Which genres are winning?
  3. Which networks produce the best content?
  4. Which titles are breaking out vs. fading?
  5. Is catalog content resurging?

All functions are idempotent: they delete existing rows for the target date
before writing, so re-running the pipeline never creates duplicates.
"""

import logging
from datetime import date

import duckdb

logger = logging.getLogger(__name__)


def buildTrendingTracker(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Metric 1 — Daily Trending Tracker.

    Compares today's popularity score to yesterday's to compute direction
    and rate of change. Titles with no prior-day record are labelled 'new'.
    """
    targetDate = snapshotDate or date.today()
    conn.execute("DELETE FROM gold_trending_tracker WHERE snapshotDate = ?", [targetDate])

    rowCount = conn.execute("""
        INSERT INTO gold_trending_tracker
        SELECT
            today.snapshotDate,
            today.tmdbId,
            today.title,
            today.mediaType,
            today.popularity,
            COALESCE(today.popularity - yesterday.popularity, 0)  AS popularityChange,
            CASE
                WHEN yesterday.popularity IS NULL                   THEN 'new'
                WHEN today.popularity > yesterday.popularity * 1.05 THEN 'rising'
                WHEN today.popularity < yesterday.popularity * 0.95 THEN 'falling'
                ELSE 'stable'
            END AS trendDirection
        FROM silver_titles today
        LEFT JOIN silver_titles yesterday
            ON today.tmdbId = yesterday.tmdbId
            AND yesterday.snapshotDate = today.snapshotDate - INTERVAL '1 day'
        WHERE today.snapshotDate = ?
        ORDER BY today.popularity DESC
    """, [targetDate]).fetchone()[0]  # INSERT returns affected-row count

    logger.info("Gold trending_tracker: %d rows for %s", rowCount, targetDate)
    return rowCount


def buildGenrePerformance(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Metric 2 — Genre Performance Index.

    Explodes the pipe-separated genres column so each title contributes
    once per genre, then computes a vote-weighted IMDb rating and average
    popularity per genre.

    Vote-weighting gives more influence to titles with many reviews,
    preventing a title with 10 votes from distorting the genre average.
    """
    targetDate = snapshotDate or date.today()
    conn.execute("DELETE FROM gold_genre_performance WHERE snapshotDate = ?", [targetDate])

    rowCount = conn.execute("""
        INSERT INTO gold_genre_performance
        WITH exploded AS (
            -- Split the pipe-separated genres into one row per genre
            SELECT
                snapshotDate,
                TRIM(genre_value) AS genre,
                imdbRating,
                imdbVoteCount,
                popularity
            FROM silver_titles,
            UNNEST(STRING_SPLIT(genres, '|')) AS t(genre_value)
            WHERE snapshotDate = ?
              AND genres IS NOT NULL
              AND genres <> ''
        )
        SELECT
            snapshotDate,
            genre,
            COUNT(*)                                                      AS titleCount,
            -- Vote-weighted rating: sum(rating * votes) / sum(votes)
            CASE
                WHEN SUM(COALESCE(imdbVoteCount, 0)) > 0
                THEN SUM(COALESCE(imdbRating, 0) * COALESCE(imdbVoteCount, 0))
                     / SUM(COALESCE(imdbVoteCount, 0))
                ELSE NULL
            END                                                           AS weightedImdbRating,
            AVG(popularity)                                               AS avgPopularity
        FROM exploded
        WHERE genre <> ''
        GROUP BY snapshotDate, genre
        HAVING COUNT(*) >= 3
        ORDER BY weightedImdbRating DESC NULLS LAST
    """, [targetDate]).fetchone()[0]

    logger.info("Gold genre_performance: %d rows for %s", rowCount, targetDate)
    return rowCount


def buildNetworkScorecard(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Metric 3 — Network Content Scorecard.

    Explodes the pipe-separated networks column and aggregates rating and
    popularity per network. Filters to TV titles only (movies don't have networks).
    Requires at least 3 titles per network to appear in the scorecard.
    """
    targetDate = snapshotDate or date.today()
    conn.execute("DELETE FROM gold_network_scorecard WHERE snapshotDate = ?", [targetDate])

    rowCount = conn.execute("""
        INSERT INTO gold_network_scorecard
        WITH exploded AS (
            SELECT
                snapshotDate,
                TRIM(network_value) AS network,
                imdbRating,
                popularity
            FROM silver_titles,
            UNNEST(STRING_SPLIT(networks, '|')) AS t(network_value)
            WHERE snapshotDate = ?
              AND mediaType = 'tv'
              AND networks IS NOT NULL
              AND networks <> ''
        )
        SELECT
            snapshotDate,
            network,
            COUNT(*)          AS titleCount,
            AVG(imdbRating)   AS avgImdbRating,
            AVG(popularity)   AS avgPopularity
        FROM exploded
        WHERE network <> ''
        GROUP BY snapshotDate, network
        HAVING COUNT(*) >= 3
        ORDER BY avgImdbRating DESC NULLS LAST
    """, [targetDate]).fetchone()[0]

    logger.info("Gold network_scorecard: %d rows for %s", rowCount, targetDate)
    return rowCount


def buildContentVelocity(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Metric 4 — Content Velocity Score.

    Measures how quickly a title's popularity is changing relative to others.
    The score is normalized to a 0–100 scale within the current snapshot.

    Labels:
      'breakout' — top 10% velocity, still in high popularity
      'climbing' — positive velocity
      'steady'   — near-zero change
      'fading'   — negative velocity
    """
    targetDate = snapshotDate or date.today()
    conn.execute("DELETE FROM gold_content_velocity WHERE snapshotDate = ?", [targetDate])

    rowCount = conn.execute("""
        INSERT INTO gold_content_velocity
        WITH changes AS (
            SELECT
                today.snapshotDate,
                today.tmdbId,
                today.title,
                today.mediaType,
                today.popularity,
                COALESCE(today.popularity - yesterday.popularity, 0) AS rawChange
            FROM silver_titles today
            LEFT JOIN silver_titles yesterday
                ON today.tmdbId = yesterday.tmdbId
                AND yesterday.snapshotDate = today.snapshotDate - INTERVAL '1 day'
            WHERE today.snapshotDate = ?
        ),
        normalized AS (
            SELECT *,
                -- Normalize raw change to 0–100 using min-max scaling
                CASE
                    WHEN MAX(rawChange) OVER () = MIN(rawChange) OVER () THEN 50
                    ELSE 100.0 * (rawChange - MIN(rawChange) OVER ())
                         / NULLIF(MAX(rawChange) OVER () - MIN(rawChange) OVER (), 0)
                END AS velocityScore
            FROM changes
        )
        SELECT
            snapshotDate,
            tmdbId,
            title,
            mediaType,
            velocityScore,
            CASE
                WHEN velocityScore >= 90 AND popularity > 50 THEN 'breakout'
                WHEN velocityScore >= 55                      THEN 'climbing'
                WHEN velocityScore <= 45                      THEN 'fading'
                ELSE 'steady'
            END AS velocityLabel
        FROM normalized
        ORDER BY velocityScore DESC
    """, [targetDate]).fetchone()[0]

    logger.info("Gold content_velocity: %d rows for %s", rowCount, targetDate)
    return rowCount


def buildCatalogEngagement(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> int:
    """
    Metric 5 — Catalog vs. New Release Engagement.

    Groups titles by release decade to reveal whether older catalog content
    is resurging in popularity — a key question for streaming platforms
    deciding whether to invest in new originals vs. licensing back-catalog.
    """
    targetDate = snapshotDate or date.today()
    conn.execute("DELETE FROM gold_catalog_engagement WHERE snapshotDate = ?", [targetDate])

    rowCount = conn.execute("""
        INSERT INTO gold_catalog_engagement
        SELECT
            snapshotDate,
            -- Round release year down to the nearest decade (e.g. 2023 → 2020)
            (releaseYear // 10) * 10  AS releaseDecade,
            mediaType,
            COUNT(*)                  AS titleCount,
            AVG(popularity)           AS avgPopularity,
            AVG(imdbRating)           AS avgImdbRating
        FROM silver_titles
        WHERE snapshotDate = ?
          AND releaseYear IS NOT NULL
          AND releaseYear BETWEEN 1950 AND 2025
        GROUP BY snapshotDate, releaseDecade, mediaType
        ORDER BY releaseDecade DESC
    """, [targetDate]).fetchone()[0]

    logger.info("Gold catalog_engagement: %d rows for %s", rowCount, targetDate)
    return rowCount


def buildAllGoldMetrics(
    conn: duckdb.DuckDBPyConnection,
    snapshotDate: date | None = None,
) -> dict[str, int]:
    """Run all five gold metric builders and return a summary of row counts."""
    targetDate = snapshotDate or date.today()
    return {
        "trending_tracker":   buildTrendingTracker(conn, targetDate),
        "genre_performance":  buildGenrePerformance(conn, targetDate),
        "network_scorecard":  buildNetworkScorecard(conn, targetDate),
        "content_velocity":   buildContentVelocity(conn, targetDate),
        "catalog_engagement": buildCatalogEngagement(conn, targetDate),
    }
