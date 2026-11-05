# 📖 Glossary: Definitions & Acronyms

> **Living Document** — Update whenever new terms, metrics, or concepts are introduced in the codebase or project planning.
>
> **Last Updated:** 2026-10-27

---

## Table of Contents

1. [Grid & Utility Economics](#1-grid--utility-economics)
2. [Capacity & Reliability Metrics](#2-capacity--reliability-metrics)
3. [Cost-Effectiveness Tests](#3-cost-effectiveness-tests)
4. [Retail Tariff & Billing](#4-retail-tariff--billing)
5. [Data Sources & Datasets](#5-data-sources--datasets)
6. [Weather & Building Simulation](#6-weather--building-simulation)
7. [Financial & Valuation](#7-financial--valuation)
8. [Software & Architecture](#8-software--architecture)
9. [Organizations & Programs](#9-organizations--programs)

---

## 1. Grid & Utility Economics

| Term / Acronym | Definition |
|----------------|------------|
| **Avoided Cost** | The cost a utility *would have incurred* to generate, transmit, and distribute electricity if a demand-side resource (e.g., efficient heat pump) had not reduced consumption. Comprised of energy, generation capacity, T&D, and emissions components. |
| **Marginal Cost** | The cost of producing or procuring one additional unit of electricity (typically $/MWh) at a given hour. Varies significantly by time of day, season, and grid conditions. |
| **LMP (Locational Marginal Price)** | The wholesale price of electricity at a specific node on the transmission grid, reflecting energy, congestion, and losses. Units: $/MWh. |
| **Wholesale Energy Price** | The hourly market price for bulk electricity generation, derived from Cambium projections. Represented as `Cambium_Energy_MWh` in the tool. |
| **Grid-Edge Technology** | Distributed energy resources sited at or near customer premises — heat pumps, battery storage, thermal storage, EVs, smart thermostats, rooftop solar, etc. |
| **Load Reduction** | The hourly difference in electricity demand (kW) between a baseline system and a proposed (more efficient) system. `Load Reduction = Baseline kW − Proposed kW`. |
| **Peak Demand** | The maximum electricity demand (kW) reached during a defined period (hour, day, month, season, or year). Drives capacity planning and infrastructure investment. |
| **Dual-Peaking System** | A grid region (like the Southeast US) where peak demand stress occurs in both **winter** (heating-driven morning peaks) and **summer** (cooling-driven afternoon peaks), unlike summer-only-peaking regions. |
| **T&D (Transmission & Distribution)** | The infrastructure (wires, transformers, substations) that moves electricity from generators to end users. T&D deferral value = avoided investment in upgrading this infrastructure. |
| **Demand Response (DR)** | A program where customers agree to reduce electricity consumption during grid stress events in exchange for incentive payments. The tool simulates DR by curtailing load during top CWFT hours. |
| **Cambium Milestone Trajectory** | Multi-year hourly grid valuation methodology where 8,760 profiles from distinct Cambium modeled milestone years (e.g., 2025, 2030, 2035, 2045) are ingested and interpolated across operating years, accurately reflecting non-linear peak price escalation and mid-day solar duck curve price suppression instead of assuming a flat scalar escalator (e.g. 2%/yr). |
| **Hourly Linear Interpolation** | Vectorized interpolation method calculating hourly prices for inter-milestone years $t$ between $Y_1$ and $Y_2$: $P_{h, t} = P_{h, Y_1} + \frac{t - Y_1}{Y_2 - Y_1}(P_{h, Y_2} - P_{h, Y_1})$. |

---

## 2. Capacity & Reliability Metrics

| Term / Acronym | Definition |
|----------------|------------|
| **CWFT (Capacity Worth Factor Table)** | An 8,760-hour profile of weights (summing to 1.0) that distributes annual generation capacity risk across hours of the year. High CWFT weights = hours when the grid is most likely to experience reliability stress. In the Southeast, concentrated on winter mornings and summer afternoons. |
| **ECC (Economic Carrying Cost)** | The annualized capital recovery and fixed O&M cost ($/kW-yr) of owning and maintaining the Next Planned Peaking Unit (SCCT / CT): `Carrying Cost = (CAPEX × FCR) + Fixed O&M`. Default benchmark uses NREL Annual Technology Baseline (ATB 2024) Natural Gas Combustion Turbine (Moderate scenario, Regulated Utility financing: CAPEX = $1,100/kW, FCR = 8.20%, FOM = $20.00/kW-yr -> ECC = $110.20/kW-yr). In Southeast utility IRPs, this establishes the benchmark avoided generation capacity scalar (Gross CONE). ✅ *Implemented in tool as default capacity valuation method.* |
| **Net CONE (Net Cost of New Entry)** | The net capacity payment required for a peaking unit to break even after subtracting profits earned selling wholesale energy or reserves: `Net CONE = Gross ECC − Net E&AS Offsets`. Prevents double-counting energy benefits in avoided cost models. ✅ *Implemented in tool.* |
| **FCR (Fixed Charge Rate)** | The levelized annual capital carrying cost rate (typically 7.5%–8.8%/yr for regulated utilities, ~9.5%–11.2% for merchant financing in NREL ATB, default 8.20%) accounting for utility WACC, economic life (20–30 years), corporate income tax rate, and MACRS tax depreciation shields. ✅ *Implemented in tool with direct input or synthesized WACC/MACRS calculation.* |
| **Southeast Dual-Peak CWF** | Default allocation methodology that divides annual generation capacity value across the Southeast's dual reliability peaks (default 80% winter morning cold snaps 6–9 AM Dec–Feb, 20% summer afternoon heat waves 2–6 PM Jun–Sep), weighted by ambient temperature severity and 3-day rolling thermal buildup/lag from aligned 8,760 EPW dry-bulb weather data. ✅ *Implemented in tool.* |
| **Feeder Distribution Deferral** | Localized distribution capacity valuation that decouples distribution from bulk transmission by allocating deferred circuit/substation investment across specific local feeder peak hours (e.g., winter space-heating cold snaps vs. summer cooling). ✅ *Implemented in tool.* |
| **Cambium Net-Demand Capacity Proxy** | Modeled physical net-demand capacity-credit screening proxy based on NREL Cambium modeled `net_load_busbar` (`busbar_load − variable_generation`). Aggregates physical load at the complete GEA reliability region level along a synchronous EST clock, applying Cambium's documented exceedance rule: `threshold = min(N_101, 0.95 * max(N))`, `excess = max(N − threshold, 0)`. Preserves 2012 weather basis and contiguous 48-state ReEDS hierarchy. ✅ *Implemented in tool.* |
| **GEA (Generation Expansion Area)** | NREL ReEDS regional capacity and reliability planning partition. Exactly 18 complete GEAs cover the 133 ReEDS balancing areas across the 48 contiguous United States. Shared GEAs are aggregated across constituent BAs before thresholding. |
| **N_101** | The 101st-highest hourly value among the 8,760 annual regional net load observations. In Cambium 2024 documentation, defines the exceedance threshold cutoff (`min(N_101, 0.95 * max(N))`) — strictly 95% of peak net load, not the 95th percentile. |
| **EPC (Effective Peak Contribution)** | A single metric (in kW) quantifying how much a load resource contributes to system peak demand, weighted by reliability risk. Formula: `EPC = Σ(Hourly Load × CWFT)`. Drives 100% of generation capacity deferral value. |
| **ELCC (Effective Load Carrying Capability)** | The additional load a resource can reliably serve without degrading system reliability, i.e. its accredited capacity as a share of nameplate. In this tool: `Capacity Accreditation (ELCC/UCAP %) = Accredited Capacity ÷ Nameplate` (nameplate = enrolled DR capacity, or peak measured reduction outside DR Mode), where Accredited Capacity = Technical EPC Reduction × Capacity Accreditation Factor (a DR performance/availability derate). Distinct from **Peak Coincidence Factor** (`EPC ÷ own peak`), which describes a load shape's peakiness but isn't a capacity-accreditation metric. Full ELCC requires probabilistic LOLP modeling. |
| **LOLP (Loss of Load Probability)** | The probability that the electric grid will be unable to meet demand during a given period. The tool implements an exponential LOLP *proxy* curve `exp(α · (P_h / P_peak - 1.0))` — the "Cambium Price-Exceedance LOLP Proxy" CWF method — driven by Cambium's own hourly wholesale energy price, not a measured LOLP curve or real EIA-930 demand data. Chosen over an external historical demand dataset because it automatically stays on the same weather-year basis as the rest of the tool's Cambium-derived inputs. ✅ *Implemented in tool (proxy only).* |
| **PCAF (Peak Capacity Allocation Factor)** | Distributes localized T&D deferral costs across the top grid stress hours. In the tool, the top 100 highest-priced hours receive equal weight (1/100 = 0.01 each). Sum = 1.0. |
| **Coincidence** | The degree to which a load resource's demand overlaps with grid peak/stress hours. High coincidence = the load draws heavily during the most expensive/risky hours. Measured in this tool as a **peak-to-average ratio**: average demand during the top N stress hours ÷ average demand across the full year. |
| **Peak-to-Average Ratio** | Average demand during a defined set of high-stress hours (e.g., top 50/100 CWFT hours, or top 100 highest-price hours) divided by average demand across the **full year**. A ratio of 2.0x means the load draws twice as much power during those hours as it does normally. Replaces the earlier "% of annual energy" framing, which was mathematically correct but unintuitive (it conflated concentration with the small time-window size). |
| **Public-Data System-Stress Capacity-Credit Proxy** | An empirical, public-data 8,760 capacity-weighting methodology (`system_stress_data.py` + `calculations.py`) that replaces prescribed seasonal clock-hour risk windows with observed upper-tail net-demand exceedance (`max(signal_h − Q_q, 0) / Σ exceedance`, default `q = 0.95`) derived from Form EIA-930 hourly Balancing Authority demand and wind/solar generation, aggregated to state portfolios via Form EIA-861 residential retail sales shares. Explicitly labeled as a screening proxy rather than measured LOLP or probabilistic ELCC. ✅ *Implemented in tool.* |
| **Upper-Tail Net Demand Exceedance** | Hourly system-stress signal `net_demand_MW[h] = reported_demand_MW[h] − reported_wind_MW[h] − reported_solar_MW[h]` (or whole-year `gross_demand_MW[h]` fallback when wind/solar are unavailable or fail quality gates) weighted above a configurable empirical quantile threshold (default 95th percentile, 90%–99% sensitivity). |
| **Proxy Coincidence / Stress-Weighted Capacity Credit** | When the public-data system-stress proxy is active, `Capacity Credit (kW) = Σ(w_h × (Baseline_kW_h − Proposed_kW_h))` and `Normalized Proxy Ratio (%) = Capacity Credit / max(Load_Reduction_h)` (computed only when peak reduction > 0; never applied as a second derate to capacity dollars). |
| **LFRR (Levelized Fixed Revenue Requirement)** | The standard regulatory ratemaking formulation used in Southeast utility IRPs (Southern Company, Duke Energy, TVA) to determine the annualized avoided cost of generation capacity: Gross ECC = (Installed CapEx * LFCR) + Fixed Non-Fuel O&M. Expressed in 2024$ real or nominal escalated delivery years. ✅ *Implemented in serc_capacity_cost.py.* |
| **SERC Regional Capacity Cost Engine** | Self-contained, citeable avoided capacity cost module (serc_capacity_cost.py) calculating Gross ECC ($/kW-year) across Southeast utilities (Southern Company $141.22/kW-yr, Duke Energy $130.35/kW-yr, TVA $115.12/kW-yr, SERC Composite $129.76/kW-yr in 2024$ real) and projecting nominal escalation (2.2% GDP deflator) from 2025 to 2050, with ambient winter turbine derate adjustments (1.15x). ✅ *Implemented in serc_capacity_cost.py.* |
| **Ambient Turbine Derate / Accreditation Ratio** | Ambient air density correction for combustion turbines: cold winter ambient air increases turbine mass flow and output by ~1.15x relative to summer ISO nameplate rating (1.00x). In winter-peaking reliability jurisdictions, 1 kW of winter load reduction provides 1.15x equivalent peaker nameplate capacity avoidance. ✅ *Implemented in serc_capacity_cost.py.* |
| **State-to-Utility Benchmark Mapping** | Automated regulatory default lookup (`get_state_capacity_benchmark` in `serc_capacity_cost.py` & `config.py`): single-utility states (GA -> Southern Company $141.22, TN -> TVA $115.12, NC -> Duke Energy $130.35) default directly to that operating company's commission-approved ECC; states with 2+ operating utilities (AL, SC, MS, FL, multi-state) default to SERC Composite ($129.76/kW-yr) and present an interactive UI prompt dropdown. ✅ *Implemented in app.py & serc_capacity_cost.py.* |
| **Annual Capacity Savings / (Cost)** | Generation capacity value accounting (`calculate_annual_capacity_savings()` in `calculations.py`). Evaluates $\text{Capacity Credit} = \text{Accredited kW} \times \text{Unit Capacity Cost ($/kW-yr)}$. Positive load reductions yield avoided capacity savings ($/yr); negative load reductions (e.g. electrification additions, heat pump winter cold snap spikes, EV charging, data centers) correctly yield annual capacity costs ($/yr). ✅ *Implemented in calculations.py.* |
| **Recalculate Benchmark Updater** | Automated background script (`refresh_capacity_benchmarks()` in `serc_capacity_cost.py`) triggered via CLI (`python serc_capacity_cost.py --refresh`) or one-click Streamlit button that re-evaluates public NLR ATB 2025 and Southeast IRP benchmarks, regenerates `data/serc_capacity_2025_2050.csv`, and refreshes in-memory calculations. ✅ *Implemented in app.py.* |

---

## 3. Cost-Effectiveness Tests

| Term / Acronym | Definition |
|----------------|------------|
| **RIM (Rate Impact Measure)** | Cost-effectiveness test measuring impact on non-participating ratepayers. `RIM = NPV of Grid Avoided Costs / (NPV of Retail Lost Revenue + Utility Program Costs)`. RIM ≥ 1.0 means avoided grid savings exceed lost revenue and program costs, putting downward pressure on customer rates (benefiting non-participants with no cross-subsidy). RIM < 1.0 means grid savings are less than lost revenue and program costs, putting upward pressure on customer rates (non-participating ratepayers cross-subsidize participants). ✅ *Implemented in tool.* |
| **TRC (Total Resource Cost)** | Cost-effectiveness test measuring net benefit to all parties combined (utility + participant). `TRC = NPV Avoided Grid Costs / (Gross Measure Cost + Utility Admin Cost)`. ✅ *Implemented* in `calculate_cost_effectiveness_tests()` (`calculations.py`), displayed via `ratio_card_html()` on the Overview Scorecard tab. |
| **UCT / PAC (Utility Cost Test / Program Administrator Cost)** | Measures cost-effectiveness from the utility's perspective only, excluding participant costs. Similar to RIM but treats bill savings differently. 🔴 *Not yet implemented.* |
| **PCT (Participant Cost Test)** | Measures whether the investment is worthwhile from the customer's perspective. `PCT = (NPV Customer Bill Savings + Incentive) / Gross Measure Cost`. ✅ *Implemented* in `calculate_cost_effectiveness_tests()` (`calculations.py`), displayed via `ratio_card_html()` on the Overview Scorecard tab. |
| **SCT (Societal Cost Test)** | Broadest test; includes externalities (carbon, health, resilience) at societal valuation levels. 🔴 *Not yet implemented.* |
| **Lost Revenue** | The reduction in retail electricity sales revenue that a utility experiences when a customer installs efficient equipment. Calculated as `Baseline Annual Bill − Proposed Annual Bill`. |
| **Non-Energy Benefits (NEBs)** | Economic benefits beyond energy savings — comfort, health, property value, resilience, reduced maintenance. Often included in TRC but difficult to quantify. |

---

## 4. Retail Tariff & Billing

| Term / Acronym | Definition |
|----------------|------------|
| **URDB (Utility Rate Database)** | NREL's publicly accessible database of utility retail tariff structures, maintained at OpenEI. Provides standardized JSON schemas for rate schedules. URL: [openei.org/wiki/Utility_Rate_Database](https://openei.org/wiki/Utility_Rate_Database) |
| **Tariff / Rate Schedule** | A utility's published pricing structure defining how customers are charged for electricity (fixed fees, energy charges, demand charges, time-of-use periods, tiered blocks). |
| **Fixed Charge** | A flat monthly fee ($/month) charged regardless of usage. Covers basic customer service infrastructure (meter reading, billing, connection). |
| **Volumetric / Energy Charge** | A charge per unit of energy consumed ($/kWh). May vary by season (summer/winter), time of day, or consumption tier. |
| **Demand Charge** | A charge based on the customer's peak demand ($/kW-month), typically the single highest kW draw in a billing period. Common for commercial rates; less common for residential. |
| **Tiered / Block Rate** | A rate structure where the $/kWh price changes after crossing usage thresholds (e.g., first 650 kWh at $0.148/kWh, next 350 kWh at $0.216/kWh). |
| **TOU (Time-of-Use)** | A rate structure where prices vary by time of day and season (e.g., on-peak, off-peak, shoulder). |
| **Rate Period** | A numbered index (0, 1, 2...) mapping hours of the year to a specific set of pricing rules. Period 0 = Winter, Period 1 = Summer in the pre-packaged GP/AL rates. |
| **Energy Rate Window** | A 12-month × 24-hour matrix mapping each hour of each month to its active rate period index. |
| **Rider / Adjustment** | A surcharge or credit applied on top of base tariff rates (e.g., fuel cost recovery rider, environmental compliance cost rider). Georgia Power's R-31 applies a 1.177209 rider multiplier. |
| **FCR (Fuel Cost Recovery)** | A variable rider on utility bills that passes through changes in the utility's fuel procurement costs to customers. |
| **ECR (Energy Cost Recovery)** | Alabama Power's equivalent of FCR — a per-kWh adjustment reflecting current fuel and purchased power costs (e.g. 2.600¢/kWh). |
| **NDR (Natural Disaster Reserve)** | An Alabama Power rider ($1.08/month) funding reserves for storm restoration and natural disaster recovery. |
| **Demand Ratchet** | A billing rule where monthly billing capacity cannot drop below a percentage (e.g., 90% in Rate FD-D) of the highest peak established during previous months (e.g., prior 11 months). |
| **Rate FD-D (Family Dwelling Demand)** | Alabama Power residential demand tariff featuring a flat energy rate ($0.105607/kWh with ECR), an $8.00/kW peak-period demand charge (summer 1–5 PM weekdays, winter 6–9 AM weekdays), and a 90% 11-month demand ratchet. |
| **Rate RTA (Residential Time Advantage - Demand)** | Alabama Power residential time-of-use tariff combining TOU energy rates (summer peak $0.282092/kWh, winter peak $0.152092/kWh, economy $0.132092/kWh) with a flat monthly peak demand charge ($1.50/kW). |
| **Rate RTA-E (Residential Time Advantage - Energy Only)** | Alabama Power residential energy-only TOU tariff with higher peak energy rates (summer peak $0.328554/kWh, winter peak $0.148554/kWh, economy $0.128554/kWh), a $25.00/mo base charge ($26.08 with NDR), and no demand charges. |

---

## 5. Data Sources & Datasets

| Term / Acronym | Definition |
|----------------|------------|
| **NREL (National Renewable Energy Laboratory)** | US DOE national lab that produces the Cambium dataset, Utility Rate Database, and various clean energy tools. |
| **Cambium** | NREL's modeled dataset of hourly grid characteristics (wholesale energy prices, carbon intensity, capacity values) across multiple future scenarios and geographies. The tool's primary grid data source. URL: [nrel.gov/analysis/cambium](https://www.nrel.gov/analysis/cambium.html) |
| **Cambium Scenario** | A long-term grid projection reflecting different assumptions about fuel prices, technology cost declines, demand growth, and decarbonization policy constraints. The tool supports the full Cambium suite: `MidCase` (reference baseline), `HighGasPrice` (elevated natural gas prices / AEO low oil & gas supply), `LowGasPrice` (cheap natural gas / AEO high oil & gas supply), `HighDemandGrowth` (rapid electrification/computing expansion), `LowDemandGrowth` (slower adoption/aggressive energy efficiency), `LowRECost` (ATB Advanced renewables/storage), `HighRECost` (ATB Conservative renewables/storage), `LowRECost_HighGasPrice` (combined high-divergence clean buildout), `HighRECost_LowGasPrice` (combined fossil-prolonging boundary), `LowCarbonConstraint` (95% CO₂ cut by 2050 / `MidCase95by2050`), `Decarb95by2035` (95% CO₂ cut by 2035), and `Decarb100by2035` (100% clean power / net-zero by 2035). |
| **Planning Year** | The future year for which Cambium projects grid conditions (2025, 2030, 2035, 2040, 2045, 2050). |
| **`lmp_energy`** | Cambium column: wholesale marginal energy price at the busbar ($/MWh). |
| **`co2_combust`** | Cambium column: marginal CO₂ combustion emissions rate (kg CO₂/MWh). Represents the emissions from the marginal generating unit. |
| **`lrmer_co2_c`** | Cambium column: long-run marginal emission rate for CO₂ (combustion). An alternative, forward-looking emissions metric. |
| **ISD (Integrated Surface Database)** | NOAA's archive of surface weather observations used by `diyepw` to build EPW files. |
| **TMY3 (Typical Meteorological Year, version 3)** | NREL's statistical composite weather files representing "typical" conditions over a 15-30 year period. Used as templates by `diyepw`. |
| **Form EIA-930 (Hourly Electric Grid Monitor)** | U.S. Energy Information Administration survey collecting hourly integrated system demand (`D`), net generation, interchange, and (since July 1, 2018) generation by fuel source (`WND`, `SUN`, etc.) across contiguous U.S. Balancing Authorities, reported with UTC hour-ending timestamps. Used by `system_stress_data.py` via API v2 (`electricity/rto/region-data` and `electricity/rto/fuel-type-data`) and six-month bulk CSV files. |
| **Form EIA-861 (`Sales_Ult_Cust`)** | U.S. EIA annual survey reporting utility and power-marketer retail electricity sales by state, sector, and Balancing Authority. Used to construct the verified 2016–2024 residential-sales-weighted state-to-BA crosswalk (`data/state_ba_sales_crosswalk.csv`), reconciling bundled + delivery sales (`Part A + B + D == Part A + C + D`) without double-counting marketers. |
| **ReEDS Balancing Area (`p1..p134`) vs. EIA Balancing Authority (`SOCO`, `TVA`, `PJM`, ...)** | Separate geographic namespaces that must never be conflated: NREL ReEDS/Cambium model regions (`p1..p134`, mapped to all 48 contiguous states via `data/reeds_state_ba_hierarchy.csv`) govern modeled future wholesale energy/carbon trajectories, whereas EIA-930 respondent Balancing Authority codes govern historical observed system-stress capacity weights. |

---

## 6. Weather & Building Simulation

| Term / Acronym | Definition |
|----------------|------------|
| **8760** | The number of hours in a non-leap year (24 × 365). The standard time resolution for energy analysis. All hourly data arrays in this tool are 8,760 elements long. |
| **EPW (EnergyPlus Weather)** | A standardized weather file format used by EnergyPlus and other building simulation tools. Contains hourly dry-bulb temperature, humidity, solar radiation, wind, and other variables. |
| **AMY (Actual Meteorological Year)** | A weather file based on observed conditions for a specific historical year (e.g., 2012), as opposed to a TMY statistical composite. Critical for matching load simulations to grid data from the same year. |
| **Dry-Bulb Temperature** | The standard air temperature measured by a thermometer, not adjusted for humidity or radiation. The primary driver of heating/cooling load. Column index 6 in EPW files (in °C). |
| **EnergyPlus (E+)** | DOE's flagship building energy simulation engine. Generates the hourly load profiles (kW) that the tool uses as input. |
| **`diyepw`** | PNNL's Python package for generating AMY EPW files from NOAA ISD observations. Integrated into the tool's weather generator tab. |
| **WMO Station ID** | A 6-digit numeric code identifying a weather station in the World Meteorological Organization's global catalog (e.g., 722300 = Birmingham, AL; 722190 = Atlanta, GA). |
| **Weather Year Alignment** | The critical requirement that load profiles, CWFT, and Cambium data all represent or are calibrated to the same historical weather year (typically 2012 for Cambium). Misalignment distorts peak coincidence calculations. |
| **Cold Snap** | An extreme winter weather event with temperatures well below normal, driving high heating demand. The tool simulates cold snaps in "Extreme Winter" mode by depressing temperatures and spiking energy prices. |

---

## 7. Financial & Valuation

| Term / Acronym | Definition |
|----------------|------------|
| **NPV (Net Present Value)** | The sum of future cash flows discounted to today's dollars using a discount rate. `NPV = Σ [Cash Flow_t / (1 + r)^t]`. Positive NPV = the investment creates value. |
| **WACC (Weighted Average Cost of Capital)** | The blended rate of return a company must earn on its investments, reflecting the cost of both debt and equity financing. Used as the discount rate in NPV calculations. Default: 7%. |
| **Discount Rate** | The rate used to convert future dollars into present value. Higher rates reduce the present value of distant future benefits. In the tool, synonymous with WACC. |
| **Escalation Rate** | The assumed annual growth rate of electricity prices. Grid escalation (wholesale) and retail escalation are specified separately. |
| **Degradation Rate** | The assumed annual decline in equipment performance (e.g., a heat pump losing 1%/year in efficiency due to wear). Reduces savings in later years. |
| **Discount Factor** | The multiplier applied to a future cash flow to express it in present value. `DF_t = 1 / (1 + r)^t`. |
| **Payback Period** | The time required for cumulative savings to equal the initial investment cost. Simple payback ignores time value of money; discounted payback accounts for it. ✅ *Implemented* — both Simple and Discounted Payback Period (years) are calculated in `calculate_cost_effectiveness_tests()` (`calculations.py`) and shown on the Overview Scorecard tab. |
| **Asset Lifetime** | The assumed operating life of the technology being evaluated (default: 15 years). Determines the NPV analysis horizon. |
| **Levelized Cost** | A per-unit cost metric that spreads total lifecycle costs over total lifetime output. Not currently calculated but commonly used in utility planning. |

---

| **Fisher Equation** | Exact relationship relating nominal discount rate ($r_{nom}$), real discount rate ($r_{real}$), and inflation ($i$): $(1 + r_{nom}) = (1 + r_{real}) \times (1 + i)$. Used to convert utility nominal WACC to an equivalent real discount rate. |
| **Real vs Nominal Valuation** | Two mathematically equivalent frameworks for evaluating multi-year project cash flows: real valuation discounts constant-dollar cash flows at the real discount rate, while nominal valuation discounts inflated dollars at the nominal discount rate. Under consistent conversion, both yield identical NPVs down to numerical precision. |
| **Base Dollar Year** | The price dollar basis in which wholesale costs are published. NREL Cambium 2024 reports all values in constant 2023 dollars ($2023$). In financially consistent valuation, 2023$ values are escalated to project start-year dollars (e.g. 2026$) using the inflation factor $(1 + i)^{start\_year - 2023}$. |
| **Mid-Year Continuous Discounting** | Discounting convention where cash flows occurring continuously throughout the 8,760 hours of operating year $t$ arrive at mid-year ($t - 0.5$) rather than being deferred to December 31 ($t$), applying discount factor $1 / (1 + r)^{t - 0.5}$. |
| **NPV Waterfall Bridge** | A deterministic, step-by-step sequential attribution waterfall explaining the change in project NPV from a reference baseline to methodological improvements and forecast sensitivities, ensuring reconciliation with exactly zero residual. |
| **Physical Credited kW** | The accredited capacity contribution of an energy efficiency or demand flexibility measure during peak stress hours: winter morning credited kW, summer afternoon credited kW, and blended generation/transmission/distribution credited kW. Kept strictly distinct from financial multipliers. |
| **Non-Cambium Escalation Scenarios** | Macroeconomic and regulatory sensitivity suites (Base Growth, High Escalation, Low Growth, Custom) applied to cost streams outside Cambium hourly wholesale energy (Generation Capacity ECC, T&D Deferral, CO₂ Carbon Penalty, Retail Rates). |
| **Incremental Escalation Adder (\Delta r)** | Real annual growth rate applied multiplicatively on top of a component\'s underlying time-dependent baseline: {effective}(t) = V_{baseline}(t) \times (1 + \Delta r)^{t - t_0}$. Preserves empirical IRP trajectories and standard escalators while modeling policy and supply-chain sensitivities. |
| **Capacity ECC Adder** | Annual growth increment on the Next Planned Peaking Unit levelized carrying cost (Base: +0.0%, High: +1.5% [Handy-Whitman Construction Index / NREL ATB High CapEx], Low: -1.0% [technological learning]). |
| **T&D Deferral Adder** | Annual growth increment on deferred wires/substation replacement value (Base: +0.0%, High: +1.8% [Wood Mackenzie / LBNL transformer shortage premium], Low: -1.0%). |
| **Carbon Penalty Adder** | Annual growth increment on the social cost of carbon / compliance tax (Base: +0.0%, High: +2.5% [EPA SC-GHG 2023 technical report damage escalation], Low: -1.5% [regulatory freeze]). |
| **Retail Rate Adder** | Annual growth increment on retail tariff billing rates (Base: +0.0%, High: +1.5% [EIA AEO High Macro rate base addition], Low: -1.0% [Low Macro / Low Fuel]). |

---

## 8. Software & Architecture

| Term / Acronym | Definition |
|----------------|------------|
| **Streamlit** | An open-source Python framework that turns Python scripts into interactive web applications. All UI elements in the tool (sidebar controls, tabs, charts, metrics) are Streamlit components. |
| **Plotly** | An interactive charting library used for all visualizations in the tool (stacked area charts, bar charts, scatter plots with dual Y-axes). |
| **Pandas / DataFrame** | Python data analysis library. A DataFrame is a tabular data structure (like an Excel spreadsheet in code) with labeled rows and columns. All 8,760-hour datasets are stored as DataFrames. |
| **NumPy** | Python numerical computing library for high-speed array math. Used for vectorized operations on 8,760-element arrays. |
| **`@st.cache_data`** | A Streamlit decorator that memoizes (caches) function output. If the same inputs are provided again, the cached result is returned instantly instead of recomputing. Applied to data loading and avoided cost calculations. |
| **Session State (`st.session_state`)** | Streamlit's mechanism for persisting data across user interactions (button clicks, widget changes). Used to store simulation results and saved scenario runs. |
| **CSV (Comma-Separated Values)** | The primary file format for all data inputs and exports in the tool (load profiles, CWFT, Cambium grid data, top hours export). |
| **JSON (JavaScript Object Notation)** | A structured text format used for URDB tariff definitions and API responses. |

---

## 9. Organizations & Programs

| Term / Acronym | Definition |
|----------------|------------|
| **NREL** | National Renewable Energy Laboratory (Golden, CO). Produces Cambium, URDB, EnergyPlus weather data, and many clean energy analysis tools. |
| **PNNL** | Pacific Northwest National Laboratory. Develops `diyepw` for weather file generation. |
| **DOE** | U.S. Department of Energy. Funds national labs and energy research programs. |
| **EPRI** | Electric Power Research Institute. Industry-funded R&D organization serving electric utilities. Potential future home for the tool (per Phase 2 plan). |
| **NOAA** | National Oceanic and Atmospheric Administration. Maintains the ISD weather observation archive used by `diyepw`. |
| **OpenEI** | Open Energy Information — NREL's open data platform hosting the URDB and other energy datasets. |
| **ISO / RTO** | Independent System Operator / Regional Transmission Organization. Entities that manage wholesale electricity markets and grid reliability (e.g., PJM, MISO, ERCOT). The Southeast US is largely vertically integrated and not in a traditional ISO/RTO market. |
| **IRP (Integrated Resource Plan)** | A utility's long-term plan for meeting future electricity demand, filed with state regulators. Contains capacity values, resource mix decisions, and avoided cost assumptions. The tool's valuation parameters should ideally align with the relevant utility's IRP. |
| **NERC (North American Electric Reliability Corporation)** | Sets and enforces reliability standards for the North American grid. Publishes the Long-Term Reliability Assessment (LTRA) with regional capacity adequacy data. |

---

*Add new terms here as they are introduced in the codebase, documentation, or project discussions. Keep entries alphabetized within each section.*
