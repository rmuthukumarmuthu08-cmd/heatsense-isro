# Algorithm Documentation — HeatSense Urban Heat Stress Detection

**ISRO Bharatiya Antariksh Hackathon 2025**

---

## 1. Land Surface Temperature (LST) Calculation

### Purpose
Convert raw Landsat 8/9 Band 10 thermal radiance values to calibrated Land Surface Temperature in degrees Celsius at 30m spatial resolution.

### Algorithm: Single-Channel Radiative Transfer (Jimenez-Munoz & Sobrino, 2003)

**Step 1 — DN to Brightness Temperature**
```
L_lambda = M_L * Q_cal + A_L          (DN to Radiance)
BT = K2 / ln(K1/L_lambda + 1) - 273.15   (Radiance to Brightness Temp °C)
```
Constants for Landsat 9 Band 10: K1=774.8853, K2=1321.0789

**Step 2 — NDVI-based Emissivity**
```
NDVI = (NIR - Red) / (NIR + Red)
Pv = ((NDVI - NDVI_min) / (NDVI_max - NDVI_min))^2   (vegetation fraction)
epsilon = 0.004 * Pv + 0.986                          (emissivity)
```

**Step 3 — LST from Brightness Temperature**
```
LST = BT / (1 + (lambda * BT / rho) * ln(epsilon))
rho = h * c / k = 0.01438 m*K
lambda = 10.895e-6 m  (Band 10 centre wavelength)
```

### Input
- Landsat Band 10 (TIRS): raw DN values
- Landsat Band 4 (Red) and Band 5 (NIR): for NDVI/emissivity

### Output
- LST raster: floating-point array in degrees Celsius at 30m resolution

### Complexity
- O(N) where N = number of pixels in the scene (~50M for a full Landsat tile)

### Advantages
- Physically-based: accounts for atmospheric emissivity
- No external atmospheric data required (single-channel method)
- Works directly on Landsat Level-1 or Level-2 products

### Limitations
- Assumes clear-sky conditions (cloud masking required)
- Emissivity from NDVI is an approximation; ASTER-based emissivity more accurate for mixed pixels

---

## 2. Urban Heat Island (UHI) Index

### Purpose
Normalise LST values to a dimensionless z-score to enable comparison across dates, cities, and seasons.

### Algorithm
```
UHI_i = (LST_i - mean(LST)) / std(LST)
```

### Heat Zone Classification
| Zone | UHI Range | Interpretation |
|------|-----------|----------------|
| Very Low | < -1.5 | Significantly cooler than city average |
| Low | -1.5 to -0.5 | Slightly cooler than average |
| Moderate | -0.5 to 0.5 | Near city average temperature |
| High | 0.5 to 1.5 | Significantly hotter than average |
| Extreme | > 1.5 | Critical heat stress zone |

### Input
- LST array (float, degrees C)

### Output
- UHI index array (float, z-score)
- Heat zone label array (categorical, 5 classes)

### Complexity
- O(N): two-pass algorithm (mean then deviation)

### Advantages
- Date-invariant: removes seasonal bias
- City-invariant: works without external reference temperatures
- Directly interpretable as statistical significance

### Limitations
- Sensitive to outliers (very hot industrial pixels can inflate std)
- Does not account for elevation-corrected temperature lapse rate

---

## 3. Getis-Ord Gi* Spatial Hotspot Detection

### Purpose
Identify statistically significant spatial clusters of high LST — distinguishing genuine hotspots from random high-temperature pixels.

### Algorithm (Simplified Local Gi* Statistic)
For each point i, calculate:
```
Gi*(d) = (sum_j w_ij(d) * x_j - X_bar * sum_j w_ij(d)) / S * sqrt((n * sum_j w_ij^2 - (sum_j w_ij)^2) / (n-1))
```

Where:
- w_ij = 1 if point j is within radius d of point i, else 0
- x_j = LST value at point j
- X_bar = global mean LST
- S = global std of LST
- n = total number of points

**Classification:**
- Gi* z-score > 1.96 → statistically significant hotspot (p < 0.05)
- Gi* z-score < -1.96 → statistically significant coldspot
- |Gi* z-score| < 1.96 → not significant

### Input
- DataFrame with lat, lon, LST columns
- radius_deg: neighbourhood radius in decimal degrees (default 0.03, ~3 km)
- z_threshold: significance threshold (default 1.96)

### Output
- gi_z_score: Gi* statistic for each point
- is_hotspot: boolean flag
- is_coldspot: boolean flag

### Complexity
- O(N^2/chunk) with chunked vectorised computation (chunk=500)
- Memory: O(chunk * N) at any time

### Advantages
- Statistically rigorous: controls for random clustering
- Identifies clusters even when surrounded by moderate-heat areas
- No parameter tuning required (z-threshold from standard normal)

### Limitations
- Simplified implementation does not account for edge effects (border pixels have fewer neighbours)
- Assumes isotropy (neighbourhood is circular, not directional)
- Sensitive to radius choice — too small misses clusters, too large blurs them

---

## 4. Spatial Clustering (Pure-NumPy DBSCAN Replacement)

### Purpose
Group statistically significant hotspot pixels into contiguous spatial zones for reporting and prioritisation.

### Why Not sklearn DBSCAN?
On Windows systems with a full C: drive, loading sklearn triggers `scipy.stats._stats_pythran` DLL which fails when the pagefile cannot expand. This pure-numpy replacement avoids the entire scipy dependency chain.

### Algorithm: Grid-Based Clustering
```
Step 1: Bin each hotspot pixel into a grid cell of size eps_deg x eps_deg
         cell_key = round(lat / eps) * 1e6 + round(lon / eps)

Step 2: For each pixel, count Linf-norm neighbours within eps_deg
         count_i = sum_j ((|lat_i - lat_j| <= eps) AND (|lon_i - lon_j| <= eps))

Step 3: Pixels with count >= min_samples are "core" points
         Label core pixel with its grid cell ID; noise pixels get label -1

Step 4: Renumber cluster IDs 0, 1, 2, ...
```

### Parameters
- eps_deg: 0.03 degrees (~3 km at Delhi latitude)
- min_samples: 10 pixels per cluster

### Input
- DataFrame with lat, lon, is_hotspot columns

### Output
- cluster_id: integer label per pixel (-1 = noise, 0..N = cluster index)

### Complexity
- O(n_hotspot^2 / chunk) for neighbour counting (chunk=300)
- Memory: O(chunk * n_hotspot)

### Advantages
- Zero external dependencies beyond numpy
- Works on any Windows/Linux system regardless of pagefile size
- Deterministic: no random state needed

### Limitations
- Uses Linf (Chebyshev) distance, not haversine — minor error at large scales
- Grid cells may merge clusters that DBSCAN would separate
- No epsilon-neighbourhood expansion (connected components not merged across cell borders)

---

## 5. Composite Severity Score

### Purpose
Rank hotspot zones by a multi-factor risk score that combines temperature, population exposure, vegetation deficit, and urban density.

### Formula
```
severity_score = 0.40 * norm(LST)
               + 0.25 * norm(pop_density)
               + 0.15 * (1 - norm(NDVI))    # low NDVI = worse
               + 0.10 * norm(NDBI)
               + 0.10 * norm(imperv_fraction)
```
All features normalised to [0, 1] via min-max scaling. Weights sum to 1.0.

### Output
- hotspot_score: float [0, 1] for each pixel
- severity_label: Low / Moderate / High / Very High / Critical (per zone)

---

## 6. Random Forest Regressor (Heat Stress Prediction)

### Purpose
Predict continuous heat stress index (0–1) from 8 geospatial features, enabling prediction at unmeasured locations or under future scenarios.

### Architecture
- Estimators: 100 decision trees
- Max depth: 10 levels
- Min samples per leaf: 5 (prevents overfitting)
- n_jobs: 1 (Windows compatibility — avoids pagefile exhaustion from parallel workers)
- Train/Test split: 80%/20%, stratified by heat zone

### Features (8)
| Feature | Type | Description |
|---------|------|-------------|
| LST | Continuous | Land Surface Temperature (°C) |
| NDVI | Continuous | Vegetation index [-1, 1] |
| NDBI | Continuous | Built-up index [-1, 1] |
| NDWI | Continuous | Water index [-1, 1] |
| pop_density | Continuous | Population per km² |
| dist_water | Continuous | Distance to nearest water body (km) |
| elevation | Continuous | Elevation above sea level (m) |
| imperv_fraction | Continuous | Fraction of impervious surface [0, 1] |

### Training Results
- R² (test): 0.989
- RMSE (test): 0.0122
- MAE (test): 0.0089

### SHAP Explainability
TreeExplainer computes Shapley values for each feature, showing how much each variable contributes (positively or negatively) to each prediction. Mean absolute SHAP values are reported per feature for global importance ranking.

---

## 7. Gradient Boosting Classifier (Heat Zone Classification)

### Purpose
Classify each spatial point into one of 5 heat zone categories using sequential ensemble learning.

### Architecture
- Estimators: 80 boosting rounds
- Learning rate: 0.10 (shrinkage)
- Max depth: 4 per tree
- Target: 5-class (Very Low, Low, Moderate, High, Extreme)
- Label encoding: scikit-learn LabelEncoder

### Training Results
- Accuracy (test): 1.000
- Note: Perfect accuracy reflects clean structure of synthetic data; real-world accuracy expected 0.85-0.92

---

## 8. Cooling Recommendations Engine

### Purpose
Rank urban heat mitigation interventions by composite priority score for each identified hotspot zone.

### Priority Score Formula
```
priority = (
    0.35 * (temp_reduction / max_temp_reduction)   # cooling impact
  + 0.25 * (pop_benefited / max_pop_benefited)     # population coverage
  + 0.20 * (1 - cost_inr_lakh / max_cost)         # cost efficiency
  + 0.20 * (1 - implementation_months / 36)        # speed
)
```

### Intervention Categories
1. Green Infrastructure (urban trees, green roofs, parks)
2. Water Features (fountains, ponds, blue corridors)
3. Cool Surfaces (reflective roofs, permeable pavement)
4. Community Cooling (mist fans, cooling centres)
5. Urban Planning (zoning, shading, street design)

### Output
Ranked list of interventions with:
- Priority score (0-1)
- Estimated LST reduction (°C)
- Cost (INR lakhs)
- Implementation timeline (months)
- Population benefited
- Co-benefits (air quality, biodiversity, flood control)
