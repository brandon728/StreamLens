"""
Tests for the Silver layer transformation.

Uses an in-memory DuckDB database so tests run fast with no file I/O.
"""

from datetime import date, datetime, timezone

import duckdb
import pandas as pd
import pytest

from streamlens.database import initSchema
from streamlens.transform.bronze import writeTmdbTrending, writeTmdbDetails, writeImdbRatings
from streamlens.transform.silver import buildSilverTitles, _parseGenreNames, _parseNetworkNames


@pytest.fixture
def memDb():
    """Provide a fresh in-memory DuckDB connection for each test."""
    conn = duckdb.connect(":memory:")
    initSchema(conn)
    yield conn
    conn.close()


def testParseGenreNamesHappyPath():
    """_parseGenreNames should convert a JSON genre array to pipe-separated names."""
    genresJson = '[{"id": 28, "name": "Action"}, {"id": 12, "name": "Adventure"}]'
    result = _parseGenreNames(genresJson)
    assert result == "Action|Adventure"


def testParseGenreNamesEmpty():
    """_parseGenreNames should return an empty string for null or empty input."""
    assert _parseGenreNames(None) == ""
    assert _parseGenreNames("") == ""
    assert _parseGenreNames("[]") == ""


def testParseNetworkNames():
    """_parseNetworkNames should convert a TMDB networks JSON array to pipe-separated names."""
    networksJson = '[{"id": 49, "name": "HBO"}, {"id": 2739, "name": "Disney+"}]'
    result = _parseNetworkNames(networksJson)
    assert result == "HBO|Disney+"


def testBuildSilverTitlesWritesRows(memDb):
    """buildSilverTitles should produce one row per unique tmdbId for the given date."""
    ingestedAt = datetime.now(timezone.utc)
    trendingRecords = [
        {
            "id": 101, "media_type": "movie", "title": "Alpha",
            "popularity": 75.0, "vote_average": 7.2, "vote_count": 3000,
            "release_date": "2022-06-15", "genre_ids": [28],
        },
        {
            "id": 202, "media_type": "tv", "name": "Beta",
            "popularity": 50.0, "vote_average": 8.0, "vote_count": 1500,
            "first_air_date": "2021-01-10", "genre_ids": [18],
        },
    ]
    writeTmdbTrending(memDb, trendingRecords, ingestedAt)

    rowCount = buildSilverTitles(memDb, date.today())
    assert rowCount == 2

    df = memDb.execute("SELECT * FROM silver_titles").df()
    assert set(df["title"]) == {"Alpha", "Beta"}


def testBuildSilverTitlesIsIdempotent(memDb):
    """Running buildSilverTitles twice for the same date should not create duplicates."""
    ingestedAt = datetime.now(timezone.utc)
    trendingRecords = [
        {
            "id": 303, "media_type": "movie", "title": "Gamma",
            "popularity": 60.0, "vote_average": 7.0, "vote_count": 500,
            "release_date": "2023-03-01", "genre_ids": [],
        }
    ]
    writeTmdbTrending(memDb, trendingRecords, ingestedAt)

    buildSilverTitles(memDb, date.today())
    buildSilverTitles(memDb, date.today())  # second run should overwrite, not duplicate

    count = memDb.execute("SELECT COUNT(*) FROM silver_titles").fetchone()[0]
    assert count == 1


def testBuildSilverTitlesJoinsImdbRating(memDb):
    """Silver layer should join IMDb rating when imdbId matches."""
    ingestedAt = datetime.now(timezone.utc)
    trendingRecords = [
        {
            "id": 404, "media_type": "movie", "title": "Delta",
            "popularity": 90.0, "vote_average": 6.5, "vote_count": 200,
            "release_date": "2020-11-20", "genre_ids": [],
        }
    ]
    writeTmdbTrending(memDb, trendingRecords, ingestedAt)

    detailRecords = [
        {
            "id": 404, "_media_type": "movie",
            "external_ids": {"imdb_id": "tt9999999"},
            "runtime": 105, "revenue": 0, "budget": 0,
            "genres": [], "networks": [],
        }
    ]
    writeTmdbDetails(memDb, detailRecords, ingestedAt)

    imdbDf = pd.DataFrame([{
        "tconst": "tt9999999",
        "averageRating": 8.5,
        "numVotes": 10000,
    }])
    writeImdbRatings(memDb, imdbDf, ingestedAt)

    buildSilverTitles(memDb, date.today())

    row = memDb.execute(
        "SELECT imdbRating FROM silver_titles WHERE tmdbId = 404"
    ).fetchone()
    assert row is not None
    assert abs(row[0] - 8.5) < 0.001
