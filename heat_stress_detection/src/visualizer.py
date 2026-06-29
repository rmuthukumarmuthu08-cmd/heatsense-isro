"""
visualizer.py — Map and Chart Generation

Purpose:
    All visualisation functions for the Streamlit dashboard.
    Folium maps (interactive) + Plotly charts (interactive) + Matplotlib (static).

Outputs:
    - Folium Map objects (rendered via streamlit-folium)
    - Plotly Figure objects (rendered via st.plotly_chart)
    - Matplotlib Figure objects (rendered via st.pyplot)
"""

import logging
from typing import Dict, List, Optional

import folium
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from folium.plugins import HeatMap, MarkerCluster

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour constants
# ---------------------------------------------------------------------------
HEAT_ZONE_COLORS = {
    "Very Low":  "#2196F3",
    "Low":       "#4CAF50",
    "Moderate":  "#FFEB3B",
    "High":      "#FF9800",
    "Extreme":   "#F44336",
}

SEVERITY_COLORS = {
    "Critical":  "#B71C1C",
    "Very High": "#E53935",
    "High":      "#F4511E",
    "Moderate":  "#FB8C00",
    "Low":       "#43A047",
}

LST_COLORSCALE = [
    [0.0, "#2196F3"],    # Very cold – blue
    [0.25, "#4CAF50"],   # Cool – green
    [0.50, "#FFEB3B"],   # Moderate – yellow
    [0.75, "#FF9800"],   # Hot – orange
    [1.0,  "#B71C1C"],   # Extreme – dark red
]

DELHI_CENTER = [28.6139, 77.2090]


# ---------------------------------------------------------------------------
# Folium Maps
# ---------------------------------------------------------------------------

def create_lst_heatmap(df: pd.DataFrame, zoom: int = 11) -> folium.Map:
    """
    Create an interactive Folium heatmap showing LST intensity across Delhi.

    Parameters
    ----------
    df   : DataFrame with lat, lon, LST columns
    zoom : Initial map zoom level

    Returns
    -------
    folium.Map with HeatMap layer
    """
    m = folium.Map(
        location=DELHI_CENTER,
        zoom_start=zoom,
        tiles="CartoDB positron",
        control_scale=True,
    )

    # Normalise LST for heatmap intensity (0-1)
    lst_min, lst_max = df["LST"].min(), df["LST"].max()
    heat_data = [
        [row["lat"], row["lon"], (row["LST"] - lst_min) / (lst_max - lst_min)]
        for _, row in df.iterrows()
    ]

    HeatMap(
        heat_data,
        name="LST Heat Map",
        min_opacity=0.4,
        max_zoom=18,
        radius=14,
        blur=10,
        gradient={
            0.0: "#2196F3",
            0.3: "#4CAF50",
            0.5: "#FFEB3B",
            0.75: "#FF9800",
            1.0: "#B71C1C",
        },
    ).add_to(m)

    # Add color legend
    _add_lst_legend(m, lst_min, lst_max)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def create_hotspot_map(df: pd.DataFrame, hotspot_zones: pd.DataFrame,
                       zoom: int = 11) -> folium.Map:
    """
    Create a Folium map with individual hotspot points and cluster markers.

    Parameters
    ----------
    df            : Full DataFrame with heat_zone column
    hotspot_zones : Aggregated hotspot zones from hotspot_detector
    zoom          : Initial zoom level
    """
    m = folium.Map(
        location=DELHI_CENTER,
        zoom_start=zoom,
        tiles="CartoDB dark_matter",
        control_scale=True,
    )

    # Add extreme + high heat points as a heatmap background
    extreme_df = df[df["heat_zone"].isin(["Extreme", "High"])]
    if not extreme_df.empty:
        heat_data = [[r["lat"], r["lon"], r["hotspot_score"]]
                     for _, r in extreme_df.iterrows()
                     if "hotspot_score" in extreme_df.columns]
        if heat_data:
            HeatMap(heat_data, radius=12, blur=10, name="Hotspot Density",
                    gradient={"0.4": "#FF9800", "0.65": "#E91E63", "1": "#B71C1C"}).add_to(m)

    # Add cluster markers for top hotspot zones
    if not hotspot_zones.empty:
        cluster = MarkerCluster(name="Hotspot Zones")
        for _, zone in hotspot_zones.iterrows():
            color = SEVERITY_COLORS.get(str(zone.get("severity_label", "High")), "#FF9800")
            score = float(zone.get("mean_hotspot_score", 0))
            lst = float(zone.get("mean_LST", 0))
            pop = int(zone.get("total_population", 0))
            rank = int(zone.get("rank", 0))
            zone_name = str(zone.get("zone_name", f"Zone {rank}"))

            popup_html = f"""
            <div style='font-family:Arial;width:220px;'>
            <h4 style='color:{color};margin:4px 0'>🔥 Rank #{rank}: {zone_name}</h4>
            <table style='width:100%;font-size:12px;'>
            <tr><td>🌡️ Mean LST</td><td><b>{lst:.1f}°C</b></td></tr>
            <tr><td>⚠️ Severity</td><td><b>{zone.get('severity_label','N/A')}</b></td></tr>
            <tr><td>👥 Population</td><td><b>{pop:,}</b></td></tr>
            <tr><td>📐 Area</td><td><b>{zone.get('area_km2',0):.2f} km²</b></td></tr>
            <tr><td>🎯 Score</td><td><b>{score:.3f}</b></td></tr>
            </table></div>"""

            folium.CircleMarker(
                location=[float(zone["centroid_lat"]), float(zone["centroid_lon"])],
                radius=8 + score * 10,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.7,
                popup=folium.Popup(popup_html, max_width=250),
                tooltip=f"#{rank} {zone_name} — {lst:.1f}°C",
            ).add_to(cluster)
        cluster.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def create_population_overlay_map(df: pd.DataFrame, hotspot_zones: pd.DataFrame,
                                  zoom: int = 11) -> folium.Map:
    """Create map showing population density overlaid on heat zones."""
    m = folium.Map(location=DELHI_CENTER, zoom_start=zoom, tiles="CartoDB positron")

    # Population heatmap
    pop_data = [[r["lat"], r["lon"], min(r["pop_density"] / 90000, 1.0)]
                for _, r in df.iterrows()]
    HeatMap(pop_data, name="Population Density", radius=13, blur=12,
            gradient={"0": "#E3F2FD", "0.5": "#1565C0", "1.0": "#0D47A1"}).add_to(m)

    # Hotspot markers on top
    if not hotspot_zones.empty:
        for _, zone in hotspot_zones.iterrows():
            color = SEVERITY_COLORS.get(str(zone.get("severity_label", "High")), "#FF9800")
            folium.CircleMarker(
                location=[float(zone["centroid_lat"]), float(zone["centroid_lon"])],
                radius=6,
                color="#FF0000",
                fill=True,
                fill_color=color,
                fill_opacity=0.8,
                tooltip=f"🔥 {zone.get('zone_name','')} — Pop: {int(zone.get('total_population',0)):,}",
            ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m


def _add_lst_legend(m: folium.Map, lst_min: float, lst_max: float) -> None:
    """Add a temperature colour legend to a Folium map."""
    legend_html = f"""
    <div style="position:fixed;bottom:50px;left:50px;z-index:1000;background:white;
                padding:10px 15px;border-radius:8px;border:1px solid #ccc;
                font-family:Arial;font-size:12px;">
    <b>Land Surface Temperature (°C)</b><br>
    <span style="background:#2196F3;padding:2px 10px;color:white;">&nbsp;</span> {lst_min:.0f}°C (Cool)<br>
    <span style="background:#4CAF50;padding:2px 10px;color:white;">&nbsp;</span> Moderate<br>
    <span style="background:#FFEB3B;padding:2px 6px;">&nbsp;</span> Warm<br>
    <span style="background:#FF9800;padding:2px 10px;color:white;">&nbsp;</span> Hot<br>
    <span style="background:#B71C1C;padding:2px 10px;color:white;">&nbsp;</span> {lst_max:.0f}°C (Extreme)
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))


# ---------------------------------------------------------------------------
# Plotly Charts
# ---------------------------------------------------------------------------

def plot_lst_distribution(df: pd.DataFrame) -> go.Figure:
    """Histogram of LST distribution with heat zone bands."""
    fig = px.histogram(
        df, x="LST", nbins=60, color="heat_zone",
        color_discrete_map=HEAT_ZONE_COLORS,
        category_orders={"heat_zone": ["Very Low", "Low", "Moderate", "High", "Extreme"]},
        labels={"LST": "Land Surface Temperature (°C)", "count": "Pixel Count"},
        title="Land Surface Temperature Distribution — Delhi",
    )
    fig.update_layout(
        bargap=0.05, plot_bgcolor="#0E1117", paper_bgcolor="#0E1117",
        font_color="white", legend_title="Heat Zone",
        xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"),
    )
    return fig


def plot_heat_zone_pie(zone_dist: pd.DataFrame) -> go.Figure:
    """Pie chart of heat zone area distribution."""
    fig = px.pie(
        zone_dist, names="heat_zone", values="pct",
        color="heat_zone", color_discrete_map=HEAT_ZONE_COLORS,
        title="Heat Zone Area Distribution (%)",
        hole=0.4,
    )
    fig.update_traces(textinfo="percent+label")
    fig.update_layout(paper_bgcolor="#0E1117", font_color="white",
                      legend_title="Heat Zone")
    return fig


def plot_land_use_lst(land_use_df: pd.DataFrame) -> go.Figure:
    """Horizontal bar chart: mean LST by land use type."""
    fig = px.bar(
        land_use_df.sort_values("mean_LST"),
        x="mean_LST", y="land_use",
        orientation="h",
        color="mean_LST",
        color_continuous_scale="RdYlBu_r",
        title="Mean LST by Land Use Type",
        labels={"mean_LST": "Mean LST (°C)", "land_use": "Land Use"},
        text="mean_LST",
    )
    fig.update_traces(texttemplate="%{text:.1f}°C", textposition="outside")
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", coloraxis_showscale=False,
                      xaxis=dict(gridcolor="#333"))
    return fig


def plot_ndvi_lst_scatter(df: pd.DataFrame, sample_n: int = 2000) -> go.Figure:
    """Scatter plot of NDVI vs LST coloured by heat zone."""
    sample = df.sample(min(sample_n, len(df)), random_state=42)
    _trendline = None
    try:
        import statsmodels  # noqa: F401
        _trendline = "ols"
    except ImportError:
        pass
    fig = px.scatter(
        sample, x="NDVI", y="LST", color="heat_zone",
        color_discrete_map=HEAT_ZONE_COLORS,
        category_orders={"heat_zone": ["Very Low", "Low", "Moderate", "High", "Extreme"]},
        opacity=0.5, size_max=4,
        title="NDVI vs LST — Inverse Relationship",
        labels={"NDVI": "NDVI (Vegetation Index)", "LST": "LST (°C)"},
        trendline=_trendline,
    )
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", xaxis=dict(gridcolor="#333"),
                      yaxis=dict(gridcolor="#333"))
    return fig


def plot_feature_importance(importance_dict: Dict, title: str = "Feature Importance") -> go.Figure:
    """Horizontal bar chart for ML feature importance."""
    feat_df = pd.DataFrame(
        list(importance_dict.items()), columns=["Feature", "Importance"]
    ).sort_values("Importance", ascending=True)

    FEATURE_LABELS = {
        "LST": "Land Surface Temp (°C)",
        "NDVI": "NDVI (Vegetation)",
        "NDBI": "NDBI (Built-up Index)",
        "NDWI": "NDWI (Water Index)",
        "pop_density": "Population Density",
        "dist_water": "Distance to Water",
        "elevation": "Elevation (m)",
        "imperv_fraction": "Imperviousness Fraction",
    }
    feat_df["Feature"] = feat_df["Feature"].map(FEATURE_LABELS).fillna(feat_df["Feature"])

    fig = px.bar(
        feat_df, x="Importance", y="Feature", orientation="h",
        color="Importance", color_continuous_scale="Viridis",
        title=title, text="Importance",
    )
    fig.update_traces(texttemplate="%{text:.3f}", textposition="outside")
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", coloraxis_showscale=False,
                      xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"))
    return fig


def plot_predicted_vs_actual(y_test: List, y_pred: List, r2: float) -> go.Figure:
    """Scatter plot of predicted vs actual heat stress index."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=y_test, y=y_pred, mode="markers",
        marker=dict(color="#FF6B35", size=4, opacity=0.5),
        name="Predictions",
    ))
    # Perfect prediction line
    min_val = min(min(y_test), min(y_pred))
    max_val = max(max(y_test), max(y_pred))
    fig.add_trace(go.Scatter(
        x=[min_val, max_val], y=[min_val, max_val],
        mode="lines", line=dict(color="#4CAF50", dash="dash", width=2),
        name="Perfect Fit",
    ))
    fig.update_layout(
        title=f"Predicted vs Actual Heat Stress Index (R² = {r2:.3f})",
        xaxis_title="Actual Heat Stress Index",
        yaxis_title="Predicted Heat Stress Index",
        paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
        font_color="white", xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"),
    )
    return fig


def plot_hotspot_ranking(hotspot_zones: pd.DataFrame, top_n: int = 10) -> go.Figure:
    """Bar chart ranking top hotspot zones by severity score."""
    df_plot = hotspot_zones.head(top_n).copy()
    df_plot["label"] = df_plot["rank"].astype(str) + ". " + df_plot["zone_name"].astype(str)

    fig = px.bar(
        df_plot.sort_values("mean_hotspot_score"),
        x="mean_hotspot_score", y="label", orientation="h",
        color="mean_LST", color_continuous_scale="RdYlBu_r",
        title=f"Top-{top_n} Hotspot Zones by Severity Score",
        labels={"mean_hotspot_score": "Severity Score", "label": "Zone", "mean_LST": "LST (°C)"},
        text="mean_LST",
    )
    fig.update_traces(texttemplate="%{text:.1f}°C", textposition="outside")
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", xaxis=dict(gridcolor="#333", range=[0, 1.05]),
                      coloraxis_colorbar=dict(title="LST (°C)"))
    return fig


def plot_recommendation_impact(recommendations: List[Dict]) -> go.Figure:
    """Bubble chart: Cost tier vs temperature reduction for interventions."""
    cost_map = {"Low": 1, "Medium": 2, "High": 3, "Very High": 4}
    rows = []
    for rec in recommendations:
        rows.append({
            "name": rec["name"],
            "temp_reduction": rec["temp_reduction_c"],
            "cost_score": cost_map.get(rec["cost_tier"], 2),
            "cost_tier": rec["cost_tier"],
            "population": rec.get("population_benefited", 100000),
            "priority": rec["priority_score"],
        })
    rdf = pd.DataFrame(rows)

    fig = px.scatter(
        rdf, x="cost_score", y="temp_reduction",
        size="population", color="priority",
        color_continuous_scale="RdYlGn",
        hover_name="name",
        title="Intervention Impact vs Cost (Bubble size = Population Benefited)",
        labels={
            "cost_score": "Cost Tier (1=Low, 4=Very High)",
            "temp_reduction": "Estimated LST Reduction (°C)",
            "priority": "Priority Score",
        },
        text="name",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", xaxis=dict(gridcolor="#333", tickvals=[1,2,3,4],
                      ticktext=["Low","Medium","High","Very High"]),
                      yaxis=dict(gridcolor="#333"))
    return fig


def plot_lst_boxplot_by_landuse(df: pd.DataFrame) -> go.Figure:
    """Box plot of LST distribution per land use category."""
    fig = px.box(
        df, x="land_use", y="LST", color="land_use",
        title="LST Distribution by Land Use Type",
        labels={"land_use": "Land Use", "LST": "Land Surface Temperature (°C)"},
        points="outliers",
    )
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                      font_color="white", showlegend=False,
                      xaxis=dict(gridcolor="#333"), yaxis=dict(gridcolor="#333"))
    return fig


def plot_correlation_heatmap(df: pd.DataFrame) -> go.Figure:
    """Correlation matrix heatmap for key features."""
    cols = ["LST", "NDVI", "NDBI", "NDWI", "pop_density", "elevation", "imperv_fraction"]
    cols = [c for c in cols if c in df.columns]
    corr = df[cols].corr().round(2)

    fig = px.imshow(
        corr, text_auto=True, aspect="auto",
        color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
        title="Feature Correlation Matrix",
    )
    fig.update_layout(paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font_color="white")
    return fig
