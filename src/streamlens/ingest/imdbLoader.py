"""
Downloads and parses IMDb's free non-commercial datasets.

IMDb publishes daily snapshots of their database as compressed TSV files.
These are free for personal and non-commercial use. This module downloads
only the files we need, caches them locally so we don't re-download on
every pipeline run, and returns clean DataFrames ready for bronze ingestion.

IMDb data terms: https://developer.imdb.com/non-commercial-datasets/
"""

import gzip
import logging
import shutil
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

IMDB_BASE_URL = "https://datasets.imdbws.com"

# The three files we use; keys are the local table names we'll use in bronze
IMDB_FILES = {
    "title.basics":  "title.basics.tsv.gz",
    "title.ratings": "title.ratings.tsv.gz",
}

# Cache directory: data/imdb/<today's date>/
def _getCacheDir(dataDir: Path) -> Path:
    cacheDir = dataDir / "imdb" / str(date.today())
    cacheDir.mkdir(parents=True, exist_ok=True)
    return cacheDir


def _downloadFile(url: str, destPath: Path) -> None:
    """Stream-download a file to disk, showing progress via logging."""
    logger.info("Downloading %s ...", url)
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as response:
        response.raise_for_status()
        with open(destPath, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                f.write(chunk)
    logger.info("Saved to %s", destPath)


def _decompressGzip(gzPath: Path) -> Path:
    """Decompress a .gz file and return the path of the uncompressed file."""
    tsvPath = gzPath.with_suffix("")  # strips .gz → .tsv
    if not tsvPath.exists():
        with gzip.open(gzPath, "rb") as gzFile, open(tsvPath, "wb") as tsvFile:
            shutil.copyfileobj(gzFile, tsvFile)
    return tsvPath


def loadImdbBasics(dataDir: Path) -> pd.DataFrame:
    """
    Download (or load from cache) title.basics and return a DataFrame.

    Filters to movies and TV series only — we skip shorts, podcasts, etc.
    Replaces IMDb's '\\N' null sentinel with actual NaN values.
    """
    cacheDir = _getCacheDir(dataDir)
    fileName = IMDB_FILES["title.basics"]
    gzPath = cacheDir / fileName
    tsvPath = gzPath.with_suffix("")

    if not tsvPath.exists():
        if not gzPath.exists():
            _downloadFile(f"{IMDB_BASE_URL}/{fileName}", gzPath)
        _decompressGzip(gzPath)

    df = pd.read_csv(
        tsvPath,
        sep="\t",
        na_values=r"\N",
        dtype=str,
        low_memory=False,
    )

    # Keep only the title types that matter for a streaming context
    keepTypes = {"movie", "tvSeries", "tvMiniSeries", "tvMovie"}
    df = df[df["titleType"].isin(keepTypes)].copy()

    logger.info("Loaded IMDb basics: %d titles", len(df))
    return df


def loadImdbRatings(dataDir: Path) -> pd.DataFrame:
    """
    Download (or load from cache) title.ratings and return a DataFrame.

    This is a small file — every rated title on IMDb with its average score
    and vote count. We join this onto basics in the silver layer.
    """
    cacheDir = _getCacheDir(dataDir)
    fileName = IMDB_FILES["title.ratings"]
    gzPath = cacheDir / fileName
    tsvPath = gzPath.with_suffix("")

    if not tsvPath.exists():
        if not gzPath.exists():
            _downloadFile(f"{IMDB_BASE_URL}/{fileName}", gzPath)
        _decompressGzip(gzPath)

    df = pd.read_csv(
        tsvPath,
        sep="\t",
        na_values=r"\N",
        dtype={"tconst": str, "averageRating": float, "numVotes": "Int64"},
    )

    logger.info("Loaded IMDb ratings: %d titles", len(df))
    return df
