"""Reproduces the spot checks in docs/reviews/2026-11-20_methodology_review.md.

Run from anywhere: python docs/reviews/review_spotcheck.py > spotcheck_results.json
"""
import os, sys, json, glob
import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(REPO)
sys.path.insert(0, REPO)

import config as C
from data_loaders import (load_load_profiles_from_csv, load_and_aggregate_data,
                          load_cambium_milestones, load_cambium_net_demand_stress_weights)
from calculations import (calculate_feeder_pcaf_weights, calculate_avoided_costs,
                          interpolate_cambium_milestone_8760, calculate_multi_year_avoided_costs_and_npv,
                          build_reproducible_npv_bridge)
from billing import calculate_urdb_bill, GP_R31_URDB, AL_FD_URDB, DAKOTA_BLENDED_TOU_URDB
from serc_capacity_cost import SERCCapacityModel, get_nrel_atb_ct_capital_cost_index, get_nrel_atb_ct_fom_index

WEATHER = "2012 (Cambium-aligned baseline)"
MILESTONES = ["2025", "2030", "2035", "2040", "2045"]
START, LIFE, DISC, INFL = 2026, 15, 7.0, 2.2

out = {}

def run_case(ex, state, tariff_json, winter_pct, tz_offset, cap_base=129.76, tag=""):
    lp = load_load_profiles_from_csv(ex["load_profiles_path"])
    base = lp[ex["baseline_col"]].to_numpy(dtype=float)
    prop = lp[ex["proposed_col"]].to_numpy(dtype=float)
    red = base - prop
    raw, _ = load_and_aggregate_data([state], "MidCase", WEATHER, target_year="2012", planning_year="2030")
    dts = raw["Datetime"]
    stress = load_cambium_net_demand_stress_weights([state], "MidCase", "2030", custom_tz=tz_offset,
                                                    seasonal_split=True, winter_weight=winter_pct/100,
                                                    summer_weight=1-winter_pct/100, aggregation_level="state",
                                                    top_n_peak_hours=100, scarcity_price_weight=0.5)
    assert stress["is_qualified"], stress.get("warning")
    cwf = stress["cwft_array"]
    price = raw["Cambium_Energy_MWh"].to_numpy()
    distw = calculate_feeder_pcaf_weights("System Coincident (Top 100 Peak Hours)", base, price, dts, 100)
    pcaf = raw["PCAF_Weight"].to_numpy()
    cap_value = round(cap_base * 1.022 ** (START - 2024), 2)
    bb, _ = calculate_urdb_bill(base, dts, tariff_json)
    bp, _ = calculate_urdb_bill(prop, dts, tariff_json)
    lost_rev = bb - bp

    mdfs, _ = load_cambium_milestones([state], "MidCase", MILESTONES, WEATHER, target_year="2012")
    yrs = [START + t for t in range(LIFE)]
    ie = interpolate_cambium_milestone_8760({y: d["Cambium_Energy_MWh"].to_numpy() for y, d in mdfs.items()}, yrs)
    ic = interpolate_cambium_milestone_8760({y: d["Cambium_Carbon_kg_MWh"].to_numpy() for y, d in mdfs.items()}, yrs)
    proj = SERCCapacityModel().get_projection(start_year=START, end_year=START+LIFE-1, utility="SERC Weighted Composite",
                                             currency="real", capacity_escalation_adder=0.0, base_cost_override=cap_value)
    sched = dict(zip(proj["year"], proj["gross_ecc_per_kw_yr"]))
    common = dict(asset_life=LIFE, start_year=START, interpolated_energy_prices=ie, load_reduction=red,
                  cwft_array=cwf, pcaf_array=pcaf, cap_value=cap_value, trans_value=14.0, dist_value=22.0,
                  carbon_tax=0.0, discount_rate=DISC, customer_discount_rate=DISC, degradation_rate=1.0,
                  annual_lost_revenue_yr1=lost_rev, retail_escalation_rate=2.0, gross_measure_cost=3000.0,
                  utility_incentive=500.0, utility_admin_cost=100.0, capacity_escalation_rate=1.0,
                  interpolated_carbon_emissions=ic, dist_weight_array=distw, valuation_basis="real",
                  base_dollar_year=2023, target_dollar_year=START, inflation_rate=INFL,
                  discount_rate_basis="nominal", discount_timing="mid_year", capacity_cost_schedule=sched)
    fc = calculate_multi_year_avoided_costs_and_npv(financial_method="financially_consistent", **common)
    cur = calculate_multi_year_avoided_costs_and_npv(financial_method="current", **common)
    bridge = build_reproducible_npv_bridge(cur, fc, scenario_sensitivities={})
    return dict(base=base, prop=prop, red=red, raw=raw, dts=dts, cwf=cwf, price=price, distw=distw, pcaf=pcaf,
                cap_value=cap_value, lost_rev=lost_rev, bills=(bb, bp), ie=ie, ic=ic, sched=sched, fc=fc, cur=cur,
                bridge=bridge, mdfs=mdfs, common=common)


def independent_npv(r, ex_state_files_2030):
    """Hand recomputation of the financially-consistent real/mid-year NPV from first principles."""
    red = r["red"]; cwf = r["cwf"]; pcaf = r["pcaf"]; distw = r["distw"]
    rr = 1.07 / 1.022 - 1.0
    to26 = 1.022 ** 3
    r_td = 1.01 / 1.022 - 1.0
    r_ret = 1.02 / 1.022 - 1.0
    grid = 0.0; lost = 0.0
    for t in range(1, LIFE + 1):
        cy = START + t - 1
        deg = 0.99 ** (t - 1)
        df = 1.0 / (1 + rr) ** (t - 0.5)
        e = np.sum(red / 1000 * deg * r["ie"][cy] * to26)
        g = np.sum(red * deg * cwf) * r["sched"][cy]
        tr = np.sum(red * deg * pcaf) * 14.0 * (1 + r_td) ** (t - 1)
        di = np.sum(red * deg * distw) * 22.0 * (1 + r_td) ** (t - 1)
        grid += (e + g + tr + di) * df
        lost += r["lost_rev"] * (1 + r_ret) ** (t - 1) * deg * df
    net = grid - lost - 600.0
    return dict(npv_grid=grid, npv_lost=lost, npv_net=net, trc=grid / (3000 + 100), rim=grid / (lost + 600))


def raw_price_check(state, year="2030"):
    files = []
    for f in glob.glob("Cambium_Hourly_Data_raw/Cambium24_MidCase_hourly_p*_%s.csv" % year):
        meta = pd.read_csv(f, nrows=1)
        if str(meta["state"].iloc[0]).upper() == state:
            files.append(f)
    dfs = [pd.read_csv(f, header=5) for f in sorted(files)]
    price = np.mean([d["energy_cost_enduse"].to_numpy() for d in dfs], axis=0)
    cols = {c: np.mean([d[c].to_numpy() for d in dfs], axis=0) for c in
            ["aer_gen_co2_c", "aer_load_co2e", "lrmer_co2e", "lrmer_co2_c", "srmer_co2e", "srmer_co2_c"]}
    return sorted(files), price, cols


def summarize(name, r, raw_files, raw_price, emis):
    red = r["red"]
    s = {}
    s["raw_files_used_for_state"] = [os.path.basename(f) for f in raw_files]
    s["price_match_max_abs_diff"] = float(np.max(np.abs(raw_price - r["price"])))
    s["annual_kwh_reduction"] = float(red.sum())
    s["max_kw_reduction"] = float(red.max())
    s["min_kw_reduction"] = float(red.min())
    s["cap_value_yr1"] = r["cap_value"]
    s["coincident_kw_EST_weights"] = float(np.sum(red * r["cwf"]))
    s["bills_base_prop"] = [round(x, 2) for x in r["bills"]]
    s["lost_revenue_yr1"] = r["lost_rev"]
    fc = r["fc"]
    s["engine_npv_grid"] = fc["npv_grid_savings"]
    s["engine_npv_lost_rev"] = fc["npv_retail_lost_revenue"]
    s["engine_npv_net"] = fc["npv_net_savings"]
    s["engine_TRC"] = fc["cost_tests"]["trc_ratio"]
    s["engine_RIM"] = fc["cost_tests"]["rim_ratio"]
    s["engine_PCT"] = fc["cost_tests"]["pct_ratio"]
    s["engine_simple_payback"] = fc["cost_tests"]["simple_payback"]
    ind = independent_npv(r, raw_files)
    s["independent"] = ind
    s["npv_net_diff_engine_vs_independent"] = fc["npv_net_savings"] - ind["npv_net"]
    b = r["bridge"]
    s["bridge_final_intermediate_npv"] = float(b["Intermediate_NPV"].iloc[-1])
    s["bridge_vs_actual_gap"] = float(b["Intermediate_NPV"].iloc[-1] - fc["npv_net_savings"])
    s["bridge_steps"] = b[["Description", "Delta_NPV", "Intermediate_NPV"]].round(2).to_dict("records")
    yr1 = fc["cash_flow_df"].iloc[0]
    s["year1_components_engine"] = {k: float(yr1[k]) for k in
                                    ["Wholesale_Energy_Savings", "Gen_Capacity_Savings", "Trans_Capacity_Savings",
                                     "Dist_Capacity_Savings", "Total_Grid_Savings", "Lost_Retail_Revenue"]}
    s["scorecard_annual_basis_energy_2030prices_2023usd"] = float(np.sum(red / 1000 * r["price"]))
    # Emissions metric sensitivity at $30/t (year-1 planning year 2030)
    s["emissions_tons_by_metric_2030"] = {k: float(np.sum(red / 1000 * v) / 1000.0) for k, v in emis.items()}
    s["emissions_value_at_30_by_metric"] = {k: 30.0 * v for k, v in s["emissions_tons_by_metric_2030"].items()}
    out[name] = s
    return s


def tz_and_other_sens(name, ex, state, tariff, alt_tariff, winter_pct):
    r_est = run_case(ex, state, tariff, winter_pct, tz_offset=-5)
    raw_files, raw_price, emis = raw_price_check(state)
    s = summarize(name, r_est, raw_files, raw_price, emis)
    # Correct local-time alignment: let the loader use state metadata (None) and explicit -6
    sens = {}
    if C.STATE_TIMEZONE_METADATA[state]["default_utc_offset"] != -5:
        r_loc = run_case(ex, state, tariff, winter_pct, tz_offset=None)
        sens["tz_local_npv_net"] = r_loc["fc"]["npv_net_savings"]
        sens["tz_local_coincident_kw"] = float(np.sum(r_loc["red"] * r_loc["cwf"]))
        sens["tz_local_yr1_gen_cap"] = float(r_loc["fc"]["cash_flow_df"]["Gen_Capacity_Savings"].iloc[0])
        sens["tz_est_yr1_gen_cap"] = float(r_est["fc"]["cash_flow_df"]["Gen_Capacity_Savings"].iloc[0])
        sens["tz_delta_npv_net"] = r_loc["fc"]["npv_net_savings"] - r_est["fc"]["npv_net_savings"]
        # where do weights peak by local hour-of-day (winter)?
        hrs = pd.to_datetime(r_est["dts"]).dt.hour.to_numpy()
        mo = pd.to_datetime(r_est["dts"]).dt.month.to_numpy()
        wmask = np.isin(mo, [12, 1, 2])
        sens["winter_cwf_by_hour_EST_aligned"] = {int(h): round(float(r_est["cwf"][wmask & (hrs == h)].sum()), 4) for h in range(4, 11)}
        sens["winter_cwf_by_hour_local_aligned"] = {int(h): round(float(r_loc["cwf"][wmask & (hrs == h)].sum()), 4) for h in range(4, 11)}
    if alt_tariff is not None:
        bb, _ = calculate_urdb_bill(r_est["base"], r_est["dts"], alt_tariff)
        bp, _ = calculate_urdb_bill(r_est["prop"], r_est["dts"], alt_tariff)
        sens["alt_tariff_name"] = alt_tariff["name"]
        sens["alt_tariff_lost_rev_yr1"] = bb - bp
        c2 = dict(r_est["common"]); c2["annual_lost_revenue_yr1"] = bb - bp
        fc2 = calculate_multi_year_avoided_costs_and_npv(financial_method="financially_consistent", **c2)
        sens["alt_tariff_npv_net"] = fc2["npv_net_savings"]
        sens["alt_tariff_RIM"] = fc2["cost_tests"]["rim_ratio"]
        sens["alt_tariff_PCT"] = fc2["cost_tests"]["pct_ratio"]
        sens["alt_tariff_payback"] = fc2["cost_tests"]["simple_payback"]
    # T&D escalation: intended +1.0% real vs implemented 1.0% nominal (-1.17% real)
    c3 = dict(r_est["common"]); c3["td_escalation_rate"] = (1.01 * 1.022 - 1) * 100
    fc3 = calculate_multi_year_avoided_costs_and_npv(financial_method="financially_consistent", **c3)
    sens["td_1pct_real_npv_net"] = fc3["npv_net_savings"]
    sens["td_delta_npv_net"] = fc3["npv_net_savings"] - r_est["fc"]["npv_net_savings"]
    # Reserve margin + loss gross-up on gen capacity (illustrative PRM 15% / 26%, loss 6%)
    for prm in (0.15, 0.26):
        c4 = dict(r_est["common"])
        mult = (1 + prm) * 1.06
        c4["capacity_cost_schedule"] = {k: v * mult for k, v in r_est["sched"].items()}
        fc4 = calculate_multi_year_avoided_costs_and_npv(financial_method="financially_consistent", **c4)
        sens[f"prm{int(prm*100)}_loss6_npv_net"] = fc4["npv_net_savings"]
        sens[f"prm{int(prm*100)}_loss6_delta"] = fc4["npv_net_savings"] - r_est["fc"]["npv_net_savings"]
    # Capacity value at a more current CT cost (illustrative $2,000/kW, same FCR/FOM as composite)
    hi = (2000 * 0.097 + 25.0) * 1.022 ** (START - 2024)
    c5 = dict(r_est["common"])
    ratio = hi / r_est["cap_value"]
    c5["capacity_cost_schedule"] = {k: v * ratio for k, v in r_est["sched"].items()}
    fc5 = calculate_multi_year_avoided_costs_and_npv(financial_method="financially_consistent", **c5)
    sens["ct2000_cap_value_yr1"] = hi
    sens["ct2000_npv_net"] = fc5["npv_net_savings"]
    sens["ct2000_delta"] = fc5["npv_net_savings"] - r_est["fc"]["npv_net_savings"]
    # Winter split sensitivity
    for wp in (50.0, 65.0, 95.0):
        if wp == winter_pct:
            continue
        rw = run_case(ex, state, tariff, wp, tz_offset=-5)
        sens[f"winter{int(wp)}_npv_net"] = rw["fc"]["npv_net_savings"]
    out[name]["sensitivities"] = sens


ex_bham = C.EXAMPLE_BUILDINGS[0]
tz_and_other_sens("Birmingham ER->HP (default tariff=GP R-31)", ex_bham, "AL", GP_R31_URDB, AL_FD_URDB, 80.0)

ex_mn = next(e for e in C.EXAMPLE_BUILDINGS if e["baseline_col"].endswith("50_40"))
tz_and_other_sens("Minneapolis ETS 50/40", ex_mn, "MN", DAKOTA_BLENDED_TOU_URDB, None, 90.0)

def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, np.integer)):
        return float(o)
    if isinstance(o, float):
        return round(o, 4)
    return o

print(json.dumps(clean(out), indent=1))
