"""
billing.py — URDB-Compliant Retail Billing Engine & Pre-Packaged Tariffs
========================================================================

This module handles everything related to retail electricity billing:

    1. PRE-PACKAGED TARIFF SCHEDULES
       Ready-to-use URDB JSON structures for Southeast utilities:
       • Georgia Power Schedule R-31 (residential, tiered summer)
       • Alabama Power Rate FD (family dwelling, tiered winter & summer)

       These are dictionaries formatted to match the NREL Utility Rate Database
       (URDB) V3 JSON schema, which uses weekday/weekend hour-of-day schedules
       to map each hour into a "period", then applies tiered rate structures
       within each period.

    2. BILLING CALCULATION ENGINE
       calculate_urdb_bill() takes an 8,760-hour load profile and a URDB JSON
       rate structure, and computes the annual electricity bill broken down by:
       • Fixed monthly charges
       • Energy charges (tiered, with weekday/weekend period mapping)
       • Demand charges (tiered, with weekday/weekend period mapping)

WHY IT'S SEPARATE:
    Billing logic is complex (tiered rates, seasonal schedules, demand charges)
    and entirely independent of the avoided cost calculations. Keeping it in
    its own module means:
    • Tariff data can be updated without touching the calculation engine
    • New utilities/tariffs can be added by just adding a new dict
    • The billing engine can be tested independently (see tests/test_calculations.py)

USED BY:
    app.py imports the tariff constants (GP_R31_URDB, AL_FD_URDB) for the
    tariff selector dropdown, and calls calculate_urdb_bill() to compute
    retail bills for baseline and proposed load profiles. The difference
    between those two bills = "lost revenue" for the RIM test.

TESTED BY:
    tests/test_calculations.py::TestCalculateUrdbBill (6 tests)
"""

import numpy as np


# ==============================================================================
# PRE-PACKAGED TARIFF SCHEDULES (URDB V3 JSON FORMAT)
# ==============================================================================
#
# Each tariff is a dict matching the NREL URDB schema:
#   fixedcharge:           Monthly fixed charge ($)
#   energyratewindow:      12×24 matrix mapping (month, hour) → period index
#     OR energyweekdayschedule + energyweekendschedule for weekday/weekend split
#   energyratestructure:   List of period tiers: [{max, rate, adj}, ...]
#   demandratewindow:      Same structure for demand charges (optional)
#   demandratestructure:   Same structure for demand charges (optional)
#
# Period index 0 = Winter, 1 = Summer (for these Southeast residential tariffs)
# ==============================================================================

GP_R31_URDB = {
    "name": "Georgia Power - Schedule R-31 (Residential)",
    "fixedcharge": 16.48,  # includes riders: $14.00/mo base × 1.177209 rider multiplier
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24,  # Jan–May  (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,           # Jun–Sep  (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                    # Oct–Dec  (Winter = Period 0)
    ],
    "energyratestructure": [
        # Period 0 — Winter: flat rate
        [{"rate": 0.142062}],  # (8.2116¢ base + 3.8561¢ FCR) × 1.177209 riders
        # Period 1 — Summer: three-tier increasing block
        [
            {"max": 650.0, "rate": 0.148101},  # Tier 1: first 650 kWh (8.7738¢ base + 3.8069¢ FCR) × riders
            {"max": 350.0, "rate": 0.216379},  # Tier 2: next 350 kWh (14.5738¢ base + 3.8069¢ FCR) × riders
            {"rate": 0.222371}                  # Tier 3: all remaining (15.0828¢ base + 3.8069¢ FCR) × riders
        ]
    ]
}

AL_FD_URDB = {
    "name": "Alabama Power - Rate FD (Family Dwelling)",
    "fixedcharge": 15.58,  # $14.50/mo base + $1.08/mo NDR (averaging $13.00/yr)
    "energyratewindow": [
        [0]*24, [0]*24, [0]*24, [0]*24, [0]*24,  # Jan–May  (Winter = Period 0)
        [1]*24, [1]*24, [1]*24, [1]*24,           # Jun–Sep  (Summer = Period 1)
        [0]*24, [0]*24, [0]*24                    # Oct–Dec  (Winter = Period 0)
    ],
    "energyratestructure": [
        # Period 0 — Winter: two-tier decreasing block
        [
            {"max": 750.0, "rate": 0.150384},  # Tier 1 (12.4384¢ base + 2.600¢ ECR)
            {"rate": 0.138384}                  # Tier 2 (11.2384¢ base + 2.600¢ ECR)
        ],
        # Period 1 — Summer: two-tier
        [
            {"max": 1000.0, "rate": 0.150384},  # Tier 1 (12.4384¢ base + 2.600¢ ECR)
            {"rate": 0.152913}                   # Tier 2 (12.6913¢ base + 2.600¢ ECR)
        ]
    ]
}


# ==============================================================================
# BILLING CALCULATION ENGINE
# ==============================================================================

def calculate_urdb_bill(load_kw, datetime_series, rate_json):
    """
    Compute an annual electricity bill from an 8,760-hour load profile
    using a URDB-format rate structure.

    This engine supports:
    • Fixed monthly charges
    • Time-of-use energy rates with weekday/weekend schedules (URDB V3)
    • Tiered (increasing block) energy rates within each period
    • Demand charges with weekday/weekend schedules and tiers

    Parameters
    ----------
    load_kw : np.ndarray
        8,760-element array of hourly load in kW.
    datetime_series : pd.Series
        8,760-element datetime series (must have .dt accessor for
        month, hour, dayofweek extraction).
    rate_json : dict
        URDB-format rate structure. See GP_R31_URDB above for an example.

    Returns
    -------
    total_bill : float
        Annual total bill ($).
    monthly_bills : np.ndarray
        12-element array of monthly bill amounts ($).
    """
    fixed_charge_monthly = rate_json.get("fixedcharge", 0.0)

    # Energy schedule: weekday/weekend or single schedule
    energy_wd = rate_json.get("energyweekdayschedule", rate_json.get("energyratewindow"))
    energy_we = rate_json.get("energyweekendschedule", rate_json.get("energyratewindow"))
    energy_structure = rate_json.get("energyratestructure")

    # Demand schedule: weekday/weekend or single schedule
    demand_wd = rate_json.get("demandweekdayschedule", rate_json.get("demandratewindow"))
    demand_we = rate_json.get("demandweekendschedule", rate_json.get("demandratewindow"))
    demand_structure = rate_json.get("demandratestructure")

    months = datetime_series.dt.month.to_numpy()
    hours = datetime_series.dt.hour.to_numpy()
    dayofweek = datetime_series.dt.dayofweek.to_numpy()  # 0=Mon, 6=Sun

    total_bill = 0.0
    monthly_bills = []

    for m in range(1, 13):
        mask = months == m
        if not mask.any():
            continue

        m_load = load_kw[mask]
        m_hours = hours[mask]
        m_dow = dayofweek[mask]

        # 1. Fixed monthly charge
        m_bill = fixed_charge_monthly

        # 2. Energy charge (tiered, with period mapping)
        if energy_structure is not None and energy_wd is not None and energy_we is not None:
            period_usage = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = energy_we[m - 1][hr] if dow >= 5 else energy_wd[m - 1][hr]
                period_usage[period_idx] = period_usage.get(period_idx, 0.0) + kw

            for period_idx, kwh in period_usage.items():
                if period_idx < len(energy_structure):
                    tiers = energy_structure[period_idx]
                    remaining_kwh = kwh
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)

                        kwh_in_tier = min(remaining_kwh, tier_max)
                        tier_charge += kwh_in_tier * tier_rate
                        remaining_kwh -= kwh_in_tier
                        if remaining_kwh <= 0:
                            break
                    m_bill += tier_charge

        # 3. Demand charge (tiered, with period mapping)
        if demand_structure is not None and demand_wd is not None and demand_we is not None:
            period_peaks = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = demand_we[m - 1][hr] if dow >= 5 else demand_wd[m - 1][hr]
                period_peaks[period_idx] = max(period_peaks.get(period_idx, 0.0), kw)

            for period_idx, peak_kw in period_peaks.items():
                if period_idx < len(demand_structure):
                    tiers = demand_structure[period_idx]
                    remaining_kw = peak_kw
                    tier_charge = 0.0
                    for tier in tiers:
                        tier_max = tier.get("max", float("inf"))
                        tier_rate = tier.get("rate", 0.0) + tier.get("adj", 0.0)

                        kw_in_tier = min(remaining_kw, tier_max)
                        tier_charge += kw_in_tier * tier_rate
                        remaining_kw -= kw_in_tier
                        if remaining_kw <= 0:
                            break
                    m_bill += tier_charge

        total_bill += m_bill
        monthly_bills.append(m_bill)

    return total_bill, np.array(monthly_bills)


def get_hourly_energy_rate(datetime_series, rate_json):
    """
    Return the marginal (first-tier) retail energy rate ($/kWh) for every
    hour in datetime_series, based on a URDB-format rate structure's
    weekday/weekend period mapping.

    NOTE: This is a simplified diagnostic helper intended for hourly charts
    (e.g. weekly customer operating cost visualizations). It ignores
    monthly cumulative-usage tiering — which requires full-month billing
    context — and always returns the first tier's rate for the hour's
    mapped period. For actual bill totals, use calculate_urdb_bill().

    Parameters
    ----------
    datetime_series : pd.Series
        Datetime series (must have .dt accessor for month/hour/dayofweek).
    rate_json : dict
        URDB-format rate structure (see GP_R31_URDB for an example).

    Returns
    -------
    np.ndarray
        Hourly marginal energy rate ($/kWh), same length as datetime_series.
        Returns all zeros if the rate structure has no energy schedule.
    """
    energy_wd = rate_json.get("energyweekdayschedule", rate_json.get("energyratewindow"))
    energy_we = rate_json.get("energyweekendschedule", rate_json.get("energyratewindow"))
    energy_structure = rate_json.get("energyratestructure")

    n = len(datetime_series)
    rates = np.zeros(n)

    if energy_structure is None or energy_wd is None or energy_we is None:
        return rates

    months = datetime_series.dt.month.to_numpy()
    hours = datetime_series.dt.hour.to_numpy()
    dayofweek = datetime_series.dt.dayofweek.to_numpy()

    for i in range(n):
        m = months[i] - 1
        hr = hours[i]
        period_idx = energy_we[m][hr] if dayofweek[i] >= 5 else energy_wd[m][hr]
        if period_idx < len(energy_structure) and energy_structure[period_idx]:
            first_tier = energy_structure[period_idx][0]
            rates[i] = first_tier.get("rate", 0.0) + first_tier.get("adj", 0.0)

    return rates
