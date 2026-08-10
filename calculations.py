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


def calculate_avoided_costs(df, cap_value, trans_value, dist_value, carbon_tax, cwft_array):
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

    Returns
    -------
    pd.DataFrame
        Copy of input with additional columns:
        - CWFT: the capacity weights applied
        - Gen_Capacity_Value_MWh: cap_value × CWFT × 1000
        - Trans_Value_MWh: trans_value × PCAF_Weight × 1000
        - Dist_Value_MWh: dist_value × PCAF_Weight × 1000
        - Emissions_Value_MWh: (carbon_kg / 1000) × carbon_tax
        - Total_Avoided_Cost_MWh: sum of energy + all four components
    """
    regional_base = df.copy()
    regional_base['CWFT'] = cwft_array

    # --- Component 1: Generation Capacity (CWFT-weighted) ---
    # Spreads annual $/kW-yr value across hours proportional to capacity risk.
    # Multiply by 1000 to convert $/kW to $/MW (since energy prices are in $/MWh).
    regional_base['Gen_Capacity_Value_MWh'] = cap_value * regional_base['CWFT'] * 1000

    # --- Component 2 & 3: Transmission & Distribution (PCAF-weighted) ---
    # Uses Peak Capacity Allocation Factor (top 100 highest-price hours).
    # These hours represent when the grid is most stressed → T&D investment
    # is most likely to be deferred by demand reduction during these hours.
    regional_base['Trans_Value_MWh'] = trans_value * regional_base['PCAF_Weight'] * 1000
    regional_base['Dist_Value_MWh'] = dist_value * regional_base['PCAF_Weight'] * 1000

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
