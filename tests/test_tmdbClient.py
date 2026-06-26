"""
Tests for the TMDB API client.

These tests validate response parsing logic using mocked HTTP responses
so no real API key or network connection is needed.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from streamlens.ingest.tmdbClient import fetchTrending, fetchDetailsForTrending


MOCK_TRENDING_RESPONSE = {
    "page": 1,
    "total_pages": 1,
    "results": [
        {
            "id": 1,
            "media_type": "movie",
            "title": "Test Movie",
            "original_title": "Test Movie",
            "overview": "A test film.",
            "popularity": 85.4,
            "vote_average": 7.5,
            "vote_count": 1200,
            "release_date": "2024-01-15",
            "genre_ids": [28, 12],
        },
        {
            "id": 2,
            "media_type": "tv",
            "name": "Test Show",
            "original_name": "Test Show",
            "overview": "A test series.",
            "popularity": 62.1,
            "vote_average": 8.1,
            "vote_count": 4500,
            "first_air_date": "2023-09-01",
            "genre_ids": [18],
        },
    ],
}


@patch("streamlens.ingest.tmdbClient.os.getenv", return_value="fake-api-key")
@patch("streamlens.ingest.tmdbClient.httpx.Client")
def testFetchTrendingReturnsResults(mockClientClass, mockGetenv):
    """fetchTrending should return a flat list of result dicts."""
    mockResponse = MagicMock()
    mockResponse.json.return_value = MOCK_TRENDING_RESPONSE
    mockResponse.raise_for_status.return_value = None

    mockClient = MagicMock()
    mockClient.__enter__ = MagicMock(return_value=mockClient)
    mockClient.__exit__ = MagicMock(return_value=False)
    mockClient.get.return_value = mockResponse
    mockClientClass.return_value = mockClient

    results = fetchTrending(mediaType="all", timeWindow="day")

    assert len(results) == 2
    assert results[0]["id"] == 1
    assert results[0]["media_type"] == "movie"
    assert results[1]["media_type"] == "tv"


@patch("streamlens.ingest.tmdbClient.os.getenv", return_value="fake-api-key")
@patch("streamlens.ingest.tmdbClient.httpx.Client")
def testFetchDetailsForTrendingYieldsDetailRecords(mockClientClass, mockGetenv):
    """fetchDetailsForTrending should yield one enriched dict per valid record."""
    mockDetailResponse = MagicMock()
    mockDetailResponse.json.return_value = {
        "id": 1,
        "external_ids": {"imdb_id": "tt1234567"},
        "runtime": 120,
        "revenue": 50000000,
        "budget": 20000000,
        "genres": [{"id": 28, "name": "Action"}],
    }
    mockDetailResponse.raise_for_status.return_value = None

    mockClient = MagicMock()
    mockClient.__enter__ = MagicMock(return_value=mockClient)
    mockClient.__exit__ = MagicMock(return_value=False)
    mockClient.get.return_value = mockDetailResponse
    mockClientClass.return_value = mockClient

    trendingRecords = [{"id": 1, "media_type": "movie"}]
    details = list(fetchDetailsForTrending(trendingRecords))

    assert len(details) == 1
    assert details[0]["_media_type"] == "movie"
    assert details[0]["external_ids"]["imdb_id"] == "tt1234567"


def testFetchTrendingRaisesWithoutApiKey():
    """fetchTrending should raise EnvironmentError when TMDB_API_KEY is missing."""
    with patch("streamlens.ingest.tmdbClient.os.getenv", return_value=""):
        with pytest.raises(EnvironmentError, match="TMDB_API_KEY"):
            fetchTrending()
