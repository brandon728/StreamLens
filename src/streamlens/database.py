"""
Manages the DuckDB database connection and creates all tables on first run.

StreamLens uses a three-layer "medallion" architecture:
  - Bronze: raw data exactly as received from the source
  - Silver: cleaned, validated, and joined data ready for analysis
  - Gold:   business metrics and aggregations ready for the dashboard
"""

import os
from pathlib import Path
import duckdb


# Default database file lives in the data/ folder at the project root
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "streamlens.duckdb"


def getConnection(dbPath: Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (or create) the DuckDB database file and return a connection."""
    dbPath.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(dbPath))


def initSchema(conn: duckdb.DuckDBPyConnection) -> None:
    """Create all Bronze, Silver, and Gold tables if they don't already exist."""
    conn.executemany("", [])  # no-op to ensure connection is alive

    # ------------------------------------------------------------------
    # BRONZE — raw snapshots with source metadata attached
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bronze_tmdb_trending (
            ingestedAt    TIMESTAMP,   -- when this row was pulled from the API
            source        VARCHAR,     -- always 'tmdb_trending'
            mediaType     VARCHAR,     -- 'movie' or 'tv'
            tmdbId        INTEGER,
            title         VARCHAR,
            originalTitle VARCHAR,
            overview      TEXT,
            popularity    DOUBLE,
            voteAverage   DOUBLE,
            voteCount     INTEGER,
            releaseDate   VARCHAR,     -- kept as text in bronze; cast in silver
            genreIds      VARCHAR,     -- JSON array stored as text
            rawJson       TEXT         -- full API response for this title
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bronze_tmdb_details (
            ingestedAt    TIMESTAMP,
            source        VARCHAR,
            mediaType     VARCHAR,
            tmdbId        INTEGER,
            imdbId        VARCHAR,     -- links to IMDb datasets
            runtime       INTEGER,
            revenue       BIGINT,
            budget        BIGINT,
            genres        VARCHAR,     -- JSON array of {id, name} objects
            networks      VARCHAR,     -- JSON array (TV only)
            rawJson       TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bronze_imdb_basics (
            ingestedAt    TIMESTAMP,
            source        VARCHAR,
            tconst        VARCHAR,     -- IMDb title identifier (e.g. tt1234567)
            titleType     VARCHAR,     -- 'movie', 'tvSeries', 'tvEpisode', etc.
            primaryTitle  VARCHAR,
            originalTitle VARCHAR,
            isAdult       VARCHAR,
            startYear     VARCHAR,
            endYear       VARCHAR,
            runtimeMinutes VARCHAR,
            genres        VARCHAR      -- comma-separated genre list
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bronze_imdb_ratings (
            ingestedAt    TIMESTAMP,
            source        VARCHAR,
            tconst        VARCHAR,
            averageRating DOUBLE,
            numVotes      INTEGER
        )
    """)

    # ------------------------------------------------------------------
    # SILVER — cleaned, deduplicated, joined across TMDB + IMDb
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS silver_titles (
            snapshotDate  DATE,        -- one record per title per day
            mediaType     VARCHAR,
            tmdbId        INTEGER,
            imdbId        VARCHAR,
            title         VARCHAR,
            releaseYear   INTEGER,
            runtimeMinutes INTEGER,
            genres        VARCHAR,     -- pipe-separated for easy filtering
            networks      VARCHAR,
            popularity    DOUBLE,
            tmdbVoteAverage DOUBLE,
            tmdbVoteCount   INTEGER,
            imdbRating    DOUBLE,
            imdbVoteCount INTEGER,
            revenue       BIGINT,
            budget        BIGINT,
            PRIMARY KEY (snapshotDate, tmdbId)
        )
    """)

    # ------------------------------------------------------------------
    # GOLD — business metrics consumed by the dashboard
    # ------------------------------------------------------------------
    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_trending_tracker (
            snapshotDate      DATE,
            tmdbId            INTEGER,
            title             VARCHAR,
            mediaType         VARCHAR,
            popularity        DOUBLE,
            popularityChange  DOUBLE,   -- delta vs. previous day
            trendDirection    VARCHAR,  -- 'rising', 'falling', or 'stable'
            PRIMARY KEY (snapshotDate, tmdbId)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_genre_performance (
            snapshotDate          DATE,
            genre                 VARCHAR,
            titleCount            INTEGER,
            weightedImdbRating    DOUBLE,  -- vote-weighted average rating
            avgPopularity         DOUBLE,
            PRIMARY KEY (snapshotDate, genre)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_network_scorecard (
            snapshotDate       DATE,
            network            VARCHAR,
            titleCount         INTEGER,
            avgImdbRating      DOUBLE,
            avgPopularity      DOUBLE,
            PRIMARY KEY (snapshotDate, network)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_content_velocity (
            snapshotDate      DATE,
            tmdbId            INTEGER,
            title             VARCHAR,
            mediaType         VARCHAR,
            velocityScore     DOUBLE,   -- normalized rate of popularity change
            velocityLabel     VARCHAR,  -- 'breakout', 'climbing', 'steady', 'fading'
            PRIMARY KEY (snapshotDate, tmdbId)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS gold_catalog_engagement (
            snapshotDate   DATE,
            releaseDecade  INTEGER,    -- e.g. 1990, 2000, 2010
            mediaType      VARCHAR,
            titleCount     INTEGER,
            avgPopularity  DOUBLE,
            avgImdbRating  DOUBLE,
            PRIMARY KEY (snapshotDate, releaseDecade, mediaType)
        )
    """)
