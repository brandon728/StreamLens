"""
StreamLens pipeline orchestrator — runs the full Bronze → Silver → Gold flow.

Run from the command line with:
    python -m streamlens.pipeline

Or import and call main() from another script or scheduler.

What this script does (in order):
  1. Connect to (or create) the DuckDB database and initialize tables
  2. Reload historical silver data from parquet (so gold can compare vs. yesterday)
  3. Fetch today's trending titles from TMDB
  4. Fetch detailed metadata for each trending title
  5. Download today's IMDb dataset files (skipped if already cached)
  6. Write all raw data to the Bronze layer
  7. Clean and join data into the Silver layer
  8. Export silver_titles to parquet (committed to repo for next run's history)
  9. Compute all five Gold metrics for the dashboard
  10. Export Gold tables to parquet for the Streamlit Cloud dashboard
"""

import logging
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

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

SILVER_PARQUET = DATA_DIR / "silver_titles.parquet"


def _loadSilverHistory(conn, snapshotDate: date) -> None:
    """
    Pre-populate silver_titles with historical rows from the committed parquet file.

    GitHub Actions starts with a fresh DuckDB on every run. Without this step,
    the gold layer has no "yesterday" to compare against, so popularity changes
    and velocity scores are always zero. Loading prior days first fixes that.
    """
    if not SILVER_PARQUET.exists():
        logger.info("  → No silver history parquet found — first run")
        return

    historicalDf = pd.read_parquet(SILVER_PARQUET)

    # Normalize date column so the comparison works regardless of parquet storage type
    historicalDf["snapshotDate"] = pd.to_datetime(historicalDf["snapshotDate"]).dt.date

    # Exclude today — buildSilverTitles will write it fresh
    historicalDf = historicalDf[historicalDf["snapshotDate"] != snapshotDate]

    if historicalDf.empty:
        logger.info("  → Silver history parquet exists but has no prior dates")
        return

    # Skip dates already present in DuckDB (e.g. from a prior local run)
    existingDates = {
        r[0] for r in conn.execute("SELECT DISTINCT snapshotDate FROM silver_titles").fetchall()
    }
    historicalDf = historicalDf[~historicalDf["snapshotDate"].isin(existingDates)]

    if historicalDf.empty:
        logger.info("  → All historical dates already in DuckDB — nothing to load")
        return

    conn.execute("INSERT INTO silver_titles BY NAME SELECT * FROM historicalDf")
    uniqueDates = historicalDf["snapshotDate"].nunique()
    logger.info(
        "  → Loaded %d historical silver rows across %d prior date(s)",
        len(historicalDf),
        uniqueDates,
    )


def _exportSilverParquet(conn, dataDir: Path) -> None:
    """Export silver_titles to parquet, merging with any existing file so dates
    not present in this DuckDB (e.g. from prior GitHub Actions runs) are kept."""
    newDf = conn.execute("SELECT * FROM silver_titles ORDER BY snapshotDate DESC").df()
    outputPath = dataDir / "silver_titles.parquet"

    if outputPath.exists():
        existingDf = pd.read_parquet(outputPath)
        newDates = set(newDf["snapshotDate"].astype(str).unique())
        existingDf = existingDf[~existingDf["snapshotDate"].astype(str).isin(newDates)]
        df = pd.concat([newDf, existingDf], ignore_index=True).sort_values(
            "snapshotDate", ascending=False
        )
    else:
        df = newDf

    df.to_parquet(outputPath, index=False)
    logger.info("  → Saved %d silver rows to %s", len(df), outputPath.name)


def main() -> None:
    startTime = datetime.now(timezone.utc)
    snapshotDate = date.today()
    logger.info("=" * 60)
    logger.info("StreamLens pipeline starting — snapshot date: %s", snapshotDate)
    logger.info("=" * 60)

    # ------------------------------------------------------------------ 1. DB
    logger.info("Step 1/10 — Initializing database")
    conn = getConnection(DEFAULT_DB_PATH)
    initSchema(conn)

    # ------------------------------------------------------------------ 2. Historical silver
    logger.info("Step 2/10 — Loading historical silver data for day-over-day comparisons")
    _loadSilverHistory(conn, snapshotDate)

    # ------------------------------------------------------------------ 3. TMDB trending
    logger.info("Step 3/10 — Fetching TMDB trending titles")
    trendingRecords = fetchTrending(mediaType="all", timeWindow="day")
    logger.info("  → %d trending titles fetched", len(trendingRecords))

    # ------------------------------------------------------------------ 4. TMDB details
    logger.info("Step 4/10 — Fetching TMDB title details")
    detailRecords = list(fetchDetailsForTrending(trendingRecords))
    logger.info("  → %d detail records fetched", len(detailRecords))

    # ------------------------------------------------------------------ 5. IMDb datasets
    logger.info("Step 5/10 — Loading IMDb datasets (cached if already downloaded today)")
    imdbBasicsDf = loadImdbBasics(DATA_DIR)
    imdbRatingsDf = loadImdbRatings(DATA_DIR)

    # ------------------------------------------------------------------ 6. Bronze
    logger.info("Step 6/10 — Writing to Bronze layer")
    ingestedAt = datetime.now(timezone.utc)
    writeTmdbTrending(conn, trendingRecords, ingestedAt)
    writeTmdbDetails(conn, detailRecords, ingestedAt)
    writeImdbBasics(conn, imdbBasicsDf, ingestedAt)
    writeImdbRatings(conn, imdbRatingsDf, ingestedAt)

    # ------------------------------------------------------------------ 7. Silver
    logger.info("Step 7/10 — Building Silver layer")
    silverRows = buildSilverTitles(conn, snapshotDate)
    logger.info("  → %d rows in silver_titles for %s", silverRows, snapshotDate)

    # ------------------------------------------------------------------ 8. Export silver
    logger.info("Step 8/10 — Exporting silver_titles to parquet")
    _exportSilverParquet(conn, DATA_DIR)

    # ------------------------------------------------------------------ 9. Gold
    logger.info("Step 9/10 — Computing Gold metrics")
    goldCounts = buildAllGoldMetrics(conn, snapshotDate)
    for metricName, rowCount in goldCounts.items():
        logger.info("  → gold_%s: %d rows", metricName, rowCount)

    # ----------------------------------------------------------------- 10. Gold parquets
    logger.info("Step 10/10 — Exporting Gold tables to parquet")
    exportGoldParquets(conn, DATA_DIR)

    conn.close()

    elapsed = (datetime.now(timezone.utc) - startTime).total_seconds()
    logger.info("=" * 60)
    logger.info("Pipeline complete in %.1fs", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
