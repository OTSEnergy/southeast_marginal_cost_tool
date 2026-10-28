"""
calculations.py — Grid Avoided Cost Calculation Engine
=======================================================

This module contains the core hourly avoided cost and demand response
calculations that form the backbone of the Southeast Marginal Cost
Valuation Engine.

WHAT IT DOES:
    Takes an 8,760-hour DataFrame of grid data (wholesale energy prices,
    carbon emission rates, and peak-hour weighting factors) and computes
    five components of avoided cost for each hour:

        1. Wholesale Energy Value    — from Cambium marginal energy prices
        2. Generation Capacity Value — weighted by CWFT (capacity risk hours)
        3. Transmission Value        — weighted by PCAF (top-100 price hours)
        4. Distribution Value        — weighted by PCAF (same as transmission)
        5. Emissions Value           — carbon price × emission rate

    The sum of all five = Total Avoided Cost per MWh, for each hour.

WHY IT'S SEPARATE:
    This function is pure math — no UI, no file I/O, no Streamlit.
    Keeping it in its own module means:
    • It can be tested independently (see tests/test_calculations.py)
    • It can be imported by other tools or scripts without Streamlit
    • Changes to the UI don't risk breaking the calculation logic

USED BY:
    app.py imports and calls calculate_avoided_costs() after the user
    configures their inputs in the sidebar. The result DataFrame then
    feeds into the dashboard tabs, NPV calculations, and visualizations.

TESTED BY:
    tests/test_calculations.py::TestCalculateAvoidedCosts (7 tests)
    tests/test_calculations.py::TestDispatchDrProgram
"""

import numpy as np
import pandas as pd
from typing import Tuple, Dict, Any, Optional, List


def calculate_avoided_costs(df, cap_value, trans_value, dist_value, carbon_tax, cwft_array, dist_weight_array=None):
    """
    Compute hourly avoided costs for an 8,760-hour grid dataset.

    Parameters
    ----------
    df : pd.DataFrame
        Must contain columns: 'Cambium_Energy_MWh', 'Cambium_Carbon_kg_MWh',
        'PCAF_Weight'. Typically produced by load_and_aggregate_data() in app.py.
    cap_value : float
        Generation capacity value in $/kW-year.
    trans_value : float
        Transmission capacity value in $/kW-year.
    dist_value : float
        Distribution capacity value in $/kW-year.
    carbon_tax : float
        Carbon price in $/metric ton CO₂.
    cwft_array : np.ndarray
        8,760-element array of Capacity Weighting Factor Table values.
        Must sum to 1.0. Each element represents that hour's share of
        annual capacity risk.
    dist_weight_array : np.ndarray, optional
        8,760-element array of localized distribution peak weighting factors
        (e.g., from feeder analysis). If None, defaults to df['PCAF_Weight'].

    Returns
    -------
    pd.DataFrame
        Copy of input with additional columns:
        - CWFT: the capacity weights applied
        - Gen_Capacity_Value_MWh: cap_value × CWFT × 1000
        - Trans_Value_MWh: trans_value × PCAF_Weight × 1000
        - Dist_Value_MWh: dist_value × Dist_Weight × 1000
        - Emissions_Value_MWh: (carbon_kg / 1000) × carbon_tax
        - Total_Avoided_Cost_MWh: sum of energy + all four components
    """
    regional_base = df.copy()
    regional_base['CWFT'] = cwft_array

    # --- Component 1: Generation Capacity (CWFT-weighted) ---
    # Spreads annual $/kW-yr value across hours proportional to capacity risk.
    # Multiply by 1000 to convert $/kW to $/MW (since energy prices are in $/MWh).
    regional_base['Gen_Capacity_Value_MWh'] = cap_value * regional_base['CWFT'] * 1000

    # --- Component 2 & 3: Transmission & Distribution (PCAF / Feeder weighted) ---
    # Transmission uses bulk system PCAF (top 100 highest-price/stress hours).
    regional_base['Trans_Value_MWh'] = trans_value * regional_base['PCAF_Weight'] * 1000

    # Distribution can use localized feeder weights (e.g. winter morning or summer afternoon)
    # or fallback to bulk PCAF if not explicitly specified.
    dist_weights = regional_base['PCAF_Weight'] if dist_weight_array is None else dist_weight_array
    regional_base['Dist_Value_MWh'] = dist_value * dist_weights * 1000

    # --- Component 4: Emissions ---
    # Carbon rate is in kg CO₂/MWh; carbon tax is in $/metric ton.
    # Divide kg by 1000 to get metric tons, then multiply by $/ton.
    regional_base['Emissions_Value_MWh'] = (regional_base['Cambium_Carbon_kg_MWh'] / 1000.0) * carbon_tax

    # --- Total: all five components summed ---
    regional_base['Total_Avoided_Cost_MWh'] = (
        regional_base['Cambium_Energy_MWh'] +
        regional_base['Gen_Capacity_Value_MWh'] +
        regional_base['Trans_Value_MWh'] +
        regional_base['Dist_Value_MWh'] +
        regional_base['Emissions_Value_MWh']
    )
    return regional_base


def dispatch_dr_program(datetime_series, cwft_array, dr_hours_per_year,
                        season_name, max_hours_per_day, dr_capacity_kw,
                        baseline_load):
    """
    Dispatch a demand response (DR) program by selecting the highest-value
    hours for load curtailment, subject to seasonal and daily call limits.

    Selects hours greedily from highest CWFT weight to lowest within the
    eligible season, enforcing a maximum number of calls per day.

    Parameters
    ----------
    datetime_series : pd.Series
        8,760-element datetime series.
    cwft_array : np.ndarray
        8,760-element CWFT weights (higher = more grid stress).
    dr_hours_per_year : int
        Maximum total DR call hours per year.
    season_name : str
        One of "Summer Only (Jun-Sep)", "Winter Only (Oct-May)", or
        "Both Seasons".
    max_hours_per_day : int
        Maximum DR call hours allowed in a single day.
    dr_capacity_kw : float
        Maximum curtailment capacity (kW) per hour.
    baseline_load : np.ndarray
        8,760-element baseline load profile (kW). DR reduction is capped
        at the actual load in each hour.

    Returns
    -------
    dr_reduction : np.ndarray
        8,760-element array of demand reduction (kW) during dispatched hours.
    selected_hours : list of int
        Indices of the hours selected for DR dispatch.
    """
    months = datetime_series.dt.month
    eligible_mask = np.ones(8760, dtype=bool)

    if season_name == "Summer Only (Jun-Sep)":
        eligible_mask = np.isin(months, [6, 7, 8, 9])
    elif season_name == "Winter Only (Oct-May)":
        eligible_mask = np.isin(months, [10, 11, 12, 1, 2, 3, 4, 5])

    eligible_indices = np.where(eligible_mask)[0]
    sorted_eligible = eligible_indices[np.argsort(-cwft_array[eligible_indices])]

    selected_hours = []
    daily_counts = {}
    dates = datetime_series.dt.date.to_numpy()

    for idx in sorted_eligible:
        date = dates[idx]
        count = daily_counts.get(date, 0)
        if count < max_hours_per_day:
            selected_hours.append(idx)
            daily_counts[date] = count + 1
            if len(selected_hours) >= dr_hours_per_year:
                break

    dr_reduction = np.zeros(8760)
    for idx in selected_hours:
        dr_reduction[idx] = min(dr_capacity_kw, baseline_load[idx])
    return dr_reduction, selected_hours


def _safe_cost_effectiveness_ratio(benefit, cost):
    """
    benefit / cost, guarding two different edge cases:
    - cost == 0 (e.g. a user zeroes out Gross Measure Cost while testing): a
      real benefit against no cost is infinitely favorable and should read
      that way, not as a misleadingly bad-looking 0.0; no benefit and no
      cost nets to a neutral 0.0.
    - cost < 0: a genuinely degenerate case (e.g. a RIM test where the
      customer's bill goes up enough that "lost revenue" is actually
      negative and outweighs the program cost, or a TRC/PCT cost input that
      somehow nets negative). Dividing by a negative cost would silently
      flip the ratio's sign -- a negative benefit over a negative cost would
      read as a *positive*, seemingly-favorable ratio, which is exactly
      backwards. Returns NaN instead, since the test's benefit/cost premise
      doesn't hold here; the caller should display this distinctly from
      both a real ratio and the cost==0 infinite/neutral cases.
    """
    if cost > 0:
        return benefit / cost
    if cost == 0:
        return float('inf') if benefit > 0 else 0.0
    return float('nan')


def calculate_cost_effectiveness_tests(npv_grid_savings, npv_lost_revenue,
                                        npv_customer_bill_savings, gross_measure_cost,
                                        utility_incentive, utility_admin_cost,
                                        annual_customer_savings_stream, pv_multipliers):
    """
    Compute standard California Standard Practice Manual (SPM) cost-effectiveness
    test ratios (TRC, PCT, RIM) and customer payback periods.

    Parameters
    ----------
    npv_grid_savings : float
        Lifetime present value of wholesale grid avoided costs ($).
    npv_lost_revenue : float
        Lifetime present value of utility lost retail revenue ($).
    npv_customer_bill_savings : float
        Lifetime present value of customer retail bill reductions ($).
    gross_measure_cost : float
        Total upfront equipment & installation cost ($).
    utility_incentive : float
        Utility rebate / incentive paid to customer ($).
    utility_admin_cost : float
        Utility program administration & marketing cost ($).
    annual_customer_savings_stream : np.ndarray
        Year-by-year nominal customer bill savings stream ($).
    pv_multipliers : np.ndarray
        Discount factors for each operating year.

    Returns
    -------
    dict
        Dictionary containing TRC, PCT, RIM ratios, net present values,
        and simple & discounted payback periods.
    """
    net_customer_cost = max(0.0, gross_measure_cost - utility_incentive)
    total_program_cost = utility_incentive + utility_admin_cost

    # 1. Total Resource Cost (TRC) Test
    trc_costs = gross_measure_cost + utility_admin_cost
    trc_ratio = _safe_cost_effectiveness_ratio(npv_grid_savings, trc_costs)
    trc_npv = npv_grid_savings - trc_costs

    # 2. Participant Cost Test (PCT) / Customer ROI
    pct_benefits = npv_customer_bill_savings + utility_incentive
    pct_costs = gross_measure_cost
    pct_ratio = _safe_cost_effectiveness_ratio(pct_benefits, pct_costs)
    pct_npv = pct_benefits - pct_costs

    # 3. Rate Impact Measure (RIM) Test (includes program costs)
    rim_costs = npv_lost_revenue + total_program_cost
    rim_ratio = _safe_cost_effectiveness_ratio(npv_grid_savings, rim_costs)
    rim_npv = npv_grid_savings - rim_costs

    # 4. Simple Payback Period (Years)
    year1_savings = annual_customer_savings_stream[0] if len(annual_customer_savings_stream) > 0 else 0.0
    if net_customer_cost <= 0:
        simple_payback = 0.0
    elif year1_savings > 0:
        simple_payback = net_customer_cost / year1_savings
    else:
        simple_payback = float('inf')

    # 5. Discounted Payback Period (Years)
    discounted_savings_stream = annual_customer_savings_stream * pv_multipliers
    cum_discounted = np.cumsum(discounted_savings_stream)
    
    if net_customer_cost <= 0:
        discounted_payback = 0.0
    else:
        payback_yr = np.where(cum_discounted >= net_customer_cost)[0]
        if len(payback_yr) > 0:
            yr_idx = payback_yr[0]
            prev_cum = cum_discounted[yr_idx - 1] if yr_idx > 0 else 0.0
            curr_disc = discounted_savings_stream[yr_idx]
            fraction = (net_customer_cost - prev_cum) / curr_disc if curr_disc > 0 else 0.0
            discounted_payback = (yr_idx) + fraction  # 1-based year count
        else:
            discounted_payback = float('inf')

    return {
        "net_customer_cost": net_customer_cost,
        "trc_ratio": trc_ratio,
        "trc_npv": trc_npv,
        "pct_ratio": pct_ratio,
        "pct_npv": pct_npv,
        "rim_ratio": rim_ratio,
        "rim_npv": rim_npv,
        "simple_payback": simple_payback,
        "discounted_payback": discounted_payback,
    }


# ==============================================================================
# SOUTHEAST UTILITY PEAKER CARRYING COST & REGULATED FCR
# ==============================================================================

def calculate_regulated_fcr(wacc=0.071, economic_life=30, tax_rate=0.25, macrs_life=15):
    """
    Compute the annual Fixed Charge Rate (FCR) for a utility-scale asset
    under regulated cost-of-service ratemaking.

    Parameters
    ----------
    wacc : float
        Weighted average cost of capital as a decimal (e.g. 0.071 for 7.1%).
    economic_life : int
        Asset book depreciation lifetime in years (default 30 for peakers).
    tax_rate : float
        Combined federal and state corporate income tax rate as a decimal (default 0.25).
    macrs_life : int
        MACRS tax depreciation schedule (15 or 20 years, default 15).

    Returns
    -------
    float
        Fixed charge rate as a decimal (e.g. ~0.084 for 8.4%/yr).
    """
    d = float(wacc)
    n = int(economic_life)
    tau = float(tax_rate)

    # Capital Recovery Factor (CRF)
    if d <= 0:
        crf = 1.0 / n if n > 0 else 0.0
    else:
        crf = d / (1.0 - (1.0 + d) ** (-n))

    # MACRS depreciation schedules (IRS half-year convention)
    if macrs_life == 20:
        rates = [
            0.03750, 0.07219, 0.06677, 0.06177, 0.05713, 0.05285, 0.04888, 0.04522,
            0.04462, 0.04461, 0.04462, 0.04461, 0.04462, 0.04461, 0.04462, 0.04461,
            0.04462, 0.04461, 0.04462, 0.04461, 0.02231
        ]
    else:  # 15-year standard for combustion turbines
        rates = [
            0.0500, 0.0950, 0.0855, 0.0770, 0.0693, 0.0623, 0.0590, 0.0590,
            0.0591, 0.0590, 0.0591, 0.0590, 0.0591, 0.0590, 0.0591, 0.0295
        ]

    # Present value of tax depreciation deductions discounted at WACC
    pv_dep = sum(r / ((1.0 + d) ** t) for t, r in enumerate(rates, start=1))

    # Tax shield factor
    if tau >= 1.0:
        tax_factor = 1.0
    else:
        tax_factor = (1.0 - tau * pv_dep) / (1.0 - tau)

    fcr = crf * tax_factor
    return fcr


def calculate_ct_carrying_cost(capex_kw, fom_kw_yr, fcr, eas_offset_kw_yr=0.0):
    """
    Calculate the annual Gross Economic Carrying Cost (ECC) and Net Avoided Capacity
    cost for the Next Planned Combustion Turbine (CT / SCCT) using the NLR Annual
    Technology Baseline (ATB) standard annualized carrying cost formulation:

        Carrying Cost ($/kW-yr) = (CAPEX * FCR) + Fixed O&M

    Under resource planning and marginal cost models (e.g. Gross CONE benchmark):
    - CAPEX: Overnight capital expenditure ($/kW)
    - FCR: Fixed Charge Rate (accounting for WACC, depreciation, income tax, and project life)
    - FOM: Fixed Operations and Maintenance ($/kW-yr)
    - Capital Recovery Annuity = CAPEX * FCR
    - Gross Carrying Cost = Capital Recovery + FOM
    - Net Avoided Capacity = max(0, Gross Carrying Cost - E&AS Offset)

    Default NLR ATB 2024 Moderate Benchmark (Regulated Utility Finance):
    - CAPEX: $1,100 / kW
    - FCR: 8.2% (0.082)
    - FOM: $20.00 / kW-yr
    - Capital Recovery: $1,100 * 0.082 = $90.20 / kW-yr
    - Total Carrying Cost: $90.20 + $20.00 = $110.20 / kW-yr
    Source: NLR ATB (atb.nlr.gov) > Electricity > Fossil Energy Technologies > Natural Gas: CT.

    Parameters
    ----------
    capex_kw : float
        Overnight capital cost in $/kW.
    fom_kw_yr : float
        Fixed O&M in $/kW-yr.
    fcr : float
        Fixed charge rate as a decimal (e.g. 0.082 for 8.2%/yr).
    eas_offset_kw_yr : float, optional
        Net energy & ancillary service revenue offset ($/kW-yr). Default 0.0
        (often 0 in Southeast cost-of-service IRPs where energy is dispatched separately).

    Returns
    -------
    dict
        capital_recovery_annuity, fom_kw_yr, gross_carrying_cost, eas_offset_kw_yr, net_capacity_cost
    """
    cap_recovery = float(capex_kw) * float(fcr)
    gross = cap_recovery + float(fom_kw_yr)
    net = max(0.0, gross - float(eas_offset_kw_yr))
    return {
        "capital_recovery_annuity": cap_recovery,
        "fom_kw_yr": float(fom_kw_yr),
        "gross_carrying_cost": gross,
        "eas_offset_kw_yr": float(eas_offset_kw_yr),
        "net_capacity_cost": net
    }


# ==============================================================================
# CAPACITY WORTH FACTOR (CWF) ALLOCATION METHODS
# ==============================================================================

def calculate_southeast_dual_peak_cwf(datetime_series=None, winter_weight=0.8, summer_weight=0.2,
                                      temperature_array=None, freeze_threshold_f=32.0, heat_threshold_f=90.0,
                                      lag_days=3, lag_weight=0.30,
                                      load_array=None, n_hours=8760):
    """
    Generate an 8,760-hour Capacity Worth Factor (CWF) array allocating annual
    capacity risk across Southeast dual-peak stress windows:
      - Winter Morning Freeze: 6:00 AM – 9:00 AM, Dec 1 – Feb 28/29
      - Summer Afternoon Heat: 2:00 PM – 6:00 PM, Jun 1 – Sep 30

    When `temperature_array` is provided (preferred), capacity risk within each window
    is allocated based on ambient temperature severity and multi-day thermal buildup/lag:
      - Trailing rolling mean temperature over `lag_days` (default 3 days / 72 hours):
        T_eff = (1 - lag_weight) * T_h + lag_weight * T_3d_rolling
      - Winter severity: max(0, freeze_threshold_f - T_eff)
      - Summer severity: max(0, T_eff - heat_threshold_f)
    If no hours exceed the threshold or `temperature_array` is None, weights within each
    window fall back to uniform distribution (or exceedance if legacy `load_array` is provided).

    Parameters
    ----------
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps. If None, assumes standard non-leap year starting Jan 1 00:00.
    winter_weight : float
        Fraction of annual capacity value assigned to winter morning peaks (default 0.80).
    summer_weight : float
        Fraction of annual capacity value assigned to summer afternoon peaks (default 0.20).
    temperature_array : np.ndarray, optional
        8,760 hourly dry-bulb temperatures in degrees Fahrenheit. When provided,
        risk within each window is weighted by effective temperature severity.
    freeze_threshold_f : float
        Winter temperature threshold below which heating capacity risk accrues (default 32.0°F).
    heat_threshold_f : float
        Summer temperature threshold above which cooling capacity risk accrues (default 90.0°F).
    lag_days : int
        Number of preceding days over which to calculate rolling average temperature
        to capture multi-day thermal inertia / cold penetration (default 3 days).
    lag_weight : float
        Weight assigned to the multi-day rolling average temperature vs. instantaneous
        hour temperature in T_eff (default 0.30, i.e. 70% current hour + 30% 3-day memory).
    load_array : np.ndarray, optional
        Hourly system or building load array (legacy/feeder fallback if temperature_array is None).
    n_hours : int
        Number of hours (default 8760).

    Returns
    -------
    np.ndarray
        Array of shape (n_hours,) summing to 1.0.
    """
    if datetime_series is not None:
        dts = pd.to_datetime(datetime_series)
        months = dts.dt.month.to_numpy()
        hours = dts.dt.hour.to_numpy()
    else:
        # Standard 8,760-hour non-leap year mapping
        h_idx = np.arange(n_hours)
        days = h_idx // 24
        hours = h_idx % 24
        # Days in each month for standard year
        month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        cum_days = np.cumsum([0] + month_days)
        months = np.zeros(n_hours, dtype=int)
        for m in range(12):
            months[(days >= cum_days[m]) & (days < cum_days[m+1])] = m + 1

    # Southeast Winter Window: Dec, Jan, Feb; hours 6, 7, 8 (6:00 to 9:00 AM)
    is_winter = np.isin(months, [12, 1, 2]) & np.isin(hours, [6, 7, 8])

    # Southeast Summer Window: Jun, Jul, Aug, Sep; hours 14, 15, 16, 17 (2:00 to 6:00 PM)
    is_summer = np.isin(months, [6, 7, 8, 9]) & np.isin(hours, [14, 15, 16, 17])

    cwf = np.zeros(n_hours, dtype=float)

    # Normalize weights so winter_weight + summer_weight = 1.0
    tot_weight = winter_weight + summer_weight
    if tot_weight > 0:
        norm_winter = winter_weight / tot_weight
        norm_summer = summer_weight / tot_weight
    else:
        norm_winter, norm_summer = 0.8, 0.2

    # Compute effective thermal stress temperature (Method A: 3-day thermal buildup/lag)
    if temperature_array is not None:
        temps = np.asarray(temperature_array, dtype=float)
        if len(temps) != n_hours:
            temps = np.resize(temps, n_hours)
        if lag_days > 0 and lag_weight > 0.0:
            win = int(lag_days * 24)
            rolling_mean = pd.Series(temps).rolling(window=win, min_periods=1).mean().to_numpy()
            eff_temps = (1.0 - lag_weight) * temps + lag_weight * rolling_mean
        else:
            eff_temps = temps
    else:
        eff_temps = None

    # 1. Allocate winter weights
    if is_winter.sum() > 0 and norm_winter > 0:
        if eff_temps is not None:
            w_temps = eff_temps[is_winter]
            w_severity = np.maximum(0.0, freeze_threshold_f - w_temps)
            s_w = w_severity.sum()
            if s_w > 0:
                cwf[is_winter] = (w_severity / s_w) * norm_winter
            else:
                cwf[is_winter] = norm_winter / is_winter.sum()
        elif load_array is not None and len(load_array) == n_hours:
            w_loads = load_array[is_winter]
            threshold = np.percentile(w_loads, 80)
            exceed = np.maximum(0.0, w_loads - threshold)
            if exceed.sum() > 0:
                cwf[is_winter] = (exceed / exceed.sum()) * norm_winter
            else:
                cwf[is_winter] = norm_winter / is_winter.sum()
        else:
            cwf[is_winter] = norm_winter / is_winter.sum()

    # 2. Allocate summer weights
    if is_summer.sum() > 0 and norm_summer > 0:
        if eff_temps is not None:
            s_temps = eff_temps[is_summer]
            s_severity = np.maximum(0.0, s_temps - heat_threshold_f)
            s_s = s_severity.sum()
            if s_s > 0:
                cwf[is_summer] = (s_severity / s_s) * norm_summer
            else:
                cwf[is_summer] = norm_summer / is_summer.sum()
        elif load_array is not None and len(load_array) == n_hours:
            s_loads = load_array[is_summer]
            threshold = np.percentile(s_loads, 80)
            exceed = np.maximum(0.0, s_loads - threshold)
            if exceed.sum() > 0:
                cwf[is_summer] = (exceed / exceed.sum()) * norm_summer
            else:
                cwf[is_summer] = norm_summer / is_summer.sum()
        else:
            cwf[is_summer] = norm_summer / is_summer.sum()

    # Safety: ensure exact sum to 1.0
    s = cwf.sum()
    if s > 0:
        cwf /= s
    else:
        cwf = np.ones(n_hours) / n_hours

    return cwf


def calculate_cwf_temperature_exceedance(temperature_array, datetime_series=None,
                                         freeze_threshold_f=32.0, heat_threshold_f=90.0,
                                         winter_weight=0.5, summer_weight=0.5,
                                         n_hours=8760):
    """
    Generate an 8,760-hour Capacity Worth Factor (CWF) array directly from ambient
    dry-bulb temperature severity within Southeast utility reliability windows (Option A):
      - Winter Morning Freeze: 6:00 AM – 9:00 AM, Dec 1 – Feb 28/29
        Severity_h = max(0, freeze_threshold_f - Temperature_F)
      - Summer Afternoon Heat: 2:00 PM – 6:00 PM, Jun 1 – Sep 30
        Severity_h = max(0, Temperature_F - heat_threshold_f)

    Parameters
    ----------
    temperature_array : np.ndarray
        8,760 hourly dry-bulb temperatures in degrees Fahrenheit.
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps for month/hour alignment. If None, assumes standard non-leap year.
    freeze_threshold_f : float
        Winter temperature threshold below which heating capacity risk accrues (default 32.0°F).
    heat_threshold_f : float
        Summer temperature threshold above which cooling capacity risk accrues (default 90.0°F).
    winter_weight : float
        Fraction of annual capacity value assigned to winter morning freeze hours (default 0.50).
    summer_weight : float
        Fraction of annual capacity value assigned to summer afternoon heat hours (default 0.50).
    n_hours : int
        Number of hours (default 8760).

    Returns
    -------
    np.ndarray
        Array of shape (n_hours,) summing to 1.0.
    """
    temps = np.asarray(temperature_array, dtype=float)
    if len(temps) != n_hours:
        temps = np.resize(temps, n_hours)

    if datetime_series is not None:
        dts = pd.to_datetime(datetime_series)
        months = dts.dt.month.to_numpy()
        hours = dts.dt.hour.to_numpy()
    else:
        h_idx = np.arange(n_hours)
        days = h_idx // 24
        hours = h_idx % 24
        month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        cum_days = np.cumsum([0] + month_days)
        months = np.zeros(n_hours, dtype=int)
        for m in range(12):
            months[(days >= cum_days[m]) & (days < cum_days[m+1])] = m + 1

    # Southeast Winter Window: Dec, Jan, Feb; hours 6, 7, 8 (6:00 to 9:00 AM)
    is_winter = np.isin(months, [12, 1, 2]) & np.isin(hours, [6, 7, 8])

    # Southeast Summer Window: Jun, Jul, Aug, Sep; hours 14, 15, 16, 17 (2:00 to 6:00 PM)
    is_summer = np.isin(months, [6, 7, 8, 9]) & np.isin(hours, [14, 15, 16, 17])

    cwf = np.zeros(n_hours, dtype=float)

    tot_weight = winter_weight + summer_weight
    if tot_weight > 0:
        norm_winter = winter_weight / tot_weight
        norm_summer = summer_weight / tot_weight
    else:
        norm_winter, norm_summer = 0.5, 0.5

    # 1. Allocate winter weights
    if is_winter.sum() > 0 and norm_winter > 0:
        w_temps = temps[is_winter]
        w_severity = np.maximum(0.0, freeze_threshold_f - w_temps)
        s_w = w_severity.sum()
        if s_w > 0:
            cwf[is_winter] = (w_severity / s_w) * norm_winter
        else:
            cwf[is_winter] = norm_winter / is_winter.sum()

    # 2. Allocate summer weights
    if is_summer.sum() > 0 and norm_summer > 0:
        s_temps = temps[is_summer]
        s_severity = np.maximum(0.0, s_temps - heat_threshold_f)
        s_s = s_severity.sum()
        if s_s > 0:
            cwf[is_summer] = (s_severity / s_s) * norm_summer
        else:
            cwf[is_summer] = norm_summer / is_summer.sum()

    # Safety: ensure exact sum to 1.0
    total = cwf.sum()
    if total > 0:
        cwf /= total
    else:
        cwf = np.ones(n_hours) / n_hours

    return cwf


def calculate_cwf_lolp_proxy(signal_array, alpha=4.0):
    """
    Calculate an 8,760-hour Capacity Worth Factor using an exponential
    Loss-of-Load Probability (LOLP) risk proxy on an hourly stress signal.

    Formula:
        risk_h = exp(alpha * (signal_h / peak_signal - 1.0))
        CWF_h = risk_h / sum(risk)

    This is a generic exceedance-curve function: it concentrates risk into
    the hours where the input signal is closest to its own annual peak,
    regardless of what that signal physically represents.

    USED BY app.py's "Cambium Price-Exceedance LOLP Proxy" CWF method, which
    passes Cambium's own hourly wholesale energy price (`Cambium_Energy_MWh`)
    as signal_array -- NOT real-world EIA-930 system demand. Price is a proxy
    for capacity scarcity (it should spike in tight-reserve-margin hours) but
    conflates other drivers too (fuel cost spikes, transmission congestion,
    renewable curtailment), and Cambium's hourly shape is a single deterministic
    weather year's dispatch simulation, not a stochastic reliability study.
    Treat this as a directional heuristic, not a measured LOLP curve. Its one
    real advantage over an external historical demand dataset (e.g. EIA-930)
    is that it automatically inherits the same weather-year basis as the rest
    of this tool's Cambium-derived inputs, so it can't drift out of alignment
    the way a separately-sourced historical-year dataset would.

    Parameters
    ----------
    signal_array : np.ndarray
        8,760-hour stress signal (e.g. Cambium hourly wholesale energy price,
        or real system/net demand if one is available on the same weather-year
        basis as the rest of the analysis).
    alpha : float
        Risk concentration parameter (default 4.0). Higher alpha concentrates
        more risk exclusively into the highest-signal hours -- alpha=12, an
        earlier default, put 40-58% of a year's entire capacity credit onto a
        single hour for real Southeast Cambium data; alpha=4 keeps the top
        hour's share under 1%, spread across thousands of hours instead.

    Returns
    -------
    np.ndarray
        8,760 array summing to 1.0.
    """
    arr = np.asarray(signal_array, dtype=float)
    peak = np.max(arr)
    if peak <= 0:
        return np.ones(len(arr)) / len(arr)

    norm_signal = arr / peak
    # Subtract 1.0 inside exp to prevent numeric overflow
    risk = np.exp(alpha * (norm_signal - 1.0))
    s = np.sum(risk)
    if s > 0:
        return risk / s
    return np.ones(len(arr)) / len(arr)


def calculate_cwf_top_n(demand_array, top_n=100, weighting_method="exceedance"):
    """
    Calculate an 8,760 CWF allocating 100% of capacity value across the top N
    highest peak hours (either uniformly or weighted by exceedance).

    Parameters
    ----------
    demand_array : np.ndarray
        8,760 hourly load or demand values.
    top_n : int
        Number of peak hours (default 100).
    weighting_method : str
        'exceedance' (weighted above cutoff threshold) or 'uniform' (1/top_n).

    Returns
    -------
    np.ndarray
        8,760 array summing to 1.0.
    """
    arr = np.asarray(demand_array, dtype=float)
    n = min(top_n, len(arr))
    cwf = np.zeros(len(arr), dtype=float)

    # Sort indices descending
    top_indices = np.argsort(arr)[-n:]

    if weighting_method == "uniform":
        cwf[top_indices] = 1.0 / n
    else:  # exceedance
        # Baseline threshold is the value just below the top N (or slightly below minimum if n == len(arr))
        sorted_arr = np.sort(arr)
        cutoff = sorted_arr[-(n + 1)] if n < len(arr) else sorted_arr[0] * 0.99
        exceed = np.maximum(0.0, arr[top_indices] - cutoff)
        s = np.sum(exceed)
        if s > 0:
            cwf[top_indices] = exceed / s
        else:
            cwf[top_indices] = 1.0 / n

    return cwf


def calculate_cwf_peaker_rent(energy_price_array, heat_rate=10500.0, gas_price=3.50, vom=4.0):
    """
    Calculate an 8,760 CWF based on peaker operating spark spread / inframarginal rents.

    Parameters
    ----------
    energy_price_array : np.ndarray
        Hourly wholesale energy prices ($/MWh).
    heat_rate : float
        Combustion turbine heat rate in Btu/kWh (default 10,500).
    gas_price : float
        Delivered natural gas price in $/MMBtu (default $3.50).
    vom : float
        Variable O&M in $/MWh (default $4.00).

    Returns
    -------
    np.ndarray
        8,760 array summing to 1.0.
    """
    prices = np.asarray(energy_price_array, dtype=float)
    # CT variable operating cost ($/MWh) = (Btu/kWh / 1000 * $/MMBtu) + VOM
    ct_vom = (heat_rate / 1000.0) * gas_price + vom
    spark_spread = np.maximum(0.0, prices - ct_vom)
    s = np.sum(spark_spread)
    if s > 0:
        return spark_spread / s
    return np.ones(len(prices)) / len(prices)


def calculate_feeder_pcaf_weights(feeder_type="System Coincident (Top 100 Peak Hours)",
                                  load_array=None, price_array=None, datetime_series=None, top_n=100):
    """
    Compute localized distribution peak weighting factors for feeder T&D deferral.

    Parameters
    ----------
    feeder_type : str
        Type of feeder profile:
        - "System Coincident (Top 100 Peak Hours)" / "Wholesale Price PCAF (Top 100 Hours)"
        - "Winter-Peaking Feeder (Southeast Heating / Dec–Feb 6–9 AM)"
        - "Summer-Peaking Feeder (Southeast Cooling / Jun–Sep 2–6 PM)"
        - "Dual-Peaking Feeder (Suburban Mixed 50/50)"
    load_array : np.ndarray, optional
        Local circuit or building load array.
    price_array : np.ndarray, optional
        System energy prices for wholesale PCAF.
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps.
    top_n : int
        Number of localized peak hours.

    Returns
    -------
    np.ndarray
        Array of weights summing to 1.0.
    """
    n_hours = 8760
    if load_array is not None:
        n_hours = len(load_array)
    elif price_array is not None:
        n_hours = len(price_array)

    if datetime_series is not None:
        dts = pd.to_datetime(datetime_series)
        months = dts.dt.month.to_numpy()
        hours = dts.dt.hour.to_numpy()
    else:
        h_idx = np.arange(n_hours)
        days = h_idx // 24
        hours = h_idx % 24
        month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        cum_days = np.cumsum([0] + month_days)
        months = np.zeros(n_hours, dtype=int)
        for m in range(12):
            months[(days >= cum_days[m]) & (days < cum_days[m+1])] = m + 1

    weights = np.zeros(n_hours, dtype=float)

    if "Winter-Peaking" in feeder_type:
        mask = np.isin(months, [12, 1, 2]) & np.isin(hours, [6, 7, 8])
        if load_array is not None and mask.sum() > 0:
            sub_loads = load_array[mask]
            k = min(top_n, len(sub_loads))
            top_k_vals = np.sort(sub_loads)[-k:]
            cutoff = top_k_vals[0]
            is_peak = mask & (load_array >= cutoff)
            weights[is_peak] = 1.0 / is_peak.sum() if is_peak.sum() > 0 else 0.0
        elif mask.sum() > 0:
            weights[mask] = 1.0 / mask.sum()

    elif "Summer-Peaking" in feeder_type:
        mask = np.isin(months, [6, 7, 8, 9]) & np.isin(hours, [14, 15, 16, 17])
        if load_array is not None and mask.sum() > 0:
            sub_loads = load_array[mask]
            k = min(top_n, len(sub_loads))
            top_k_vals = np.sort(sub_loads)[-k:]
            cutoff = top_k_vals[0]
            is_peak = mask & (load_array >= cutoff)
            weights[is_peak] = 1.0 / is_peak.sum() if is_peak.sum() > 0 else 0.0
        elif mask.sum() > 0:
            weights[mask] = 1.0 / mask.sum()

    elif "Dual-Peaking" in feeder_type:
        w_cwf = calculate_southeast_dual_peak_cwf(
            datetime_series=datetime_series,
            winter_weight=0.5,
            summer_weight=0.5,
            load_array=load_array,
            n_hours=n_hours
        )
        weights = w_cwf

    else:  # Wholesale Price PCAF (top 100 price hours)
        if price_array is not None:
            top_indices = np.argsort(price_array)[-top_n:]
            weights[top_indices] = 1.0 / len(top_indices)
        else:
            # Fallback uniform
            weights = np.ones(n_hours) / n_hours

    s = weights.sum()
    if s > 0:
        weights /= s
    else:
        weights = np.ones(n_hours) / n_hours

    return weights


def find_peak_week(datetime_series, stress_signal, month_filter, mode="max", window_hours=168):
    """
    Find the contiguous `window_hours`-long window (starting on a day
    boundary) that best matches `mode` within the given months, scored by
    summing `stress_signal` over each candidate window.

    Used to pick a genuinely representative "Winter Peak Week," "Summer
    Peak Week," or "Shoulder Week" from the actual loaded data, instead of
    assuming a fixed calendar week (e.g. "Jan 1-7") is representative every
    run — the real peak hour can land anywhere depending on the selected
    grid scenario/state/year, and a fixed window can miss it entirely.

    Parameters
    ----------
    datetime_series : pd.Series or array-like of datetime
        Timestamp for each hour (typically 8,760 hours).
    stress_signal : np.ndarray
        Per-hour value summed over each candidate window (e.g.
        Total_Avoided_Cost_MWh). Higher = more stressed.
    month_filter : list of int
        Calendar months (1-12) the window must be entirely contained
        within, so a "Winter Peak Week" can't land in July.
    mode : str
        "max" for the highest-stress window, "min" for the lowest (e.g. a
        representative Shoulder Week).
    window_hours : int
        Window length in hours (default 168 = 7 days).

    Returns
    -------
    tuple of (int, int), or None
        (start_hour, end_hour) half-open index range, or None if no
        window_hours-long window fits entirely within month_filter.
    """
    dts = pd.to_datetime(pd.Series(np.asarray(datetime_series)).reset_index(drop=True))
    months = dts.dt.month.to_numpy()
    vals = np.asarray(stress_signal, dtype=float)
    n = len(vals)

    best_start = None
    best_score = -np.inf if mode == "max" else np.inf
    for day_start in range(0, n - window_hours + 1, 24):
        window_months = months[day_start:day_start + window_hours]
        if not np.isin(window_months, month_filter).all():
            continue
        score = vals[day_start:day_start + window_hours].sum()
        if (mode == "max" and score > best_score) or (mode == "min" and score < best_score):
            best_score = score
            best_start = day_start

    if best_start is None:
        return None
    return best_start, best_start + window_hours


# ==============================================================================
# PUBLIC-DATA SYSTEM-STRESS CAPACITY-CREDIT PROXY (EIA-930 / EIA-861)
# ==============================================================================

def _extract_months_and_hours(n_hours: int, datetime_series=None):
    """Extract 1-based month (1..12) and 0-based hour-of-day (0..23) arrays."""
    if datetime_series is not None:
        dts = pd.to_datetime(pd.Series(np.asarray(datetime_series)).reset_index(drop=True))
        if len(dts) == n_hours and not dts.isna().any():
            return dts.dt.month.to_numpy(dtype=int), dts.dt.hour.to_numpy(dtype=int)

    h_idx = np.arange(n_hours, dtype=int)
    days = h_idx // 24
    hours = h_idx % 24
    month_days = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    cum_days = np.cumsum([0] + month_days)
    months = np.zeros(n_hours, dtype=int)
    for m in range(12):
        months[(days >= cum_days[m]) & (days < cum_days[m + 1])] = m + 1
    # If n_hours > 8760, assign remaining days to month 12
    months[months == 0] = 12
    return months, hours


def _compute_weight_diagnostics(weights: np.ndarray, datetime_series=None) -> dict:
    """Compute concentration, monthly, and seasonal diagnostics for an 8,760 weight vector."""
    w = np.asarray(weights, dtype=float)
    n_hours = len(w)
    months, _ = _extract_months_and_hours(n_hours, datetime_series=datetime_series)

    nonzero_hours = int(np.sum(w > 0.0))
    max_hour_share = float(np.max(w)) if n_hours > 0 else 0.0
    sum_sq = float(np.sum(w ** 2))
    effective_hours = float(1.0 / sum_sq) if sum_sq > 0.0 else 0.0

    monthly_shares = {int(m): float(np.sum(w[months == m])) for m in range(1, 13)}
    seasonal_shares = {
        "Winter (Dec-Feb)": float(np.sum(w[np.isin(months, [12, 1, 2])])),
        "Spring (Mar-May)": float(np.sum(w[np.isin(months, [3, 4, 5])])),
        "Summer (Jun-Sep)": float(np.sum(w[np.isin(months, [6, 7, 8, 9])])),
        "Fall (Oct-Nov)": float(np.sum(w[np.isin(months, [10, 11])])),
    }
    top_k = min(20, n_hours)
    top_indices = [int(i) for i in np.argsort(w)[::-1][:top_k] if w[i] > 0.0]

    return {
        "nonzero_hours": nonzero_hours,
        "max_hour_share": max_hour_share,
        "effective_hours": effective_hours,
        "monthly_shares": monthly_shares,
        "seasonal_shares": seasonal_shares,
        "top_hours_indices": top_indices,
    }


def calculate_upper_tail_stress_weights(
    signal_array,
    percentile: float = 95.0,
    datetime_series=None,
):
    """
    Compute upper-tail exceedance capacity weights for a single Balancing Authority (BA)
    or system stress signal (net demand or gross demand in MW).

    Mathematical definition:
        threshold = quantile(signal, q)
        exceedance[h] = max(signal[h] - threshold, 0)
        BA_weight[h] = exceedance[h] / sum(exceedance)

    Parameters
    ----------
    signal_array : array-like
        1D hourly stress signal (typically 8,760 hours of net demand or gross demand in MW).
    percentile : float, default 95.0
        Upper-tail threshold percentile in [90.0, 99.0] (or quantile in [0.90, 0.99]).
    datetime_series : array-like, optional
        Optional timestamps corresponding to signal_array for monthly/seasonal diagnostics.

    Returns
    -------
    tuple of (np.ndarray, dict)
        (weights, diagnostics) where `weights` is a 1D float array summing to 1.0.
    """
    arr = np.asarray(signal_array, dtype=float)
    if arr.ndim != 1 or len(arr) == 0:
        raise ValueError("signal_array must be a non-empty 1D array.")
    if not np.isfinite(arr).all():
        raise ValueError("signal_array contains NaN or infinite values.")

    pct = float(percentile)
    if 0.90 <= pct <= 0.99:
        pct = pct * 100.0
    if pct < 90.0 or pct > 99.0:
        raise ValueError(
            f"System-stress threshold percentile must be between 90.0 and 99.0 (got {percentile})."
        )

    sig_range = float(np.max(arr) - np.min(arr))
    sig_std = float(np.std(arr))
    if sig_range <= 1e-9 or sig_std <= 1e-9:
        raise ValueError(
            "Signal has no meaningful variation (flat or constant series); fails system-stress qualification."
        )

    q = pct / 100.0
    threshold = float(np.quantile(arr, q))
    exceedance = np.maximum(arr - threshold, 0.0)
    exc_sum = float(np.sum(exceedance))

    if exc_sum > 0.0:
        weights = exceedance / exc_sum
        tie_fallback_used = False
    else:
        # Upper-tail tie: multiple hours equal the maximum so quantile(signal, q) == max(signal),
        # while overall signal has verified variation. Allocate uniformly across tied maximum hours.
        max_val = float(np.max(arr))
        tied_mask = np.isclose(arr, max_val, rtol=1e-12, atol=1e-9)
        n_tied = int(np.sum(tied_mask))
        if n_tied <= 0:
            raise ValueError("Unable to identify upper-tail stress hours.")
        weights = np.where(tied_mask, 1.0 / n_tied, 0.0)
        tie_fallback_used = True

    # Enforce exact normalization
    weights = np.maximum(weights, 0.0)
    w_sum = float(np.sum(weights))
    weights = weights / w_sum

    diag = _compute_weight_diagnostics(weights, datetime_series=datetime_series)
    diag.update({
        "threshold_mw": threshold,
        "percentile": pct,
        "quantile": q,
        "signal_max_mw": float(np.max(arr)),
        "signal_min_mw": float(np.min(arr)),
        "signal_mean_mw": float(np.mean(arr)),
        "tie_fallback_used": tie_fallback_used,
    })
    return weights, diag


def combine_ba_weights_to_state_portfolio(
    ba_weights_map: dict,
    state_ba_shares_map: dict,
    selected_states: list,
    fallback_state_weights: dict = None,
    datetime_series=None,
):
    """
    Combine BA-level 8,760 stress weight vectors into a state or multi-state portfolio
    capacity weight vector using EIA-861 residential sales shares.

    Follows Section A & C of the specification:
    1. Within each state s, retained BA shares are normalized to sum to 1.0.
    2. Across multiple selected states, each state receives equal portfolio weight (1 / N_states).
    3. Repeated BA shares across states are summed before multiplying by the BA's hourly weight
       vector so that no BA is fetched or counted twice on an unnormalized basis.
    4. If a subset of states falls back to weather-based weights (`fallback_state_weights`),
       those states contribute their equal state share via their fallback vector while
       retained states use their BA-weighted stress vectors.

    Parameters
    ----------
    ba_weights_map : dict[str, np.ndarray]
        Mapping of `{ba_code: 8760_weight_array}` for all qualified BAs.
    state_ba_shares_map : dict[str, dict[str, float]]
        Mapping of `{state_code: {ba_code: residential_sales_share}}` for states using EIA stress data.
    selected_states : list[str]
        Ordered list of selected state codes (e.g. `["GA", "NC"]`).
    fallback_state_weights : dict[str, np.ndarray], optional
        Optional mapping `{state_code: 8760_weight_array}` for states that fell back to weather CWF.
    datetime_series : array-like, optional
        Optional timestamps for monthly/seasonal diagnostics.

    Returns
    -------
    tuple of (np.ndarray, dict)
        (portfolio_weights, portfolio_diagnostics)
    """
    if not selected_states:
        raise ValueError("selected_states must not be empty.")

    fallback_state_weights = fallback_state_weights or {}
    clean_states = [str(s).strip().upper() for s in selected_states if str(s).strip()]
    if not clean_states:
        raise ValueError("selected_states must contain at least one valid state code.")

    # Determine vector length from available BA or fallback weight arrays
    n_hours = None
    for arr in list(ba_weights_map.values()) + list(fallback_state_weights.values()):
        arr_np = np.asarray(arr, dtype=float)
        if n_hours is None:
            n_hours = len(arr_np)
        elif len(arr_np) != n_hours:
            raise ValueError(f"Inconsistent weight vector lengths: expected {n_hours}, got {len(arr_np)}.")

    if n_hours is None or n_hours == 0:
        raise ValueError("No valid BA or fallback weight vectors provided.")

    n_states = len(clean_states)
    state_portfolio_weights = {s: 1.0 / n_states for s in clean_states}

    # Sum repeated BA shares across states BEFORE multiplying by BA hourly weights
    combined_ba_shares: dict = {}
    normalized_state_ba_shares: dict = {}
    stress_states = []
    fallback_states = []

    for s in clean_states:
        s_w = state_portfolio_weights[s]
        raw_ba_map = state_ba_shares_map.get(s, {})
        # Keep only BAs present in ba_weights_map with positive share
        usable_ba_map = {
            str(ba).strip().upper(): float(sh)
            for ba, sh in raw_ba_map.items()
            if str(ba).strip().upper() in ba_weights_map and float(sh) > 0.0
        }
        retained_sum = sum(usable_ba_map.values())

        if retained_sum > 0.0:
            norm_ba_map = {ba: sh / retained_sum for ba, sh in usable_ba_map.items()}
            normalized_state_ba_shares[s] = norm_ba_map
            stress_states.append(s)
            for ba, norm_sh in norm_ba_map.items():
                combined_ba_shares[ba] = combined_ba_shares.get(ba, 0.0) + s_w * norm_sh
        elif s in fallback_state_weights:
            fallback_states.append(s)
            normalized_state_ba_shares[s] = {}
        else:
            raise ValueError(
                f"State '{s}' has no qualified BA stress weights and no fallback weight vector."
            )

    portfolio_weights = np.zeros(n_hours, dtype=float)

    # 1. Add deduplicated BA stress contributions
    for ba, portfolio_ba_share in combined_ba_shares.items():
        ba_w = np.asarray(ba_weights_map[ba], dtype=float)
        ba_w_sum = float(np.sum(ba_w))
        if ba_w_sum <= 0.0:
            raise ValueError(f"BA '{ba}' weight vector has non-positive sum.")
        portfolio_weights += portfolio_ba_share * (ba_w / ba_w_sum)

    # 2. Add fallback state contributions (if mixed portfolio)
    for s in fallback_states:
        s_w = state_portfolio_weights[s]
        fb_w = np.asarray(fallback_state_weights[s], dtype=float)
        fb_sum = float(np.sum(fb_w))
        if fb_sum <= 0.0:
            raise ValueError(f"Fallback weight vector for state '{s}' has non-positive sum.")
        portfolio_weights += s_w * (fb_w / fb_sum)

    portfolio_weights = np.maximum(portfolio_weights, 0.0)
    total_w = float(np.sum(portfolio_weights))
    if total_w <= 0.0:
        raise ValueError("Combined portfolio weight vector summed to zero.")
    portfolio_weights = portfolio_weights / total_w

    diag = _compute_weight_diagnostics(portfolio_weights, datetime_series=datetime_series)
    diag.update({
        "selected_states": clean_states,
        "state_portfolio_weights": state_portfolio_weights,
        "normalized_state_ba_shares": normalized_state_ba_shares,
        "combined_ba_shares": combined_ba_shares,
        "stress_states": stress_states,
        "fallback_states": fallback_states,
        "is_mixed_portfolio": bool(len(stress_states) > 0 and len(fallback_states) > 0),
    })
    return portfolio_weights, diag


def calculate_system_stress_capacity_metrics(
    baseline_kw,
    proposed_kw,
    portfolio_weights,
    cap_value_kw_yr: float,
    dr_mode: bool = False,
    dr_capacity_kw: float = None,
    dr_performance_factor: float = 1.0,
) -> dict:
    """
    Compute generation-capacity valuation metrics under a given 8,760 capacity-weight vector.

    Preserves existing hourly valuation mechanics:
      - Fixed building profiles: hourly capacity benefit = (baseline_kW - proposed_kW) * weight[h] * cap_value_kw_yr
      - DR mode: when `dr_mode=True` and `dr_capacity_kw` is provided, accredited capacity is
        `dr_capacity_kw * dr_performance_factor` allocated across positive-weight hours.
      - Proxy coincidence ratio (`capacity_credit_kw / max_positive_reduction_kw`) is reported
        strictly for display/screening and NEVER applied as an additional derate.
      - Handles zero or all-negative load reductions cleanly without divide-by-zero or misleading percentages.
    """
    base_arr = np.asarray(baseline_kw, dtype=float)
    prop_arr = np.asarray(proposed_kw, dtype=float)
    w_arr = np.asarray(portfolio_weights, dtype=float)

    if base_arr.shape != prop_arr.shape or base_arr.shape != w_arr.shape:
        raise ValueError(
            f"Shape mismatch in capacity metric calculation: baseline={base_arr.shape}, "
            f"proposed={prop_arr.shape}, weights={w_arr.shape}."
        )
    if np.any(w_arr < 0.0):
        raise ValueError("portfolio_weights cannot contain negative values.")
    w_sum = float(np.sum(w_arr))
    if w_sum <= 0.0:
        raise ValueError("portfolio_weights must have a strictly positive sum.")
    if not np.isclose(w_sum, 1.0, atol=1e-6):
        w_arr = w_arr / w_sum

    hourly_load_reduction_kw = base_arr - prop_arr
    hourly_cap_rates_kw_hr = w_arr * float(cap_value_kw_yr)

    # Effective Peak Coincidence (weighted kW reduction during capacity-risk hours)
    capacity_credit_kw = float(np.sum(hourly_load_reduction_kw * w_arr))

    if dr_mode and dr_capacity_kw is not None:
        accredited_capacity_kw = float(dr_capacity_kw) * float(dr_performance_factor)
        hourly_cap_benefit_dollars = np.where(
            w_arr > 0.0,
            accredited_capacity_kw * hourly_cap_rates_kw_hr,
            0.0,
        )
    else:
        accredited_capacity_kw = capacity_credit_kw
        hourly_cap_benefit_dollars = hourly_load_reduction_kw * hourly_cap_rates_kw_hr

    generation_capacity_annual_dollars = float(np.sum(hourly_cap_benefit_dollars))
    max_positive_reduction_kw = float(np.max(hourly_load_reduction_kw)) if len(hourly_load_reduction_kw) > 0 else 0.0

    if max_positive_reduction_kw > 1e-6:
        proxy_coincidence_ratio = float(capacity_credit_kw / max_positive_reduction_kw)
        proxy_coincidence_pct = float(proxy_coincidence_ratio * 100.0)
        proxy_ratio_valid = True
        proxy_ratio_status = "valid"
    else:
        proxy_coincidence_ratio = None
        proxy_coincidence_pct = None
        proxy_ratio_valid = False
        if np.allclose(hourly_load_reduction_kw, 0.0, atol=1e-9):
            proxy_ratio_status = "no_positive_load_reduction"
        else:
            proxy_ratio_status = "negative_or_zero_peak_reduction"

    return {
        "capacity_credit_kw": capacity_credit_kw,
        "accredited_capacity_kw": accredited_capacity_kw,
        "generation_capacity_annual_dollars": generation_capacity_annual_dollars,
        "max_positive_reduction_kw": max_positive_reduction_kw,
        "proxy_coincidence_ratio": proxy_coincidence_ratio,
        "proxy_coincidence_pct": proxy_coincidence_pct,
        "proxy_ratio_valid": proxy_ratio_valid,
        "proxy_ratio_status": proxy_ratio_status,
        "hourly_load_reduction_kw": hourly_load_reduction_kw,
        "hourly_cap_rates_kw_hr": hourly_cap_rates_kw_hr,
        "hourly_cap_benefit_dollars": hourly_cap_benefit_dollars,
    }



# ==============================================================================
# CAMBIUM REGIONAL NET-DEMAND EXCEEDANCE WEIGHTING & GEA PORTFOLIO MATH
# ==============================================================================

def calculate_cambium_net_demand_exceedance_weights(
    net_load_array,
    datetime_series=None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Compute Cambium regional net-demand exceedance capacity weights per Cambium 2024
    documentation (S1, PDF p.70):
        threshold = min(N_101, 0.95 * max(N))
        excess[h] = max(N[h] - threshold, 0)
        weight[h] = excess[h] / sum(excess)

    where N_101 is the 101st-highest hour value among the 8,760 net load observations.
    (Note: 95% of peak net load, NOT the 95th percentile).

    Parameters
    ----------
    net_load_array : array-like
        1D array of 8,760 regional net load values (MWh).
    datetime_series : array-like, optional
        Optional 8,760-element datetime series for monthly/seasonal diagnostics.

    Returns
    -------
    tuple of (np.ndarray, dict)
        (weights, diagnostics) where weights is a 1D float array summing to 1.0.
    """
    arr = np.asarray(net_load_array, dtype=float)
    if arr.ndim != 1 or len(arr) == 0:
        raise ValueError("net_load_array must be a non-empty 1D array.")
    if len(arr) != 8760:
        raise ValueError(f"net_load_array must contain exactly 8,760 hours (got {len(arr)}).")
    if not np.isfinite(arr).all():
        raise ValueError("net_load_array contains NaN or infinite values.")

    max_n = float(np.max(arr))
    if max_n <= 0.0:
        raise ValueError(f"Peak regional net load is non-positive ({max_n:.2f}); cannot compute exceedance.")

    sig_range = float(max_n - np.min(arr))
    sig_std = float(np.std(arr))
    if sig_range <= 1e-9 or sig_std <= 1e-9:
        raise ValueError("Signal has no meaningful variation (flat/constant); fails exceedance qualification.")

    sorted_desc = np.sort(arr)[::-1]
    # 101st-highest value (0-indexed: index 100)
    n_101 = float(sorted_desc[100])
    threshold = float(min(n_101, 0.95 * max_n))

    excess = np.maximum(arr - threshold, 0.0)
    total_excess = float(np.sum(excess))
    if total_excess <= 0.0:
        raise ValueError(f"Sum of excess above threshold {threshold:.2f} is non-positive; cannot normalize.")

    weights = excess / total_excess
    diag = _compute_weight_diagnostics(weights, datetime_series=datetime_series)
    diag.update({
        "peak_net_load": max_n,
        "n_101": n_101,
        "threshold": threshold,
        "total_excess_mwh": total_excess,
        "active_hours": int(np.sum(weights > 0.0)),
        "top_hour_share": float(np.max(weights)),
        "formula": "min(N_101, 0.95 * max(N))",
    })

    return weights, diag


def calculate_cambium_seasonal_net_demand_weights(
    net_load_array,
    datetime_series=None,
    winter_weight: float = 0.60,
    summer_weight: Optional[float] = None,
    winter_months: tuple = (12, 1, 2),
    summer_months: tuple = (6, 7, 8, 9),
    top_n_peak_hours: int = 100,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Computes Cambium regional net-demand capacity weights with explicit dual-peak
    seasonal allocation (Winter + Summer).

    Applies Cambium S1 exceedance (threshold = min(N_101, 0.95 * max(N)))
    separately within Winter (Dec–Feb) and Summer (Jun–Sep) regional net load hours,
    then combines them using winter_weight and summer_weight (default 60% winter / 40% summer).

    Avoids single-season regional dilution (e.g. peninsular Florida cooling load
    overwhelming winter heating peaks) while remaining 100% grounded in modeled
    physical net-demand stress (MWh).

    Parameters
    ----------
    net_load_array : array-like
        8,760 hourly regional net load values (MWh).
    datetime_series : array-like, optional
        8,760 hourly timestamps.
    winter_weight : float
        Fraction of capacity value allocated to winter net-demand peak hours (default 0.60).
    summer_weight : float, optional
        Fraction of capacity value allocated to summer net-demand peak hours.
        Defaults to (1.0 - winter_weight).
    winter_months : tuple of int
        Months considered winter (default 12, 1, 2).
    summer_months : tuple of int
        Months considered summer (default 6, 7, 8, 9).

    Returns
    -------
    tuple of (np.ndarray, dict)
        (weights, diagnostics) where weights is an 8,760-element array summing to 1.0.
    """
    arr = np.asarray(net_load_array, dtype=float)
    if arr.ndim != 1 or len(arr) != 8760:
        raise ValueError(f"net_load_array must contain exactly 8,760 hours (got {len(arr)}).")
    if not np.isfinite(arr).all():
        raise ValueError("net_load_array contains NaN or infinite values.")

    if summer_weight is None:
        summer_weight = max(0.0, 1.0 - float(winter_weight))

    tot_weight = float(winter_weight + summer_weight)
    if tot_weight <= 0.0:
        raise ValueError("Sum of winter_weight and summer_weight must be positive.")
    w_norm = float(winter_weight) / tot_weight
    s_norm = float(summer_weight) / tot_weight

    n_hours = len(arr)
    months, _ = _extract_months_and_hours(n_hours, datetime_series=datetime_series)
    weights = np.zeros(n_hours, dtype=float)

    winter_mask = np.isin(months, winter_months)
    summer_mask = np.isin(months, summer_months)

    diag_extra: Dict[str, Any] = {
        "winter_weight": w_norm,
        "summer_weight": s_norm,
    }

    # Allocate total top_n_peak_hours across seasons proportionally to seasonal risk weights
    # so that total active stress hours across both seasons exactly matches top_n_peak_hours.
    if w_norm > 0.0 and s_norm > 0.0:
        w_peak_hrs = max(1, int(round(top_n_peak_hours * w_norm)))
        s_peak_hrs = max(1, top_n_peak_hours - w_peak_hrs)
    elif w_norm > 0.0:
        w_peak_hrs = top_n_peak_hours
        s_peak_hrs = 0
    else:
        w_peak_hrs = 0
        s_peak_hrs = top_n_peak_hours

    # Evaluate winter if weight > 0
    if w_norm > 0.0 and np.any(winter_mask):
        w_sub = arr[winter_mask]
        w_max = float(np.max(w_sub))
        if w_max > 0.0:
            w_sorted = np.sort(w_sub)[::-1]
            n_rank = min(w_peak_hrs, len(w_sub) - 1)
            w_n101 = float(w_sorted[n_rank])
            w_thresh = float(min(w_n101, 0.95 * w_max))
            w_excess = np.maximum(w_sub - w_thresh, 0.0)
            tot_w_excess = float(np.sum(w_excess))
            if tot_w_excess > 0.0:
                weights[winter_mask] += w_norm * (w_excess / tot_w_excess)
                diag_extra["winter_peak_net_load"] = w_max
                diag_extra["winter_threshold"] = w_thresh
                diag_extra["active_winter_hours"] = int(np.sum(w_excess > 0.0))

    # Evaluate summer if weight > 0
    if s_norm > 0.0 and np.any(summer_mask):
        s_sub = arr[summer_mask]
        s_max = float(np.max(s_sub))
        if s_max > 0.0:
            s_sorted = np.sort(s_sub)[::-1]
            n_rank = min(s_peak_hrs, len(s_sub) - 1)
            s_n101 = float(s_sorted[n_rank])
            s_thresh = float(min(s_n101, 0.95 * s_max))
            s_excess = np.maximum(s_sub - s_thresh, 0.0)
            tot_s_excess = float(np.sum(s_excess))
            if tot_s_excess > 0.0:
                weights[summer_mask] += s_norm * (s_excess / tot_s_excess)
                diag_extra["summer_peak_net_load"] = s_max
                diag_extra["summer_threshold"] = s_thresh
                diag_extra["active_summer_hours"] = int(np.sum(s_excess > 0.0))

    # Normalize final weights
    w_sum = float(np.sum(weights))
    if w_sum > 0.0:
        weights = weights / w_sum
    else:
        raise ValueError("Computed seasonal net-demand weights sum to 0.")

    diag = _compute_weight_diagnostics(weights, datetime_series=datetime_series)
    diag.update(diag_extra)
    diag.update({
        "active_hours": int(np.sum(weights > 0.0)),
        "top_hour_share": float(np.max(weights)),
        "method": "Seasonal Split Net-Demand (Cambium)",
    })
    return weights, diag


def combine_gea_weights_to_state_portfolio(
    gea_weights_by_state: Dict[str, np.ndarray],
    state_shares: Optional[Dict[str, float]] = None,
) -> np.ndarray:
    """
    Combines normalized state-level stress weight curves into a multi-state
    representative-building portfolio curve.

    Defaults to equal-state weighting across selected states, explicitly
    representing an unweighted portfolio of identical local buildings across states.
    """
    if not gea_weights_by_state:
        raise ValueError("No state weights provided for portfolio combination.")

    states = list(gea_weights_by_state.keys())
    n_states = len(states)
    sample_w = next(iter(gea_weights_by_state.values()))
    n_hours = len(sample_w)

    if state_shares is None:
        # Equal state weighting
        shares = {st: 1.0 / n_states for st in states}
    else:
        tot_share = sum(state_shares.values())
        if tot_share <= 0:
            raise ValueError(f"State shares must sum to > 0 (got {tot_share}).")
        shares = {st: state_shares.get(st, 0.0) / tot_share for st in states}

    combined = np.zeros(n_hours, dtype=float)
    for st, w in gea_weights_by_state.items():
        w_arr = np.asarray(w, dtype=float)
        if len(w_arr) != n_hours:
            raise ValueError(f"Length mismatch for state {st}: {len(w_arr)} != {n_hours}")
        combined += shares.get(st, 0.0) * w_arr

    comb_sum = float(np.sum(combined))
    if comb_sum > 0.0:
        combined = combined / comb_sum
    return combined


# ==============================================================================
# MULTI-YEAR CAMBIUM MILESTONE INTERPOLATION & VALUATION ENGINE
# ==============================================================================

def interpolate_cambium_milestone_8760(
    milestone_data: Dict[int, np.ndarray],
    target_years: List[int],
) -> Dict[int, np.ndarray]:
    """
    Linearly interpolate hourly 8,760 profiles between Cambium milestone years.

    For inter-milestone years t between Y1 and Y2, each hour h is calculated as:
        P_{h, t} = P_{h, Y1} + ((t - Y1) / (Y2 - Y1)) * (P_{h, Y2} - P_{h, Y1})

    Years before the earliest milestone are clamped to the earliest milestone.
    Years after the latest milestone are clamped to the latest milestone.

    Parameters
    ----------
    milestone_data : Dict[int, np.ndarray]
        Mapping from integer milestone year (e.g. {2024: p_24, 2030: p_30, 2035: p_35, 2045: p_45})
        to 8,760-element numpy array.
    target_years : List[int]
        List of integer calendar years to interpolate across (e.g. [2025, 2026, ..., 2039]).

    Returns
    -------
    Dict[int, np.ndarray]
        Mapping from each target year to its interpolated 8,760 numpy array.
    """
    if not milestone_data:
        raise ValueError("milestone_data dictionary cannot be empty.")

    sorted_milestones = sorted(int(k) for k in milestone_data.keys())
    first_arr = np.asarray(milestone_data[sorted_milestones[0]], dtype=float)
    n_hours = len(first_arr)
    if n_hours == 0:
        raise ValueError("Milestone arrays cannot be empty.")

    # Normalize keys to int and validate dimensions
    norm_milestones: Dict[int, np.ndarray] = {}
    for m in sorted_milestones:
        arr = np.asarray(milestone_data[m], dtype=float)
        if len(arr) != n_hours:
            raise ValueError(f"Milestone year {m} length ({len(arr)}) does not match expected ({n_hours}).")
        norm_milestones[m] = arr

    interpolated: Dict[int, np.ndarray] = {}

    for yr in target_years:
        yr_int = int(yr)
        if yr_int in norm_milestones:
            interpolated[yr_int] = norm_milestones[yr_int].copy()
        elif yr_int <= sorted_milestones[0]:
            interpolated[yr_int] = norm_milestones[sorted_milestones[0]].copy()
        elif yr_int >= sorted_milestones[-1]:
            interpolated[yr_int] = norm_milestones[sorted_milestones[-1]].copy()
        else:
            # Find bounding milestone years Y1 <= yr_int <= Y2
            y1 = max(m for m in sorted_milestones if m <= yr_int)
            y2 = min(m for m in sorted_milestones if m >= yr_int)
            if y1 == y2:
                interpolated[yr_int] = norm_milestones[y1].copy()
            else:
                weight = float(yr_int - y1) / float(y2 - y1)
                p1 = norm_milestones[y1]
                p2 = norm_milestones[y2]
                interpolated[yr_int] = p1 + weight * (p2 - p1)

    return interpolated


def calculate_multi_year_avoided_costs_and_npv(
    asset_life: int,
    start_year: int,
    interpolated_energy_prices: Dict[int, np.ndarray],
    load_reduction: np.ndarray,
    cwft_array: np.ndarray,
    pcaf_array: np.ndarray,
    cap_value: float,
    trans_value: float,
    dist_value: float,
    carbon_tax: float,
    discount_rate: float,
    customer_discount_rate: float,
    degradation_rate: float,
    annual_lost_revenue_yr1: float,
    retail_escalation_rate: float,
    gross_measure_cost: float = 0.0,
    utility_incentive: float = 0.0,
    utility_admin_cost: float = 0.0,
    dr_capacity_derate: float = 1.0,
    capacity_escalation_rate: float = 0.0,
    interpolated_carbon_emissions: Optional[Dict[int, np.ndarray]] = None,
    dist_weight_array: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """
    Compute multi-year avoided costs and NPV using dynamic hourly Cambium milestone trajectories.

    Instead of applying a single flat annual percentage escalator across all hours,
    this function evaluates each operating year t with that year's specific interpolated
    8,760 wholesale energy price vector (and optionally carbon emissions vector).

    Parameters
    ----------
    asset_life : int
        Measure operating lifetime in years (e.g. 15).
    start_year : int
        Base calendar year (e.g. 2026).
    interpolated_energy_prices : Dict[int, np.ndarray]
        Mapping of calendar year to 8,760 wholesale energy prices ($/MWh).
    load_reduction : np.ndarray
        8,760 hourly load reduction array in kW.
    cwft_array : np.ndarray
        8,760 Capacity Weighting Factor Table values (sums to 1.0).
    pcaf_array : np.ndarray
        8,760 Peak Capacity Allocation Factors for transmission/distribution (sums to 1.0).
    cap_value : float
        Generation capacity value in $/kW-year.
    trans_value : float
        Transmission capacity value in $/kW-year.
    dist_value : float
        Distribution capacity value in $/kW-year.
    carbon_tax : float
        Carbon price in $/metric ton CO2.
    discount_rate : float
        Utility discount rate / WACC in percent (e.g. 7.0).
    customer_discount_rate : float
        Customer discount rate in percent (e.g. 7.0).
    degradation_rate : float
        Annual equipment efficiency degradation in percent (e.g. 1.0).
    annual_lost_revenue_yr1 : float
        Year 1 utility lost retail revenue / customer bill savings ($).
    retail_escalation_rate : float
        Annual retail tariff escalation rate in percent (e.g. 2.0).
    gross_measure_cost : float, optional
        Total installed measure cost ($). Default 0.0.
    utility_incentive : float, optional
        Utility customer rebate / incentive ($). Default 0.0.
    utility_admin_cost : float, optional
        Utility program administrative and marketing cost ($). Default 0.0.
    dr_capacity_derate : float, optional
        Capacity accreditation factor (default 1.0).
    capacity_escalation_rate : float, optional
        Annual inflation on generation and T&D capital replacement costs in percent (default 0.0).
    interpolated_carbon_emissions : Optional[Dict[int, np.ndarray]], optional
        Mapping of calendar year to 8,760 carbon emissions (kg CO2/MWh).
    dist_weight_array : Optional[np.ndarray], optional
        Localized distribution weights (default falls back to pcaf_array).

    Returns
    -------
    Dict[str, Any]
        Dictionary of NPV figures, cash flow arrays, cost tests, and summary DataFrame.
    """
    if asset_life < 1:
        raise ValueError("asset_life must be at least 1 year.")

    years = np.arange(1, asset_life + 1)
    calendar_years = np.array([start_year + t - 1 for t in years])

    discount_pct = discount_rate / 100.0
    cust_discount_pct = customer_discount_rate / 100.0
    degradation_pct = degradation_rate / 100.0
    cap_esc_pct = capacity_escalation_rate / 100.0
    retail_esc_pct = retail_escalation_rate / 100.0

    dist_weights = pcaf_array if dist_weight_array is None else dist_weight_array

    annual_energy_savings = np.zeros(asset_life, dtype=float)
    annual_gen_cap_savings = np.zeros(asset_life, dtype=float)
    annual_trans_savings = np.zeros(asset_life, dtype=float)
    annual_dist_savings = np.zeros(asset_life, dtype=float)
    annual_emissions_savings = np.zeros(asset_life, dtype=float)
    annual_grid_savings = np.zeros(asset_life, dtype=float)
    annual_lost_revenue = np.zeros(asset_life, dtype=float)

    disc_factors = 1.0 / ((1.0 + discount_pct) ** years)
    cust_disc_factors = 1.0 / ((1.0 + cust_discount_pct) ** years)

    for idx, (yr_num, cal_yr) in enumerate(zip(years, calendar_years)):
        deg_factor = (1.0 - degradation_pct) ** (yr_num - 1)
        cap_esc_factor = (1.0 + cap_esc_pct) ** (yr_num - 1)
        retail_esc_factor = (1.0 + retail_esc_pct) ** (yr_num - 1)

        # Degraded load reductions (kW to MWh)
        red_mwh = (load_reduction / 1000.0) * deg_factor
        cap_red_mwh = red_mwh * dr_capacity_derate

        # Hourly energy price for this calendar year
        energy_price_h = interpolated_energy_prices.get(cal_yr)
        if energy_price_h is None:
            # Fall back to closest available year
            avail_years = sorted(interpolated_energy_prices.keys())
            closest_yr = min(avail_years, key=lambda y: abs(y - cal_yr))
            energy_price_h = interpolated_energy_prices[closest_yr]

        # Hourly carbon emissions
        if interpolated_carbon_emissions and cal_yr in interpolated_carbon_emissions:
            carbon_h = interpolated_carbon_emissions[cal_yr]
        elif interpolated_carbon_emissions:
            avail_c_years = sorted(interpolated_carbon_emissions.keys())
            closest_c_yr = min(avail_c_years, key=lambda y: abs(y - cal_yr))
            carbon_h = interpolated_carbon_emissions[closest_c_yr]
        else:
            carbon_h = np.zeros(len(load_reduction), dtype=float)

        # 5 component avoided cost streams for operating year yr_num
        energy_val = float(np.sum(red_mwh * energy_price_h))
        gen_cap_val = float(np.sum(cap_red_mwh * (cap_value * cap_esc_factor * cwft_array * 1000.0)))
        trans_val = float(np.sum(red_mwh * (trans_value * cap_esc_factor * pcaf_array * 1000.0)))
        dist_val = float(np.sum(red_mwh * (dist_value * cap_esc_factor * dist_weights * 1000.0)))
        emiss_val = float(np.sum(red_mwh * ((carbon_h / 1000.0) * (carbon_tax * cap_esc_factor))))

        tot_grid = energy_val + gen_cap_val + trans_val + dist_val + emiss_val
        tot_lost_rev = float(annual_lost_revenue_yr1 * retail_esc_factor * deg_factor)

        annual_energy_savings[idx] = energy_val
        annual_gen_cap_savings[idx] = gen_cap_val
        annual_trans_savings[idx] = trans_val
        annual_dist_savings[idx] = dist_val
        annual_emissions_savings[idx] = emiss_val
        annual_grid_savings[idx] = tot_grid
        annual_lost_revenue[idx] = tot_lost_rev

    # Discounted cash flow series
    grid_savings_disc = annual_grid_savings * disc_factors
    energy_savings_disc = annual_energy_savings * disc_factors
    cap_emiss_savings = annual_gen_cap_savings + annual_trans_savings + annual_dist_savings + annual_emissions_savings
    cap_emiss_savings_disc = cap_emiss_savings * disc_factors

    retail_stream_disc_util = annual_lost_revenue * disc_factors
    customer_stream_disc = annual_lost_revenue * cust_disc_factors

    npv_grid_savings = float(np.sum(grid_savings_disc))
    npv_energy_savings = float(np.sum(energy_savings_disc))
    npv_capacity_savings = float(np.sum(cap_emiss_savings_disc))
    npv_retail_lost_revenue = float(np.sum(retail_stream_disc_util))
    npv_customer_bill_savings = float(np.sum(customer_stream_disc))

    npv_program_cost = float(utility_incentive + utility_admin_cost)
    npv_net_savings = npv_grid_savings - npv_retail_lost_revenue - npv_program_cost

    # Cost-effectiveness tests
    cost_tests = calculate_cost_effectiveness_tests(
        npv_grid_savings=npv_grid_savings,
        npv_lost_revenue=npv_retail_lost_revenue,
        npv_customer_bill_savings=npv_customer_bill_savings,
        gross_measure_cost=gross_measure_cost,
        utility_incentive=utility_incentive,
        utility_admin_cost=utility_admin_cost,
        annual_customer_savings_stream=annual_lost_revenue,
        pv_multipliers=cust_disc_factors,
    )

    # Build detailed cash flow DataFrame
    cum_util_net_pv = np.cumsum(grid_savings_disc - retail_stream_disc_util) - npv_program_cost
    cash_flow_df = pd.DataFrame({
        "Operating_Year": years,
        "Calendar_Year": calendar_years,
        "Wholesale_Energy_Savings": annual_energy_savings,
        "Capacity_Emissions_Savings": cap_emiss_savings,
        "Total_Grid_Savings": annual_grid_savings,
        "Lost_Retail_Revenue": annual_lost_revenue,
        "Discount_Factor_Utility": disc_factors,
        "Discount_Factor_Customer": cust_disc_factors,
        "Discounted_Grid_Savings": grid_savings_disc,
        "Discounted_Lost_Revenue": retail_stream_disc_util,
        "Discounted_Customer_Savings": customer_stream_disc,
        "Cumulative_Utility_Net_PV": cum_util_net_pv,
    })

    return {
        "years": years,
        "calendar_years": calendar_years,
        "annual_energy_savings": annual_energy_savings,
        "annual_gen_cap_savings": annual_gen_cap_savings,
        "annual_trans_savings": annual_trans_savings,
        "annual_dist_savings": annual_dist_savings,
        "annual_emissions_savings": annual_emissions_savings,
        "annual_grid_savings": annual_grid_savings,
        "annual_lost_revenue": annual_lost_revenue,
        "discount_factors": disc_factors,
        "customer_discount_factors": cust_disc_factors,
        "grid_savings_discounted": grid_savings_disc,
        "retail_lost_revenue_discounted": retail_stream_disc_util,
        "customer_bill_savings_discounted": customer_stream_disc,
        "npv_grid_savings": npv_grid_savings,
        "npv_energy_savings": npv_energy_savings,
        "npv_capacity_savings": npv_capacity_savings,
        "npv_retail_lost_revenue": npv_retail_lost_revenue,
        "npv_customer_bill_savings": npv_customer_bill_savings,
        "npv_program_cost": npv_program_cost,
        "npv_net_savings": npv_net_savings,
        "cash_flow_df": cash_flow_df,
        "cost_tests": cost_tests,
    }
