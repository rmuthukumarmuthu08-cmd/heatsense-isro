"""
recommender.py — Urban Cooling Recommendation Engine

Purpose:
    Given hotspot zone characteristics (LST, population, land use, severity),
    generate a ranked list of location-specific cooling interventions.

Algorithm:
    1. Rule-based trigger: match zone properties to applicable interventions.
    2. Impact scoring: estimate temperature reduction per intervention type.
    3. Priority ranking: score = (impact × population_weight) / cost_tier.
    4. Return top-5 recommendations with detailed action plans.

Inputs:  hotspot_zones DataFrame (from hotspot_detector), optional land-use context
Outputs: List[dict] — ranked cooling recommendations per zone
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intervention database — 15 cooling interventions
# ---------------------------------------------------------------------------
INTERVENTIONS = [
    {
        "id": "urban_trees",
        "name": "Urban Tree Plantation",
        "category": "Urban Greening",
        "emoji": "🌳",
        "description": (
            "Plant native shade trees (Neem, Peepal, Gulmohar) along streets, "
            "parks, and open spaces. Trees provide evapotranspiration cooling."
        ),
        "temp_reduction_c": 2.5,   # Estimated LST reduction in °C
        "cost_tier": "Low",        # Low / Medium / High / Very High
        "cost_inr_lakh": 5,        # Approximate cost in ₹ lakh per zone
        "implementation_months": 6,
        "land_use_targets": ["Residential", "Transportation", "Commercial"],
        "min_lst_trigger": 38.0,
        "population_multiplier": 1.2,
        "co_benefits": ["Air quality", "Carbon sequestration", "Mental health"],
        "sdg_goals": ["SDG 11", "SDG 13", "SDG 15"],
    },
    {
        "id": "cool_roofs",
        "name": "Cool Roof Installation",
        "category": "Cool Roofs",
        "emoji": "🏠",
        "description": (
            "Apply reflective white coatings or tiles on rooftops of residential "
            "and commercial buildings to reflect solar radiation."
        ),
        "temp_reduction_c": 1.8,
        "cost_tier": "Medium",
        "cost_inr_lakh": 12,
        "implementation_months": 3,
        "land_use_targets": ["Residential", "Commercial", "Industrial"],
        "min_lst_trigger": 40.0,
        "population_multiplier": 1.5,
        "co_benefits": ["Energy savings", "Indoor comfort", "Reduced AC load"],
        "sdg_goals": ["SDG 7", "SDG 11", "SDG 13"],
    },
    {
        "id": "water_features",
        "name": "Water Body Creation / Restoration",
        "category": "Water Features",
        "emoji": "💧",
        "description": (
            "Create or restore urban ponds, check dams, and decorative water "
            "features in parks and public spaces for evaporative cooling."
        ),
        "temp_reduction_c": 3.2,
        "cost_tier": "High",
        "cost_inr_lakh": 45,
        "implementation_months": 12,
        "land_use_targets": ["Green Space", "Residential"],
        "min_lst_trigger": 42.0,
        "population_multiplier": 1.0,
        "co_benefits": ["Groundwater recharge", "Biodiversity", "Aesthetics"],
        "sdg_goals": ["SDG 6", "SDG 11", "SDG 15"],
    },
    {
        "id": "shade_structures",
        "name": "Shade Structures & Bus Shelters",
        "category": "Shade Structures",
        "emoji": "⛱️",
        "description": (
            "Install solar-panel shade canopies over bus stops, pedestrian paths, "
            "markets, and public gathering areas."
        ),
        "temp_reduction_c": 1.4,
        "cost_tier": "Medium",
        "cost_inr_lakh": 8,
        "implementation_months": 2,
        "land_use_targets": ["Transportation", "Commercial", "Residential"],
        "min_lst_trigger": 39.0,
        "population_multiplier": 1.3,
        "co_benefits": ["Solar energy generation", "Pedestrian comfort"],
        "sdg_goals": ["SDG 7", "SDG 11"],
    },
    {
        "id": "reflective_pavement",
        "name": "Reflective / Permeable Paving",
        "category": "Reflective Pavements",
        "emoji": "🛣️",
        "description": (
            "Replace dark asphalt with light-coloured, permeable paving on roads "
            "and footpaths to reduce solar absorption and enable percolation."
        ),
        "temp_reduction_c": 1.6,
        "cost_tier": "High",
        "cost_inr_lakh": 30,
        "implementation_months": 8,
        "land_use_targets": ["Transportation", "Commercial"],
        "min_lst_trigger": 41.0,
        "population_multiplier": 1.1,
        "co_benefits": ["Flood reduction", "Groundwater recharge"],
        "sdg_goals": ["SDG 11", "SDG 13"],
    },
    {
        "id": "green_corridors",
        "name": "Green Corridor Development",
        "category": "Urban Greening",
        "emoji": "🌿",
        "description": (
            "Connect existing parks and green spaces with tree-lined corridors "
            "to create natural air-flow channels that flush hot air."
        ),
        "temp_reduction_c": 2.1,
        "cost_tier": "Medium",
        "cost_inr_lakh": 20,
        "implementation_months": 9,
        "land_use_targets": ["Residential", "Transportation"],
        "min_lst_trigger": 38.0,
        "population_multiplier": 1.2,
        "co_benefits": ["Biodiversity", "Air quality", "Recreation"],
        "sdg_goals": ["SDG 11", "SDG 13", "SDG 15"],
    },
    {
        "id": "rooftop_gardens",
        "name": "Rooftop & Vertical Gardens",
        "category": "Urban Greening",
        "emoji": "🪴",
        "description": (
            "Install green roofs and vertical garden walls on large buildings "
            "to insulate structures and cool surrounding air."
        ),
        "temp_reduction_c": 1.5,
        "cost_tier": "High",
        "cost_inr_lakh": 25,
        "implementation_months": 4,
        "land_use_targets": ["Commercial", "Industrial", "Residential"],
        "min_lst_trigger": 40.0,
        "population_multiplier": 1.0,
        "co_benefits": ["Stormwater management", "Food production", "Insulation"],
        "sdg_goals": ["SDG 2", "SDG 11", "SDG 13"],
    },
    {
        "id": "mist_cooling",
        "name": "Mist Cooling Systems",
        "category": "Water Features",
        "emoji": "🌫️",
        "description": (
            "Deploy high-pressure mist cooling systems at bus terminals, "
            "outdoor markets, and public plazas for immediate thermal relief."
        ),
        "temp_reduction_c": 4.0,
        "cost_tier": "Medium",
        "cost_inr_lakh": 15,
        "implementation_months": 1,
        "land_use_targets": ["Commercial", "Transportation"],
        "min_lst_trigger": 43.0,
        "population_multiplier": 2.0,
        "co_benefits": ["Immediate relief", "Low installation time"],
        "sdg_goals": ["SDG 3", "SDG 11"],
    },
    {
        "id": "heat_alert_system",
        "name": "Heat Alert & Early Warning System",
        "category": "Digital Infrastructure",
        "emoji": "📱",
        "description": (
            "Deploy SMS/app-based heat stress warnings to residents of extreme "
            "hotspot zones using satellite-derived LST data."
        ),
        "temp_reduction_c": 0.0,   # Indirect — saves lives rather than reducing LST
        "cost_tier": "Low",
        "cost_inr_lakh": 3,
        "implementation_months": 2,
        "land_use_targets": ["Residential", "Industrial", "Commercial"],
        "min_lst_trigger": 44.0,
        "population_multiplier": 3.0,   # High multiplier — reaches many people
        "co_benefits": ["Lives saved", "Emergency preparedness", "Low cost"],
        "sdg_goals": ["SDG 3", "SDG 11", "SDG 13"],
    },
    {
        "id": "industrial_greenbelt",
        "name": "Industrial Zone Green Buffer",
        "category": "Urban Greening",
        "emoji": "🏭",
        "description": (
            "Plant dense tree buffers around industrial areas to absorb "
            "radiant heat and pollutants before they reach residential zones."
        ),
        "temp_reduction_c": 3.0,
        "cost_tier": "Medium",
        "cost_inr_lakh": 18,
        "implementation_months": 8,
        "land_use_targets": ["Industrial"],
        "min_lst_trigger": 42.0,
        "population_multiplier": 1.4,
        "co_benefits": ["Air quality", "Pollution reduction", "Wildlife habitat"],
        "sdg_goals": ["SDG 3", "SDG 11", "SDG 13", "SDG 15"],
    },
    {
        "id": "cool_pavements_bike",
        "name": "Shaded Cycling & Walking Infrastructure",
        "category": "Shade Structures",
        "emoji": "🚲",
        "description": (
            "Build shaded cycling tracks and pedestrian paths to reduce "
            "heat exposure for non-motorised commuters."
        ),
        "temp_reduction_c": 1.2,
        "cost_tier": "Medium",
        "cost_inr_lakh": 22,
        "implementation_months": 6,
        "land_use_targets": ["Transportation", "Residential"],
        "min_lst_trigger": 37.0,
        "population_multiplier": 1.1,
        "co_benefits": ["Active transport", "Health", "CO2 reduction"],
        "sdg_goals": ["SDG 3", "SDG 11", "SDG 13"],
    },
    {
        "id": "community_cooling_centers",
        "name": "Community Cooling Centres",
        "category": "Social Infrastructure",
        "emoji": "🏥",
        "description": (
            "Convert schools, libraries, and community halls into air-conditioned "
            "cooling centres open 24×7 during peak heat events."
        ),
        "temp_reduction_c": 0.0,   # Indirect benefit
        "cost_tier": "Low",
        "cost_inr_lakh": 6,
        "implementation_months": 1,
        "land_use_targets": ["Residential", "Commercial"],
        "min_lst_trigger": 44.0,
        "population_multiplier": 2.5,
        "co_benefits": ["Immediate relief", "Social equity", "Community building"],
        "sdg_goals": ["SDG 3", "SDG 10", "SDG 11"],
    },
]


# ---------------------------------------------------------------------------
# Cost tier to score mapping (lower cost = higher feasibility score)
# ---------------------------------------------------------------------------
COST_TIER_SCORE = {"Low": 4, "Medium": 3, "High": 2, "Very High": 1}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_recommendations(
    hotspot_zones: pd.DataFrame,
    top_k: int = 5,
) -> List[Dict]:
    """
    Generate ranked cooling recommendations for the study area's hotspot zones.

    Parameters
    ----------
    hotspot_zones : DataFrame from hotspot_detector.identify_top_hotspots()
    top_k         : Number of top recommendations to return (default 5)

    Returns
    -------
    List[dict] — each dict is one recommendation with all details
    """
    if hotspot_zones.empty:
        logger.warning("No hotspot zones provided — returning default recommendations")
        return _default_recommendations(top_k)

    # Compute area-wide statistics for rule-based triggering
    mean_lst = float(hotspot_zones["mean_LST"].mean())
    max_lst = float(hotspot_zones["max_LST"].max())
    total_pop = int(hotspot_zones["total_population"].sum())
    dominant_severity = hotspot_zones["severity_label"].mode().iloc[0] if not hotspot_zones.empty else "High"

    logger.info(
        f"Generating recommendations: mean_LST={mean_lst:.1f}°C | "
        f"max_LST={max_lst:.1f}°C | total_pop={total_pop:,} | severity={dominant_severity}"
    )

    # Score each intervention
    scored = []
    for iv in INTERVENTIONS:
        if max_lst < iv["min_lst_trigger"]:
            continue  # Not triggered

        # Impact score (0-1): weighted temperature reduction
        temp_score = min(iv["temp_reduction_c"] / 5.0, 1.0)

        # Population score: log-normalised
        pop_score = min(np.log10(max(total_pop, 1)) / 6.0, 1.0) * iv["population_multiplier"]

        # Cost-effectiveness score
        cost_score = COST_TIER_SCORE.get(iv["cost_tier"], 1) / 4.0

        # Urgency multiplier based on severity
        urgency = {"Critical": 2.0, "Very High": 1.6, "High": 1.3, "Moderate": 1.0, "Low": 0.7}
        urgency_mult = urgency.get(str(dominant_severity), 1.0)

        # Final composite score
        final_score = (
            0.40 * temp_score
            + 0.30 * pop_score
            + 0.20 * cost_score
            + 0.10 * urgency_mult / 2.0
        )

        scored.append({
            **iv,
            "priority_score": round(final_score, 4),
            "estimated_lst_reduction": f"{iv['temp_reduction_c']:.1f}°C",
            "target_zones": min(len(hotspot_zones), 5),
            "population_benefited": int(total_pop * 0.6),
            "heat_illness_prevented": int(total_pop * 0.001 * iv["temp_reduction_c"]),
        })

    scored.sort(key=lambda x: x["priority_score"], reverse=True)
    results = scored[:top_k]

    logger.info(f"Generated {len(results)} recommendations")
    return results


def _default_recommendations(top_k: int) -> List[Dict]:
    """Return top-k default recommendations when no hotspot data is available."""
    defaults = sorted(INTERVENTIONS, key=lambda x: x["temp_reduction_c"], reverse=True)
    return [
        {**iv, "priority_score": 0.7, "estimated_lst_reduction": f"{iv['temp_reduction_c']:.1f}°C",
         "target_zones": 5, "population_benefited": 500000, "heat_illness_prevented": 1500}
        for iv in defaults[:top_k]
    ]


def format_recommendation_card(rec: Dict) -> str:
    """
    Format a recommendation as a human-readable markdown card string.
    Used in Streamlit dashboard st.markdown() calls.
    """
    lines = [
        f"### {rec['emoji']} {rec['name']}",
        f"**Category:** {rec['category']}",
        f"**Priority Score:** {rec['priority_score']:.2f} / 1.00",
        f"**Estimated LST Reduction:** {rec['estimated_lst_reduction']}",
        f"**Cost Tier:** {rec['cost_tier']} (₹{rec['cost_inr_lakh']} lakh / zone)",
        f"**Implementation Time:** {rec['implementation_months']} months",
        f"**Population Benefited:** {rec['population_benefited']:,}",
        f"**Estimated Heat Illnesses Prevented:** {rec['heat_illness_prevented']:,}",
        "",
        f"**Action:** {rec['description']}",
        "",
        f"**Co-Benefits:** {', '.join(rec['co_benefits'])}",
        f"**SDG Alignment:** {', '.join(rec['sdg_goals'])}",
    ]
    return "\n".join(lines)


def get_intervention_summary_df(recommendations: List[Dict]) -> pd.DataFrame:
    """
    Convert recommendation list to a clean DataFrame for display in Streamlit tables.
    """
    rows = []
    for i, rec in enumerate(recommendations, 1):
        rows.append({
            "Rank": i,
            "Intervention": f"{rec['emoji']} {rec['name']}",
            "Category": rec["category"],
            "LST Reduction": rec["estimated_lst_reduction"],
            "Cost Tier": rec["cost_tier"],
            "Time (months)": rec["implementation_months"],
            "Population Benefited": f"{rec['population_benefited']:,}",
            "Priority Score": f"{rec['priority_score']:.3f}",
        })
    return pd.DataFrame(rows)
