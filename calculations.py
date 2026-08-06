"""
calculations.py — Grid Avoided Cost Calculation Engine
=======================================================

This module contains the core hourly avoided cost calculation that forms
the backbone of the Southeast Marginal Cost Valuation Engine.

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
