"""
Tests for the Gold layer metric builders.

Seeds silver_titles directly (bypassing bronze/silver) to test each
gold metric in isolation. Uses in-memory DuckDB for speed.
"""

from datetime import date, datetime, timezone

import duckdb
import pandas as pd
import pytest

from streamlens.database import initSchema
from streamlens.transform.gold import (
    buildTrendingTracker,
    buildGenrePerformance,
    buildNetworkScorecard,
    buildContentVelocity,
    buildCatalogEngagement,
    buildAllGoldMetrics,
)


@pytest.fixture
def memDb():
    """Provide a fresh in-memory DuckDB connection seeded with silver data."""
    conn = duckdb.connect(":memory:")
    initSchema(conn)
    yield conn
    conn.close()


def _seedSilver(conn: duckdb.DuckDBPyConnection, rows: list[dict]) -> None:
    """Insert rows directly into silver_titles for testing."""
    df = pd.DataFrame(rows)
    conn.execute("INSERT INTO silver_titles SELECT * FROM df")


TODAY = date.today()
YESTERDAY = date(TODAY.year, TODAY.month, TODAY.day - 1) if TODAY.day > 1 else date(TODAY.year, TODAY.month - 1, 28)

BASE_ROW = {
    "snapshotDate": TODAY,
    "mediaType": "movie",
    "tmdbId": 1,
    "imdbId": "tt0000001",
    "title": "Test Title",
    "releaseYear": 2020,
    "runtimeMinutes": 100,
    "genres": "Action|Drama",
    "networks": "",
    "popularity": 50.0,
    "tmdbVoteAverage": 7.0,
    "tmdbVoteCount": 1000,
    "imdbRating": 7.5,
    "imdbVoteCount": 5000,
    "revenue": 0,
    "budget": 0,
}


def testBuildTrendingTrackerLabelsRisingTitle(memDb):
    """A title with higher popularity today than yesterday should be labelled 'rising'."""
    _seedSilver(memDb, [
        {**BASE_ROW, "snapshotDate": YESTERDAY, "tmdbId": 1, "popularity": 40.0},
        {**BASE_ROW, "snapshotDate": TODAY,     "tmdbId": 1, "popularity": 60.0},
    ])
    buildTrendingTracker(memDb, TODAY)

    row = memDb.execute(
        "SELECT trendDirection, popularityChange FROM gold_trending_tracker WHERE snapshotDate = ?",
        [TODAY]
    ).fetchone()
    assert row[0] == "rising"
    assert abs(row[1] - 20.0) < 0.01


def testBuildTrendingTrackerLabelsNewTitle(memDb):
    """A title with no prior-day record should be labelled 'new'."""
    _seedSilver(memDb, [{**BASE_ROW, "snapshotDate": TODAY, "tmdbId": 99, "popularity": 30.0}])
    buildTrendingTracker(memDb, TODAY)

    row = memDb.execute(
        "SELECT trendDirection FROM gold_trending_tracker WHERE tmdbId = 99"
    ).fetchone()
    assert row[0] == "new"


def testBuildGenrePerformanceComputesWeightedRating(memDb):
    """Genre performance should produce vote-weighted ratings, not simple averages."""
    _seedSilver(memDb, [
        {**BASE_ROW, "tmdbId": 1, "genres": "Action", "imdbRating": 6.0, "imdbVoteCount": 1000},
        {**BASE_ROW, "tmdbId": 2, "genres": "Action", "imdbRating": 9.0, "imdbVoteCount": 9000},
        {**BASE_ROW, "tmdbId": 3, "genres": "Action", "imdbRating": 8.0, "imdbVoteCount": 1000},
    ])
    buildGenrePerformance(memDb, TODAY)

    row = memDb.execute(
        "SELECT weightedImdbRating FROM gold_genre_performance WHERE genre = 'Action'"
    ).fetchone()
    assert row is not None
    # Weighted: (6*1000 + 9*9000 + 8*1000) / (1000+9000+1000) = 89000/11000 ≈ 8.09
    assert abs(row[0] - (6*1000 + 9*9000 + 8*1000) / 11000) < 0.01


def testBuildNetworkScorecardFiltersToTv(memDb):
    """Network scorecard should include TV titles only, not movies."""
    _seedSilver(memDb, [
        {**BASE_ROW, "tmdbId": 1, "mediaType": "tv",    "networks": "HBO",    "imdbRating": 8.5},
        {**BASE_ROW, "tmdbId": 2, "mediaType": "tv",    "networks": "HBO",    "imdbRating": 7.5},
        {**BASE_ROW, "tmdbId": 3, "mediaType": "tv",    "networks": "HBO",    "imdbRating": 9.0},
        {**BASE_ROW, "tmdbId": 4, "mediaType": "movie", "networks": "HBO",    "imdbRating": 6.0},
    ])
    buildNetworkScorecard(memDb, TODAY)

    row = memDb.execute(
        "SELECT titleCount, avgImdbRating FROM gold_network_scorecard WHERE network = 'HBO'"
    ).fetchone()
    assert row is not None
    assert row[0] == 3  # only the 3 tv titles
    assert abs(row[1] - (8.5 + 7.5 + 9.0) / 3) < 0.01


def testBuildCatalogEngagementGroupsByDecade(memDb):
    """Catalog engagement should bucket titles into decades correctly."""
    _seedSilver(memDb, [
        {**BASE_ROW, "tmdbId": 1, "releaseYear": 1995, "popularity": 10.0},
        {**BASE_ROW, "tmdbId": 2, "releaseYear": 1998, "popularity": 20.0},
        {**BASE_ROW, "tmdbId": 3, "releaseYear": 2022, "popularity": 80.0},
    ])
    buildCatalogEngagement(memDb, TODAY)

    decades = memDb.execute(
        "SELECT releaseDecade FROM gold_catalog_engagement WHERE snapshotDate = ? ORDER BY releaseDecade",
        [TODAY]
    ).fetchall()
    decadeValues = [r[0] for r in decades]
    assert 1990 in decadeValues
    assert 2020 in decadeValues


def testBuildAllGoldMetricsReturnsSummary(memDb):
    """buildAllGoldMetrics should return a dict with all five metric keys."""
    _seedSilver(memDb, [
        {**BASE_ROW, "tmdbId": i, "releaseYear": 2020, "genres": "Action", "networks": ""}
        for i in range(1, 6)
    ])
    summary = buildAllGoldMetrics(memDb, TODAY)

    assert set(summary.keys()) == {
        "trending_tracker", "genre_performance", "network_scorecard",
        "content_velocity", "catalog_engagement",
    }
    assert all(isinstance(v, int) for v in summary.values())
