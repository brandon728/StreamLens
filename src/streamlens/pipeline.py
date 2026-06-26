"""
StreamLens pipeline orchestrator — runs the full Bronze → Silver → Gold flow.

Run from the command line with:
    python -m streamlens.pipeline

Or import and call main() from another script or scheduler.

What this script does (in order):
  1. Connect to (or create) the DuckDB database and initialize tables
  2. Fetch today's trending titles from TMDB
  3. Fetch detailed metadata for each trending title
  4. Download today's IMDb dataset files (skipped if already cached)
  5. Write all raw data to the Bronze layer
  6. Clean and join data into the Silver layer
  7. Compute all five Gold metrics for the dashboard
"""

import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from streamlens.database import getConnection, initSchema, DEFAULT_DB_PATH
from streamlens.ingest.tmdbClient import fetchTrending, fetchDetailsForTrending
from streamlens.ingest.imdbLoader import loadImdbBasics, loadImdbRatings
from streamlens.transform.bronze import (
    writeTmdbTrending,
    writeTmdbDetails,
    writeImdbBasics,
    writeImdbRatings,
)
from streamlens.transform.silver import buildSilverTitles
from streamlens.transform.gold import buildAllGoldMetrics, exportGoldParquets

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("streamlens.pipeline")

# The data/ directory sits at the project root (two levels above this file)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def main() -> None:
    startTime = datetime.now(timezone.utc)
    snapshotDate = date.today()
    logger.info("=" * 60)
    logger.info("StreamLens pipeline starting — snapshot date: %s", snapshotDate)
    logger.info("=" * 60)

    # ------------------------------------------------------------------ 1. DB
    logger.info("Step 1/7 — Initializing database")
    conn = getConnection(DEFAULT_DB_PATH)
    initSchema(conn)

    # ------------------------------------------------------------------ 2. TMDB trending
    logger.info("Step 2/7 — Fetching TMDB trending titles")
    trendingRecords = fetchTrending(mediaType="all", timeWindow="day")
    logger.info("  → %d trending titles fetched", len(trendingRecords))

    # ------------------------------------------------------------------ 3. TMDB details
    logger.info("Step 3/7 — Fetching TMDB title details")
    detailRecords = list(fetchDetailsForTrending(trendingRecords))
    logger.info("  → %d detail records fetched", len(detailRecords))

    # ------------------------------------------------------------------ 4. IMDb datasets
    logger.info("Step 4/7 — Loading IMDb datasets (cached if already downloaded today)")
    imdbBasicsDf = loadImdbBasics(DATA_DIR)
    imdbRatingsDf = loadImdbRatings(DATA_DIR)

    # ------------------------------------------------------------------ 5. Bronze
    logger.info("Step 5/7 — Writing to Bronze layer")
    ingestedAt = datetime.now(timezone.utc)
    writeTmdbTrending(conn, trendingRecords, ingestedAt)
    writeTmdbDetails(conn, detailRecords, ingestedAt)
    writeImdbBasics(conn, imdbBasicsDf, ingestedAt)
    writeImdbRatings(conn, imdbRatingsDf, ingestedAt)

    # ------------------------------------------------------------------ 6. Silver
    logger.info("Step 6/7 — Building Silver layer")
    silverRows = buildSilverTitles(conn, snapshotDate)
    logger.info("  → %d rows in silver_titles for %s", silverRows, snapshotDate)

    # ------------------------------------------------------------------ 7. Gold
    logger.info("Step 7/7 — Computing Gold metrics")
    goldCounts = buildAllGoldMetrics(conn, snapshotDate)
    for metricName, rowCount in goldCounts.items():
        logger.info("  → gold_%s: %d rows", metricName, rowCount)

    # ------------------------------------------------------------------ 8. Parquet export
    logger.info("Step 8/8 — Exporting Gold tables to parquet")
    exportGoldParquets(conn, DATA_DIR)

    conn.close()

    elapsed = (datetime.now(timezone.utc) - startTime).total_seconds()
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1fs", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
