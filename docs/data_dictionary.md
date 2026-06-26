# StreamLens Data Dictionary

This document defines every field in the Gold layer — the metrics that power the StreamLens dashboard. Fields are described in plain language for readers who are not data engineers.

For the full database schema (all Bronze and Silver fields), see [src/streamlens/database.py](../src/streamlens/database.py).

---

## How to read this document

Each section covers one Gold table. Fields are listed with:
- **Type** — the kind of data stored (number, text, date, etc.)
- **Description** — what the field means in plain English
- **Example** — a realistic sample value

---

## gold_trending_tracker

*One row per title per day. Answers: "What's trending today, and is it gaining or losing momentum?"*

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `snapshotDate` | Date | The calendar day this record was captured | `2025-06-25` |
| `tmdbId` | Number | TMDB's unique identifier for this title | `550` |
| `title` | Text | The title's display name | `"Fight Club"` |
| `mediaType` | Text | Whether this is a movie or TV show | `"movie"` or `"tv"` |
| `popularity` | Decimal | TMDB's composite popularity score. Higher = more popular. Reflects page views, watchlist adds, and rating activity on TMDB. Not directly comparable to streaming viewership numbers. | `85.4` |
| `popularityChange` | Decimal | How much the popularity score changed compared to yesterday. Positive = growing audience interest, negative = declining. Zero on first appearance. | `+12.3` |
| `trendDirection` | Text | A human-readable summary of the change. `rising` = up >5%, `falling` = down >5%, `stable` = within 5%, `new` = first time appearing in trending | `"rising"` |

---

## gold_genre_performance

*One row per genre per day. Answers: "Which types of content are audiences rating most highly?"*

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `snapshotDate` | Date | The calendar day this record was captured | `2025-06-25` |
| `genre` | Text | The content genre. A title can belong to multiple genres and will contribute to each. | `"Action"` |
| `titleCount` | Number | How many trending titles belong to this genre on this day | `14` |
| `weightedImdbRating` | Decimal | The average IMDb rating for this genre, weighted by vote count. A title with 100,000 votes influences the average more than one with 50 votes. Scale is 0–10. | `7.4` |
| `avgPopularity` | Decimal | The average TMDB popularity score across all titles in this genre | `62.8` |

**Why vote-weighting matters:** A simple average would let a niche film with 10 enthusiastic reviews inflate a genre's rating. Vote-weighting reflects what the broader audience actually thinks.

---

## gold_network_scorecard

*One row per network per day. Answers: "Which streaming networks and broadcasters produce the most acclaimed content?"*

Only TV titles are included — movies are distributed to theaters, not networks.
Networks with fewer than 3 titles in the trending set are excluded to avoid misleading averages.

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `snapshotDate` | Date | The calendar day this record was captured | `2025-06-25` |
| `network` | Text | The network or streaming platform name | `"HBO"` |
| `titleCount` | Number | Number of trending TV titles from this network | `7` |
| `avgImdbRating` | Decimal | Average IMDb rating across the network's trending titles. Scale 0–10. | `8.2` |
| `avgPopularity` | Decimal | Average TMDB popularity score across the network's trending titles | `74.1` |

---

## gold_content_velocity

*One row per title per day. Answers: "Which titles are surging in interest and which are losing it?"*

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `snapshotDate` | Date | The calendar day this record was captured | `2025-06-25` |
| `tmdbId` | Number | TMDB's unique identifier for this title | `1396` |
| `title` | Text | The title's display name | `"Breaking Bad"` |
| `mediaType` | Text | Movie or TV show | `"tv"` |
| `velocityScore` | Decimal | A 0–100 score representing how fast this title's popularity is growing relative to all other titles today. 100 = fastest-growing, 0 = fastest-declining. | `94.7` |
| `velocityLabel` | Text | Human-readable category based on velocity score and current popularity level. See below. | `"breakout"` |

**Velocity labels explained:**

| Label | Meaning |
|-------|---------|
| `breakout` | Top 10% velocity score AND already highly popular. This title is a current cultural moment. |
| `climbing` | Velocity score above 55. Growing faster than most. |
| `steady` | Velocity score between 45 and 55. Holding its audience. |
| `fading` | Velocity score below 45. Losing audience interest. |

---

## gold_catalog_engagement

*One row per decade + media type per day. Answers: "Are people watching new content or rediscovering classics?"*

This metric helps answer a key streaming strategy question: should the platform invest in new originals, or does licensing back-catalog content deliver comparable engagement?

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `snapshotDate` | Date | The calendar day this record was captured | `2025-06-25` |
| `releaseDecade` | Number | The decade the content was originally released. 1990 = titles from 1990–1999, 2020 = titles from 2020–2029. | `1990` |
| `mediaType` | Text | Movie or TV show | `"movie"` |
| `titleCount` | Number | Number of trending titles from this decade | `5` |
| `avgPopularity` | Decimal | Average TMDB popularity for titles from this decade currently in the trending set | `41.2` |
| `avgImdbRating` | Decimal | Average IMDb rating for titles from this decade in the trending set | `8.1` |

**Interpreting the data:** High popularity for older decades means audiences are actively seeking out catalog content — a signal that licensing classic titles may deliver outsized engagement relative to cost.

---

## A note on data freshness

All Gold tables are rebuilt each time the pipeline runs (once daily). The `snapshotDate` field tells you exactly when each record was calculated. Comparisons across dates (like trending direction) are based on the previous calendar day's snapshot.

IMDb ratings reflect the state of IMDb's dataset at the time of download (refreshed daily). TMDB data is fetched live at pipeline run time.
