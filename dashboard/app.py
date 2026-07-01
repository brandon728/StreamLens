"""
StreamLens Dashboard — visualizes the five Gold layer metrics.

Reads from parquet files in data/gold/ so it works both locally
and on Streamlit Community Cloud without needing a DuckDB file.

Run locally with:  streamlit run dashboard/app.py
"""

from pathlib import Path
import pandas as pd
import plotly.express as px
import streamlit as st

GOLD_DIR = Path(__file__).resolve().parents[1] / "data" / "gold"

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="StreamLens",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("🎬 StreamLens")
st.caption(
    "A daily-refreshing content analytics pipeline powered by TMDB + IMDb data. "
    "Built to demonstrate end-to-end data product thinking."
)


# ── Data loading (cached for 1 hour) ─────────────────────────────────────────
@st.cache_data(ttl=3600)
def loadParquet(name: str) -> pd.DataFrame:
    path = GOLD_DIR / f"{name}.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def filterDate(df: pd.DataFrame, selectedDate) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["snapshotDate"] == str(selectedDate)].copy()


# ── Check data exists ─────────────────────────────────────────────────────────
trendingAll = loadParquet("trending_tracker")
if trendingAll.empty:
    st.warning(
        "No data found in `data/gold/`. "
        "Run `uv run python -m streamlens.pipeline` to populate it."
    )
    st.stop()

# ── Last refresh status ───────────────────────────────────────────────────────
latestDate = pd.to_datetime(trendingAll["snapshotDate"].max()).date()
totalDates = trendingAll["snapshotDate"].nunique()
col_title, col_status = st.columns([4, 1])
with col_status:
    st.success(f"Last refresh: **{latestDate}**  \n{totalDates} days of data")

# ── Sidebar: date picker ──────────────────────────────────────────────────────
availableDates = sorted(trendingAll["snapshotDate"].unique(), reverse=True)

selectedDate = st.sidebar.selectbox(
    "Snapshot date",
    options=availableDates,
    format_func=lambda d: str(d),
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    "**Data sources**\n"
    "- [TMDB API](https://www.themoviedb.org/)\n"
    "- [IMDb Datasets](https://developer.imdb.com/non-commercial-datasets/)\n\n"
    "Refreshed daily via GitHub Actions."
)

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "📈 Trending",
    "🎭 Genre Performance",
    "📡 Network Scorecard",
    "🚀 Content Velocity",
    "📼 Catalog vs. New",
])


# ── Tab 1: Trending Tracker ───────────────────────────────────────────────────
with tab1:
    st.subheader("Daily Trending Tracker")
    st.markdown(
        "Which titles are most popular today, and are they rising or falling? "
        "Popularity is TMDB's composite score based on page views, ratings, and watchlist adds."
    )

    trendingDf = filterDate(trendingAll, selectedDate).sort_values("popularity", ascending=False).head(50)

    if trendingDf.empty:
        st.info("No trending data for this date.")
    else:
        directionEmoji = {"rising": "↑", "falling": "↓", "stable": "→", "new": "★"}
        trendingDf["direction"] = trendingDf["trendDirection"].map(directionEmoji).fillna("?")

        col1, col2 = st.columns([3, 2])
        with col1:
            fig = px.bar(
                trendingDf.head(20),
                x="popularity",
                y="title",
                color="trendDirection",
                orientation="h",
                color_discrete_map={"rising": "#22c55e", "falling": "#ef4444", "stable": "#94a3b8", "new": "#a78bfa"},
                labels={"popularity": "Popularity Score", "title": ""},
                title="Top 20 Trending Titles",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, height=550)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            st.dataframe(
                trendingDf[["direction", "title", "mediaType", "popularity", "popularityChange"]]
                .rename(columns={
                    "direction": "", "title": "Title", "mediaType": "Type",
                    "popularity": "Score", "popularityChange": "Δ vs Yesterday",
                })
                .head(20),
                hide_index=True,
                use_container_width=True,
            )

    # ── 7-day trend line chart ────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("7-Day Popularity Trend")
    st.markdown(
        "How has each title's popularity shifted over the past week? "
        "Tracks the top 20 titles by their most recent popularity score."
    )

    # Top 20 titles on the most recent date
    recentDate = trendingAll["snapshotDate"].max()
    top20Titles = (
        trendingAll[trendingAll["snapshotDate"] == recentDate]
        .sort_values("popularity", ascending=False)
        .head(20)["title"]
        .tolist()
    )

    # All dates available, capped at 7
    last7Dates = sorted(trendingAll["snapshotDate"].unique())[-7:]

    trendLineDf = (
        trendingAll[
            trendingAll["title"].isin(top20Titles) &
            trendingAll["snapshotDate"].isin(last7Dates)
        ]
        .copy()
    )
    trendLineDf["snapshotDate"] = pd.to_datetime(trendLineDf["snapshotDate"])

    if len(last7Dates) < 2:
        st.info("Trend chart requires at least 2 days of data. Check back tomorrow.")
    else:
        figLine = px.line(
            trendLineDf.sort_values("snapshotDate"),
            x="snapshotDate",
            y="popularity",
            color="title",
            markers=True,
            labels={
                "snapshotDate": "Date",
                "popularity": "Popularity Score",
                "title": "Title",
            },
            title=f"Top 20 Titles — Popularity Over Last {len(last7Dates)} Days",
        )
        figLine.update_layout(
            height=500,
            xaxis=dict(tickformat="%b %d"),
            legend=dict(
                orientation="v",
                yanchor="top",
                y=1,
                xanchor="left",
                x=1.02,
                font=dict(size=11),
            ),
        )
        st.plotly_chart(figLine, use_container_width=True)


# ── Tab 2: Genre Performance ──────────────────────────────────────────────────
with tab2:
    st.subheader("Genre Performance Index")
    st.markdown(
        "Which genres produce the highest-rated content? "
        "Ratings are vote-weighted — genres with more community reviews carry more influence."
    )

    genreDf = filterDate(loadParquet("genre_performance"), selectedDate).sort_values(
        "weightedImdbRating", ascending=False, na_position="last"
    )

    if genreDf.empty:
        st.info("No genre data for this date.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(
                genreDf.dropna(subset=["weightedImdbRating"]).head(15),
                x="weightedImdbRating",
                y="genre",
                orientation="h",
                color="weightedImdbRating",
                color_continuous_scale="Viridis",
                labels={"weightedImdbRating": "Weighted IMDb Rating", "genre": "Genre"},
                title="Top Genres by Vote-Weighted Rating",
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"}, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig2 = px.scatter(
                genreDf.dropna(subset=["weightedImdbRating"]),
                x="avgPopularity",
                y="weightedImdbRating",
                size="titleCount",
                text="genre",
                labels={"avgPopularity": "Avg Popularity", "weightedImdbRating": "IMDb Rating"},
                title="Rating vs. Popularity by Genre",
            )
            fig2.update_traces(textposition="top center")
            st.plotly_chart(fig2, use_container_width=True)


# ── Tab 3: Network Scorecard ──────────────────────────────────────────────────
with tab3:
    st.subheader("Network Content Scorecard")
    st.markdown(
        "Which streaming networks and broadcasters produce the best-rated and most popular content? "
        "Only TV titles are included. Minimum 3 titles per network."
    )

    networkDf = filterDate(loadParquet("network_scorecard"), selectedDate).sort_values(
        "avgImdbRating", ascending=False, na_position="last"
    ).head(25)

    if networkDf.empty:
        st.info("No network data for this date.")
    else:
        fig = px.scatter(
            networkDf.dropna(subset=["avgImdbRating"]),
            x="avgPopularity",
            y="avgImdbRating",
            size="titleCount",
            text="network",
            color="avgImdbRating",
            color_continuous_scale="RdYlGn",
            labels={"avgPopularity": "Avg Popularity", "avgImdbRating": "Avg IMDb Rating", "titleCount": "Titles"},
            title="Network: Rating vs. Popularity (bubble size = # of titles)",
        )
        fig.update_traces(textposition="top center")
        fig.update_layout(height=550, coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            networkDf.rename(columns={
                "network": "Network", "titleCount": "# Titles",
                "avgImdbRating": "Avg IMDb Rating", "avgPopularity": "Avg Popularity",
            }),
            hide_index=True,
            use_container_width=True,
        )


# ── Tab 4: Content Velocity ───────────────────────────────────────────────────
with tab4:
    st.subheader("Content Velocity Score")
    st.markdown(
        "Which titles are breaking out (rapid popularity gain) and which are fading? "
        "Velocity is normalized 0–100 based on day-over-day popularity change."
    )

    velocityDf = filterDate(loadParquet("content_velocity"), selectedDate).sort_values(
        "velocityScore", ascending=False
    ).head(50)

    if velocityDf.empty:
        st.info("No velocity data for this date.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            breakoutDf = velocityDf[velocityDf["velocityLabel"].isin(["breakout", "climbing"])].head(10)
            fig = px.bar(
                breakoutDf,
                x="velocityScore",
                y="title",
                color="velocityLabel",
                orientation="h",
                color_discrete_map={"breakout": "#f59e0b", "climbing": "#22c55e"},
                title="Breakouts & Climbers",
                labels={"velocityScore": "Velocity Score", "title": ""},
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fadingDf = velocityDf[velocityDf["velocityLabel"] == "fading"].tail(10)
            fig2 = px.bar(
                fadingDf,
                x="velocityScore",
                y="title",
                orientation="h",
                color_discrete_sequence=["#ef4444"],
                title="Fading Titles",
                labels={"velocityScore": "Velocity Score", "title": ""},
            )
            fig2.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig2, use_container_width=True)

        labelCounts = velocityDf["velocityLabel"].value_counts().reset_index()
        labelCounts.columns = ["Label", "Count"]
        st.dataframe(labelCounts, hide_index=True, use_container_width=False)


# ── Tab 5: Catalog vs. New Release ───────────────────────────────────────────
with tab5:
    st.subheader("Catalog vs. New Release Engagement")
    st.markdown(
        "Are audiences gravitating toward new releases or rediscovering older catalog? "
        "Each bar represents titles from that release decade currently in the trending set."
    )

    catalogDf = filterDate(loadParquet("catalog_engagement"), selectedDate).sort_values("releaseDecade")

    if catalogDf.empty:
        st.info("No catalog data for this date.")
    else:
        catalogDf["decade"] = catalogDf["releaseDecade"].astype(str) + "s"

        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(
                catalogDf,
                x="decade",
                y="avgPopularity",
                color="mediaType",
                barmode="group",
                labels={"decade": "Release Decade", "avgPopularity": "Avg Popularity", "mediaType": "Type"},
                title="Average Popularity by Release Decade",
                color_discrete_map={"movie": "#6366f1", "tv": "#f97316"},
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig2 = px.bar(
                catalogDf.dropna(subset=["avgImdbRating"]),
                x="decade",
                y="avgImdbRating",
                color="mediaType",
                barmode="group",
                labels={"decade": "Release Decade", "avgImdbRating": "Avg IMDb Rating", "mediaType": "Type"},
                title="Average IMDb Rating by Release Decade",
                color_discrete_map={"movie": "#6366f1", "tv": "#f97316"},
            )
            st.plotly_chart(fig2, use_container_width=True)
