# 📖 Glossary: Definitions & Acronyms

> **Living Document** — Update whenever new terms, metrics, or concepts are introduced in the codebase or project planning.
>
> **Last Updated:** 2026-08-31

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

---

## 2. Capacity & Reliability Metrics

| Term / Acronym | Definition |
|----------------|------------|
| **CWFT (Capacity Worth Factor Table)** | An 8,760-hour profile of weights (summing to 1.0) that distributes annual generation capacity risk across hours of the year. High CWFT weights = hours when the grid is most likely to experience reliability stress. In the Southeast, concentrated on winter mornings and summer afternoons. |
| **EPC (Effective Peak Contribution)** | A single metric (in kW) quantifying how much a load resource contributes to system peak demand, weighted by reliability risk. Formula: `EPC = Σ(Hourly Load × CWFT)`. Drives 100% of generation capacity deferral value. |
| **ELCC (Effective Load Carrying Capability)** | The additional load a resource can reliably serve without degrading system reliability. In this tool, approximated as a proxy: `ELCC Proxy (%) = EPC / Peak Load`. Full ELCC requires probabilistic LOLP modeling. |
| **LOLP (Loss of Load Probability)** | The probability that the electric grid will be unable to meet demand during a given period. CWFT weights are ideally derived from LOLP distributions. Not directly calculated in the current tool. |
| **PCAF (Peak Capacity Allocation Factor)** | Distributes localized T&D deferral costs across the top grid stress hours. In the tool, the top 100 highest-priced hours receive equal weight (1/100 = 0.01 each). Sum = 1.0. |
| **Coincidence** | The degree to which a load resource's demand overlaps with grid peak/stress hours. High coincidence = the load draws heavily during the most expensive/risky hours. Measured in this tool as a **peak-to-average ratio**: average demand during the top N stress hours ÷ average demand across the full year. |
| **Peak-to-Average Ratio** | Average demand during a defined set of high-stress hours (e.g., top 50/100 CWFT hours, or top 100 highest-price hours) divided by average demand across the **full year**. A ratio of 2.0x means the load draws twice as much power during those hours as it does normally. Replaces the earlier "% of annual energy" framing, which was mathematically correct but unintuitive (it conflated concentration with the small time-window size). |

---

## 3. Cost-Effectiveness Tests

| Term / Acronym | Definition |
|----------------|------------|
| **RIM (Ratepayer Impact Measure)** | Cost-effectiveness test measuring impact on non-participating ratepayers. `RIM = NPV of Grid Avoided Costs / NPV of Retail Lost Revenue`. RIM ≥ 1.0 means grid savings exceed utility lost revenue, putting downward pressure on rates. ✅ *Implemented in tool.* |
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
| **ECR (Energy Cost Recovery)** | Alabama Power's equivalent of FCR — a per-kWh adjustment reflecting current fuel and purchased power costs. |
| **NDR (Natural Disaster Reserve)** | An Alabama Power rider ($1.08/month) funding reserves for storm restoration and natural disaster recovery. |

---

## 5. Data Sources & Datasets

| Term / Acronym | Definition |
|----------------|------------|
| **NREL (National Renewable Energy Laboratory)** | US DOE national lab that produces the Cambium dataset, Utility Rate Database, and various clean energy tools. |
| **Cambium** | NREL's modeled dataset of hourly grid characteristics (wholesale energy prices, carbon intensity, capacity values) across multiple future scenarios and geographies. The tool's primary grid data source. URL: [nrel.gov/analysis/cambium](https://www.nrel.gov/analysis/cambium.html) |
| **Cambium Scenario** | A long-term grid projection reflecting different assumptions about demand growth, policy, and technology costs. The tool supports: `HighDemandGrowth`, `MidCase`, `LowCarbonConstraint`, `LowDemandGrowth`. |
| **Planning Year** | The future year for which Cambium projects grid conditions (2025, 2030, 2035, 2040, 2045, 2050). |
| **`lmp_energy`** | Cambium column: wholesale marginal energy price at the busbar ($/MWh). |
| **`co2_combust`** | Cambium column: marginal CO₂ combustion emissions rate (kg CO₂/MWh). Represents the emissions from the marginal generating unit. |
| **`lrmer_co2_c`** | Cambium column: long-run marginal emission rate for CO₂ (combustion). An alternative, forward-looking emissions metric. |
| **ISD (Integrated Surface Database)** | NOAA's archive of surface weather observations used by `diyepw` to build EPW files. |
| **TMY3 (Typical Meteorological Year, version 3)** | NREL's statistical composite weather files representing "typical" conditions over a 15-30 year period. Used as templates by `diyepw`. |

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
