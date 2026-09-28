"""
billing.py — URDB-Compliant Retail Billing Engine & Pre-Packaged Tariffs
========================================================================

This module handles everything related to retail electricity billing:

    1. PRE-PACKAGED TARIFF SCHEDULES
       Ready-to-use URDB JSON structures for Southeast utilities:
       • Georgia Power Schedule R-31 (residential, tiered summer)
       • Alabama Power Rate FD (family dwelling, tiered winter & summer)
       • Alabama Power Rate FD-D (family dwelling demand, seasonal peak demand)
       • Alabama Power Rate RTA (residential time advantage, TOU energy + flat monthly demand)
       • Alabama Power Rate RTA-E (residential time advantage, energy-only TOU)

       These are dictionaries formatted to match the NREL Utility Rate Database
       (URDB) V3 JSON schema, which uses weekday/weekend hour-of-day schedules
       to map each hour into a "period", then applies tiered rate structures
       within each period.

    2. BILLING CALCULATION ENGINE
       calculate_urdb_bill() takes an 8,760-hour load profile and a URDB JSON
       rate structure, and computes the annual electricity bill broken down by:
       • Fixed monthly charges
       • Energy charges (tiered, with weekday/weekend period mapping)
       • Demand charges (tiered, with weekday/weekend period mapping & optional ratchets)

WHY IT'S SEPARATE:
    Billing logic is complex (tiered rates, seasonal schedules, demand charges)
    and entirely independent of the avoided cost calculations. Keeping it in
    its own module means:
    • Tariff data can be updated without touching the calculation engine
    • New utilities/tariffs can be added by just adding a new dict
    • The billing engine can be tested independently (see tests/test_calculations.py)

USED BY:
    app.py imports the tariff constants (GP_R31_URDB, AL_FD_URDB, AL_FDD_URDB,
    AL_RTA_URDB, AL_RTA_E_URDB) for the tariff selector dropdown, and calls
    calculate_urdb_bill() to compute retail bills for baseline and proposed
    load profiles. The difference between those two bills = "lost revenue"
    for the RIM test.

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
#   demandweekdayschedule: Weekday matrix for demand period index (optional)
#   demandweekendschedule: Weekend matrix for demand period index (optional)
#   demandratestructure:   List of period tiers for demand charges (optional)
#   demandratchetpercentage: Decimal ratchet percentage for lookback capacity (optional)
#
# Period index 0 = Winter/Economy, 1 = Summer/Peak, etc.
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

# ------------------------------------------------------------------------------
# Alabama Power — Rate FD-D: Family Dwelling Demand (Residential Service Demand)
# ------------------------------------------------------------------------------
# Base Charge: $14.50/mo + $1.08/mo NDR = $15.58/mo
# Energy Charge: 7.9607¢ base + 2.600¢ ECR = 10.5607¢/kWh ($0.105607/kWh) all hours
# Demand Charge: $8.00 per kW of Billing Capacity measured during Peak Periods:
#   - Apr 1 – Oct 31 (Months 4–10): Weekdays 1:00 PM – 5:00 PM (hours 13, 14, 15, 16)
#   - Nov 1 – Mar 31 (Months 11, 12, 1, 2, 3): Weekdays 6:00 AM – 9:00 AM (hours 6, 7, 8)
#   - Weekends & holidays: Off-peak (Period 0)
# Ratchet: Billing capacity is greater of monthly peak period kW or 90% of highest
#          peak period kW established during preceding 11 months.
# ------------------------------------------------------------------------------
_FDD_DEMAND_WD = [
    # Jan–Mar: 6 AM – 9 AM (hours 6, 7, 8) = Period 1 (Peak)
    [0]*6 + [1]*3 + [0]*15,
    [0]*6 + [1]*3 + [0]*15,
    [0]*6 + [1]*3 + [0]*15,
    # Apr–Oct: 1 PM – 5 PM (hours 13, 14, 15, 16) = Period 1 (Peak)
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    [0]*13 + [1]*4 + [0]*7,
    # Nov–Dec: 6 AM – 9 AM (hours 6, 7, 8) = Period 1 (Peak)
    [0]*6 + [1]*3 + [0]*15,
    [0]*6 + [1]*3 + [0]*15,
]
_FDD_DEMAND_WE = [[0]*24 for _ in range(12)]

AL_FDD_URDB = {
    "name": "Alabama Power - Rate FD-D (Family Dwelling Demand)",
    "fixedcharge": 15.58,  # $14.50/mo base + $1.08/mo NDR
    "energyratewindow": [[0]*24 for _ in range(12)],
    "energyratestructure": [
        [{"rate": 0.105607}]  # 7.9607¢ base + 2.600¢ ECR
    ],
    "demandweekdayschedule": _FDD_DEMAND_WD,
    "demandweekendschedule": _FDD_DEMAND_WE,
    "demandratestructure": [
        [{"rate": 0.0}],   # Period 0 — Off-Peak: $0.00/kW
        [{"rate": 8.00}],  # Period 1 — Peak Period: $8.00/kW of Billing Capacity
    ],
    "demandratchetpercentage": 0.90,  # 90% peak period lookback ratchet
}

# ------------------------------------------------------------------------------
# Alabama Power — Rate RTA: Residential Time Advantage (Demand)
# ------------------------------------------------------------------------------
# Base Charge: $14.50/mo + $1.08/mo NDR = $15.58/mo
# Demand Charge: $1.50 per kW of monthly maximum integrated demand (all hours)
# Energy Charge (TOU):
#   - Jun 1 – Sep 30: Weekdays 1 PM – 7 PM (Summer Peak, Period 1) = 25.6092¢ + 2.600¢ = $0.282092/kWh
#   - Nov 1 – Mar 31: Weekdays 5 AM – 9 AM (Winter Peak, Period 2) = 12.6092¢ + 2.600¢ = $0.152092/kWh
#   - All other hours (Economy & Apr, May, Oct shoulder, Period 0) = 10.6092¢ + 2.600¢ = $0.132092/kWh
# ------------------------------------------------------------------------------
_RTA_ENERGY_WD = [
    # Jan–Mar (Winter): 5 AM – 9 AM (hours 5, 6, 7, 8) = Period 2 (Winter Peak)
    [0]*5 + [2]*4 + [0]*15,
    [0]*5 + [2]*4 + [0]*15,
    [0]*5 + [2]*4 + [0]*15,
    # Apr–May (Shoulder): all hours = Period 0 (Economy)
    [0]*24,
    [0]*24,
    # Jun–Sep (Summer): 1 PM – 7 PM (hours 13, 14, 15, 16, 17, 18) = Period 1 (Summer Peak)
    [0]*13 + [1]*6 + [0]*5,
    [0]*13 + [1]*6 + [0]*5,
    [0]*13 + [1]*6 + [0]*5,
    [0]*13 + [1]*6 + [0]*5,
    # Oct (Shoulder): all hours = Period 0 (Economy)
    [0]*24,
    # Nov–Dec (Winter): 5 AM – 9 AM (hours 5, 6, 7, 8) = Period 2 (Winter Peak)
    [0]*5 + [2]*4 + [0]*15,
    [0]*5 + [2]*4 + [0]*15,
]
_RTA_ENERGY_WE = [[0]*24 for _ in range(12)]

AL_RTA_URDB = {
    "name": "Alabama Power - Rate RTA (Residential Time Advantage - Demand)",
    "fixedcharge": 15.58,  # $14.50/mo base + $1.08/mo NDR
    "energyweekdayschedule": _RTA_ENERGY_WD,
    "energyweekendschedule": _RTA_ENERGY_WE,
    "energyratestructure": [
        # Period 0 — Economy / Shoulder (all non-peak hours)
        [{"rate": 0.132092}],  # 10.6092¢ base + 2.600¢ ECR
        # Period 1 — Summer Peak (Jun–Sep weekdays 1 PM – 7 PM)
        [{"rate": 0.282092}],  # 25.6092¢ base + 2.600¢ ECR
        # Period 2 — Winter Peak (Nov–Mar weekdays 5 AM – 9 AM)
        [{"rate": 0.152092}],  # 12.6092¢ base + 2.600¢ ECR
    ],
    "demandratewindow": [[0]*24 for _ in range(12)],
    "demandratestructure": [
        [{"rate": 1.50}],  # $1.50/kW monthly maximum demand (all hours)
    ],
}

# ------------------------------------------------------------------------------
# Alabama Power — Rate RTA-E: Residential Time Advantage (Energy Only)
# ------------------------------------------------------------------------------
# Base Charge: $25.00/mo + $1.08/mo NDR = $26.08/mo
# Demand Charge: None
# Energy Charge (TOU):
#   - Jun 1 – Sep 30: Weekdays 1 PM – 7 PM (Summer Peak, Period 1) = 30.2554¢ + 2.600¢ = $0.328554/kWh
#   - Nov 1 – Mar 31: Weekdays 5 AM – 9 AM (Winter Peak, Period 2) = 12.2554¢ + 2.600¢ = $0.148554/kWh
#   - All other hours (Economy & Apr, May, Oct shoulder, Period 0) = 10.2554¢ + 2.600¢ = $0.128554/kWh
# ------------------------------------------------------------------------------
AL_RTA_E_URDB = {
    "name": "Alabama Power - Rate RTA-E (Residential Time Advantage - Energy Only)",
    "fixedcharge": 26.08,  # $25.00/mo base + $1.08/mo NDR
    "energyweekdayschedule": _RTA_ENERGY_WD,
    "energyweekendschedule": _RTA_ENERGY_WE,
    "energyratestructure": [
        # Period 0 — Economy / Shoulder (all non-peak hours)
        [{"rate": 0.128554}],  # 10.2554¢ base + 2.600¢ ECR
        # Period 1 — Summer Peak (Jun–Sep weekdays 1 PM – 7 PM)
        [{"rate": 0.328554}],  # 30.2554¢ base + 2.600¢ ECR
        # Period 2 — Winter Peak (Nov–Mar weekdays 5 AM – 9 AM)
        [{"rate": 0.148554}],  # 12.2554¢ base + 2.600¢ ECR
    ],
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
    ratchet_pct = float(rate_json.get("demandratchetpercentage", rate_json.get("demandlookbackpercentage", 0.0)) or 0.0)

    months = datetime_series.dt.month.to_numpy()
    hours = datetime_series.dt.hour.to_numpy()
    dayofweek = datetime_series.dt.dayofweek.to_numpy()  # 0=Mon, 6=Sun

    # Precalculate monthly demand peaks per period if demand charges apply
    monthly_demand_peaks = {}
    if demand_structure is not None and demand_wd is not None and demand_we is not None:
        for m in range(1, 13):
            mask = months == m
            if not mask.any():
                continue
            m_load = load_kw[mask]
            m_hours = hours[mask]
            m_dow = dayofweek[mask]
            p_peaks = {}
            for i, kw in enumerate(m_load):
                hr = m_hours[i]
                dow = m_dow[i]
                period_idx = demand_we[m - 1][hr] if dow >= 5 else demand_wd[m - 1][hr]
                p_peaks[period_idx] = max(p_peaks.get(period_idx, 0.0), kw)
            monthly_demand_peaks[m] = p_peaks

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

        # 3. Demand charge (tiered, with period mapping and optional lookback ratchet)
        if demand_structure is not None and demand_wd is not None and demand_we is not None:
            period_peaks = monthly_demand_peaks.get(m, {})

            for period_idx in range(len(demand_structure)):
                peak_kw = period_peaks.get(period_idx, 0.0)
                if ratchet_pct > 0.0:
                    prior_peaks = [
                        monthly_demand_peaks[other_m].get(period_idx, 0.0)
                        for other_m in monthly_demand_peaks
                        if other_m != m
                    ]
                    ratchet_floor = (ratchet_pct * max(prior_peaks)) if prior_peaks else 0.0
                    billed_kw = max(peak_kw, ratchet_floor)
                else:
                    billed_kw = peak_kw

                if billed_kw <= 0.0:
                    continue

                tiers = demand_structure[period_idx]
                remaining_kw = billed_kw
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
