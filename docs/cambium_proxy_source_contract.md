# Cambium Net-Demand Capacity Proxy: Source Contract & Capability Matrix

**Status:** Phase 1 Verified & Frozen  
**Date:** 2026-10-27  
**Scope:** Contiguous 48 United States, Cambium 2024 & 2023 releases  

---

## 1. Mathematical & Algorithmic Contract

### 1.1 Documented Net-Load Exceedance Rule (Cambium Documentation S1)
For each complete GEA region and modeled year, let \( N[h] \) be the regional busbar net load synchronized to a common Eastern Standard Time (EST) clock:
\[
N[h] = \sum_{r \in \text{GEA}} \text{net\_load\_busbar}_{r}[h]
\]

1. **Sort 8,760 values descending:** Let \( N_{(1)} \ge N_{(2)} \ge \dots \ge N_{(8760)} \).
2. **101st-ranked hour value:** \( N_{101} = N_{(101)} \) (0-indexed: index 100).
3. **Threshold calculation:**
   \[
   \text{threshold} = \min\left(N_{101}, 0.95 \cdot \max(N)\right)
   \]
   *(Note: 95% of peak, NOT 95th percentile).*
4. **Exceedance:**
   \[
   \text{excess}[h] = \max\left(N[h] - \text{threshold}, 0\right)
   \]
5. **Normalization:**
   \[
   W_{\text{GEA}}[h] = \frac{\text{excess}[h]}{\sum_{j=1}^{8760} \text{excess}[j]}
   \]
   - All weights are finite, nonnegative (\( W[h] \ge 0 \)), and sum to 1.0.
   - If \(\sum \text{excess} \le 0\) or signal is constant/invalid, reject with explicit error.

6. **Diagnostics Exported:**
   - `peak_net_load`: \(\max(N)\)
   - `n_101`: 101st-ranked net load value
   - `threshold`: Exceedance cutoff
   - `active_hours`: \(\sum \mathbf{1}(W[h] > 0)\)
   - `top_hour_weight`: \(\max(W)\)
   - `effective_hours`: \( 1 / \sum W[h]^2 \)
   - `seasonal_distribution`: Monthly / seasonal shares of total weight

---

## 2. Chronological & Time Zone Alignment Contract

### 2.1 Provider Timestamp Conventions
- **`timestamp`**: Eastern Standard Time (EST, UTC-5), hour-beginning (`2030-01-01 00:00:00` or `01:00:00`).
- **`timestamp_local`**: Local standard time, hour-beginning (`2030-01-01 00:00:00`).
- **`Start_day`**: Sunday.
- **Calendar**: Synthetic no-leap 365-day year (8,760 hours). Leap day (Feb 29) omitted from labels.
- **Weather year**: 2012 meteorological basis.

### 2.2 ReEDS BA Local-to-EST Alignment
Each constituent ReEDS BA file has local standard time spanning hours `0..8759`.
To sum BAs across different time zones into a synchronous GEA total:
- **ET (UTC-5):** `h_EST = h_local`
- **CT (UTC-6):** `h_EST = (h_local + 1) % 8760`
- **MT (UTC-7):** `h_EST = (h_local + 2) % 8760`
- **PT (UTC-8):** `h_EST = (h_local + 3) % 8760`

### 2.3 EST Weights to Building Local Time Alignment
The building profile is recorded in local standard time:
\[
W_{\text{building}}[h_{\text{local}}] = W_{\text{EST}}[(h_{\text{local}} - \Delta_{\text{tz}}) \pmod{8760}]
\]
where \( \Delta_{\text{tz}} \) is the local time zone offset relative to EST (ET: 0, CT: -1, MT: -2, PT: -3).

---

## 3. Geographic Hierarchy & Multi-GEA State Allocation

### 3.1 GEA Partition
The contiguous 48 states contain 133 ReEDS balancing areas (`p1..p134`, with `p119` and `p122` in PA aggregated to `z122`).
These map partition-cleanly into **18 GEAs**:
1. `SERTP` (11 BAs: AL, GA, MS, FL, TN, SC, NC, KY)
2. `ERCOT` (7 BAs: TX)
3. `CAISO` (3 BAs: CA)
4. `NYISO` (2 BAs: NY)
5. `ISONE` (6 BAs: CT, MA, ME, VT, RI, NH)
6. `PJM_East` (19 BAs: VA, KY, OH, PA, NJ, DE, WV, MD, z122)
7. `PJM_West` (2 BAs: MI, IL)
8. `MISO_Central` (12 BAs: IN, KY, MI, MO, IL)
9. `MISO_North` (15 BAs: MN, ND, WI, IA, MI)
10. `MISO_South` (5 BAs: LA, TX, MS, AR)
11. `SPP_North` (6 BAs: NE, MT, ND, SD)
12. `SPP_South` (11 BAs: NM, OK, TX, MO, AR, KS)
13. `FRCC` (2 BAs: FL)
14. `NorthernGrid_West` (7 BAs: WA, OR)
15. `NorthernGrid_South` (5 BAs: NV, UT, CA)
16. `NorthernGrid_East` (9 BAs: MT, ID, WY)
17. `WestConnect_North` (5 BAs: WY, SD, CO)
18. `WestConnect_South` (6 BAs: AZ, NM, TX)

### 3.2 State Allocation Formula
For states entirely within 1 GEA (e.g. GA in SERTP):
\[
W_{\text{state}} = W_{\text{GEA}}
\]
For states spanning multiple GEAs (e.g. TX, KY, FL, MI, CA):
\[
\text{share}(\text{state}, \text{GEA}) = \frac{\sum_{r \in \text{state} \cap \text{GEA}} \text{annual enduse load}_{r}}{\sum_{r \in \text{state}} \text{annual enduse load}_{r}}
\]
\[
W_{\text{state}}[h] = \sum_{\text{GEA}} \text{share}(\text{state}, \text{GEA}) \cdot W_{\text{GEA}}[h]
\]

---

## 4. Release Capability Matrix

| Release | Scenarios Tested | Weather Year | Net Load Field | Status |
|---|---|---|---|---|
| **Cambium 2024** | MidCase, HighDemandGrowth, LowDemandGrowth | 2012 | `net_load_busbar` (exact `busbar_load - variable_generation`) | **Fully Supported** |
| **Cambium 2023** | LowCarbonConstraint (Decarb95by2050) | 2012 | `net_load_busbar` (exact `busbar_load - variable_generation`) | **Fully Supported** |
| **Cambium 2022** | Pre-2023 packages | Varies | Incompatible timestamp/storage structures | **Excluded / Weather Fallback** |

---

## 5. Offline Verification Fixtures Created

1. `data/cambium24_reeds_gea_manifest.json`: Full 133-BA to 18-GEA manifest verified from live package.
2. `tests/fixtures/cambium_stress/al_test_fixture_8760.csv`: 8,760-hour AL public Cambium load and exceedance weights.
3. `tests/fixtures/cambium_stress/al_test_summary.json`: Diagnostic ground truths:
   - Peak: `19,769.40 MWh`
   - N_101: `17,303.80 MWh`
   - Threshold: `17,303.80 MWh`
   - Active hours: `100`
   - Top hour weight: `3.1411%`
   - Effective hours: `61.64`
