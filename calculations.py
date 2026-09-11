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
    trc_ratio = npv_grid_savings / trc_costs if trc_costs > 0 else 0.0
    trc_npv = npv_grid_savings - trc_costs

    # 2. Participant Cost Test (PCT) / Customer ROI
    pct_benefits = npv_customer_bill_savings + utility_incentive
    pct_costs = gross_measure_cost
    pct_ratio = pct_benefits / pct_costs if pct_costs > 0 else 0.0
    pct_npv = pct_benefits - pct_costs

    # 3. Rate Impact Measure (RIM) Test (includes program costs)
    rim_costs = npv_lost_revenue + total_program_cost
    rim_ratio = npv_grid_savings / rim_costs if rim_costs > 0 else 0.0
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
    Calculate the annual Gross Economic Carrying Cost and Net Avoided Capacity
    cost for the Next Planned Combustion Turbine (SCCT).

    Parameters
    ----------
    capex_kw : float
        Overnight capital cost in $/kW.
    fom_kw_yr : float
        Fixed O&M in $/kW-yr.
    fcr : float
        Fixed charge rate as a decimal (e.g. 0.084).
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

def calculate_southeast_dual_peak_cwf(datetime_series=None, winter_weight=0.5, summer_weight=0.5,
                                      load_array=None, n_hours=8760):
    """
    Generate an 8,760-hour Capacity Worth Factor (CWF) array allocating annual
    capacity risk across Southeast dual-peak stress windows:
      - Winter Morning Freeze: 6:00 AM – 9:00 AM, Dec 1 – Feb 28/29
      - Summer Afternoon Heat: 2:00 PM – 6:00 PM, Jun 1 – Sep 30

    Parameters
    ----------
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps. If None, assumes standard non-leap year starting Jan 1 00:00.
    winter_weight : float
        Fraction of annual capacity value assigned to winter morning peaks (default 0.50).
    summer_weight : float
        Fraction of annual capacity value assigned to summer afternoon peaks (default 0.50).
    load_array : np.ndarray, optional
        Hourly system or building load array. If provided, weights within each
        season are allocated by exceedance over that window's 80th percentile.
        If None, weights within each window are uniform.
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
        norm_winter, norm_summer = 0.5, 0.5

    # Allocate winter weights
    if is_winter.sum() > 0:
        if load_array is not None and len(load_array) == n_hours:
            w_loads = load_array[is_winter]
            threshold = np.percentile(w_loads, 80)
            exceed = np.maximum(0.0, w_loads - threshold)
            if exceed.sum() > 0:
                cwf[is_winter] = (exceed / exceed.sum()) * norm_winter
            else:
                cwf[is_winter] = norm_winter / is_winter.sum()
        else:
            cwf[is_winter] = norm_winter / is_winter.sum()

    # Allocate summer weights
    if is_summer.sum() > 0:
        if load_array is not None and len(load_array) == n_hours:
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


def calculate_cwf_lolp_proxy(signal_array, alpha=12.0):
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
        Risk concentration parameter (default 12.0). Higher alpha concentrates
        more risk exclusively into the highest-signal hours.

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


def calculate_feeder_pcaf_weights(feeder_type="Winter-Peaking Feeder (Southeast Heating / Cold Snap)",
                                  load_array=None, price_array=None, datetime_series=None, top_n=100):
    """
    Compute localized distribution peak weighting factors for feeder T&D deferral.

    Parameters
    ----------
    feeder_type : str
        Type of feeder profile:
        - "Winter-Peaking Feeder (Southeast Heating / Cold Snap)"
        - "Summer-Peaking Feeder (Southeast Cooling)"
        - "Dual-Peaking Feeder (Suburban Mixed 50/50)"
        - "Wholesale Price PCAF (Top 100 Hours)"
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

