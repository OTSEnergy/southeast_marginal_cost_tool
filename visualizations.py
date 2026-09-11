"""
visualizations.py — Plotly Chart Builder Functions
====================================================

This module contains functions that build Plotly chart figures for the
Southeast Marginal Cost Valuation Engine dashboard. Each function takes
pre-computed data and returns a ``plotly.graph_objects.Figure`` ready to
be rendered by Streamlit (or any other Plotly-compatible frontend).

WHAT IT DOES:
    Provides reusable chart builders for the dashboard tabs:

    1. build_weekly_overlay_chart()   — Dual-axis weekly load + avoided cost
    2. build_annual_avoided_cost_chart() — Full-year hourly avoided cost series
    3. build_stacked_components_chart()  — Stacked area of 5 cost components
    4. build_lifetime_npv_chart()     — Grouped bar of nominal vs discounted
                                        cash flow streams

WHY IT'S SEPARATE:
    Chart construction is verbose Plotly boilerplate that clutters the main
    app.py orchestration file. Keeping it here means:
    • Each chart can be unit-tested in isolation (returns a Figure, no UI)
    • Chart styling/layout can be updated without scrolling through
      1,000+ lines of Streamlit layout code
    • New charts for future milestones (M2/M3 visualizations) have a
      natural home

USED BY:
    app.py imports these functions and calls them inside tab blocks,
    then renders the returned Figure via st.plotly_chart().

TESTED BY:
    tests/test_calculations.py::TestVisualizations
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import GRID_COMPONENTS, COLORS


def build_weekly_load_and_temp_chart(datetime_slice, baseline_slice, proposed_slice, temp_slice):
    """
    Build a dual-axis chart comparing Baseline vs Proposed load profiles (kW)
    on the left Y-axis with Outdoor Air Temperature (°F) on the right Y-axis.

    Parameters
    ----------
    datetime_slice : pd.Series
        Datetime values for the selected window.
    baseline_slice : np.ndarray
        Baseline load profile (kW).
    proposed_slice : np.ndarray
        Proposed load profile (kW).
    temp_slice : np.ndarray
        Outdoor air temperature (°F).

    Returns
    -------
    go.Figure
        Dual-axis Plotly figure with kW demand on left Y-axis and °F on right Y-axis.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=baseline_slice,
            name="Baseline Load (kW)",
            line=dict(color=COLORS["red"], width=2)
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=proposed_slice,
            name="Proposed Load (kW)",
            line=dict(color=COLORS["teal"], width=2)
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=temp_slice,
            name="Outdoor Air Temp (°F)",
            line=dict(color=COLORS["blue"], width=1.5, dash='dot'),
            opacity=0.85
        ),
        secondary_y=True
    )

    fig.update_layout(
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=40, t=30, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Building Demand (kW)", secondary_y=False)
    fig.update_yaxes(title_text="Outdoor Air Temp (°F)", secondary_y=True)

    return fig


def build_weekly_grid_economics_chart(slice_df, mode="Stacked Components"):
    """
    Build a 4-row subplot figure for weekly grid & customer economics analysis:
    - Row 1: Grid Avoided Cost Economics ($/MWh) — configurable as stacked components,
             individual component lines, or total marginal cost.
    - Row 2: Standalone Load Reduction panel (kW) aligned on the exact same X-axis.
    - Row 3: Hourly Operating Cost Delta ($/hr) — wholesale value created per hour ($/hr).
    - Row 4: Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed bill impact,
             with the applicable retail energy rate ($/kWh) on a secondary Y-axis.

    Parameters
    ----------
    slice_df : pd.DataFrame
        DataFrame slice containing 'Datetime', all grid component columns, 'Load_Reduction_kW',
        and optionally 'Hourly_Savings_hr', 'Customer_Cost_Baseline_hr', 'Customer_Cost_Proposed_hr',
        and 'Retail_Rate_kWh'.
    mode : str
        One of "Stacked Components", "Individual Component Lines", "Total Marginal Cost ($/MWh)".

    Returns
    -------
    go.Figure
        4-row subplot figure with Grid Economics on Row 1, Load Reduction on Row 2,
        Hourly Cost Delta ($/hr) on Row 3, and Customer Retail Operating Cost on Row 4.
    """
    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.055,
        row_heights=[0.34, 0.20, 0.20, 0.26],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": True}]],
        subplot_titles=(
            "Wholesale Grid Avoided Cost Economics ($/MWh)",
            "Standalone Load Reduction (kW)",
            "Hourly Operating Cost Delta ($/hr) — Grid Value Created",
            "Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed"
        )
    )

    # Row 1: Grid Economics
    if mode == "Total Marginal Cost ($/MWh)":
        fig.add_trace(
            go.Scatter(
                x=slice_df['Datetime'], y=slice_df['Total_Avoided_Cost_MWh'],
                mode='lines', name='Total Avoided Cost ($/MWh)',
                line=dict(color=COLORS["purple"], width=2.5)
            ),
            row=1, col=1
        )
    elif mode == "Individual Component Lines":
        for col_name, label, color in GRID_COMPONENTS:
            fig.add_trace(
                go.Scatter(
                    x=slice_df['Datetime'], y=slice_df[col_name],
                    mode='lines', name=label,
                    line=dict(color=color, width=1.8)
                ),
                row=1, col=1
            )
        fig.add_trace(
            go.Scatter(
                x=slice_df['Datetime'], y=slice_df['Total_Avoided_Cost_MWh'],
                mode='lines', name='Total Avoided Cost ($/MWh)',
                line=dict(color=COLORS["purple"], width=2, dash='dash')
            ),
            row=1, col=1
        )
    else:  # Default: "Stacked Components"
        for col_name, label, color in GRID_COMPONENTS:
            fig.add_trace(
                go.Scatter(
                    x=slice_df['Datetime'], y=slice_df[col_name],
                    mode='lines', name=label, stackgroup='one',
                    line=dict(color=color, width=0.5)
                ),
                row=1, col=1
            )

    # Row 2: Standalone Load Reduction Panel
    if 'Load_Reduction_kW' in slice_df.columns:
        reduction_vals = slice_df['Load_Reduction_kW']
    else:
        reduction_vals = np.zeros(len(slice_df))

    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=reduction_vals,
            mode='lines', name='Load Reduction (kW)',
            fill='tozeroy',
            line=dict(color=COLORS["amber"], width=2),
            fillcolor="rgba(245, 158, 11, 0.25)"
        ),
        row=2, col=1
    )

    # Row 3: Hourly Operating Cost Delta ($/hr)
    if 'Hourly_Savings_hr' in slice_df.columns:
        hourly_savings = slice_df['Hourly_Savings_hr']
    else:
        hourly_savings = (reduction_vals / 1000.0) * slice_df['Total_Avoided_Cost_MWh']

    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=hourly_savings,
            mode='lines', name='Grid Value Delta ($/hr)',
            fill='tozeroy',
            line=dict(color=COLORS["green"], width=2),
            fillcolor="rgba(16, 185, 129, 0.25)"
        ),
        row=3, col=1
    )

    # Row 4: Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed,
    # with the applicable retail energy rate ($/kWh) on a secondary Y-axis.
    if 'Customer_Cost_Baseline_hr' in slice_df.columns:
        baseline_cost_vals = slice_df['Customer_Cost_Baseline_hr']
    else:
        baseline_cost_vals = np.zeros(len(slice_df))

    if 'Customer_Cost_Proposed_hr' in slice_df.columns:
        proposed_cost_vals = slice_df['Customer_Cost_Proposed_hr']
    else:
        proposed_cost_vals = np.zeros(len(slice_df))

    if 'Retail_Rate_kWh' in slice_df.columns:
        retail_rate_vals = slice_df['Retail_Rate_kWh']
    else:
        retail_rate_vals = np.zeros(len(slice_df))

    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=baseline_cost_vals,
            mode='lines', name='Customer Cost - Baseline ($/hr)',
            line=dict(color=COLORS["red"], width=2)
        ),
        row=4, col=1, secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=proposed_cost_vals,
            mode='lines', name='Customer Cost - Proposed ($/hr)',
            line=dict(color=COLORS["teal"], width=2)
        ),
        row=4, col=1, secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=retail_rate_vals,
            mode='lines', name='Retail Energy Rate ($/kWh)',
            line=dict(color=COLORS["blue"], width=1.5, dash='dot'),
            opacity=0.85
        ),
        row=4, col=1, secondary_y=True
    )

    fig.update_layout(
        template="plotly_white",
        height=900,
        margin=dict(l=40, r=40, t=30, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Avoided Cost ($/MWh)", row=1, col=1)
    fig.update_yaxes(title_text="Reduction (kW)", row=2, col=1)
    fig.update_yaxes(title_text="Cost Delta ($/hr)", row=3, col=1)
    fig.update_yaxes(title_text="Customer Cost ($/hr)", row=4, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Retail Rate ($/kWh)", row=4, col=1, secondary_y=True)
    fig.update_xaxes(title_text="Date", row=4, col=1)

    return fig


def build_weekly_overlay_chart(datetime_slice, cost_slice, baseline_slice,
                               proposed_slice, reduction_slice):
    """
    Build a dual-axis chart overlaying load profiles with avoided cost rates
    for a selected week window.

    Parameters
    ----------
    datetime_slice : pd.Series
        Datetime values for the week (typically 168 elements).
    cost_slice : pd.Series or np.ndarray
        Total avoided cost rate ($/MWh) for each hour in the window.
    baseline_slice : np.ndarray
        Baseline load profile (kW) for each hour in the window.
    proposed_slice : np.ndarray
        Proposed load profile (kW) for each hour in the window.
    reduction_slice : np.ndarray
        Load reduction (kW) for each hour in the window.

    Returns
    -------
    go.Figure
        Plotly figure with primary y-axis (kW) and secondary y-axis ($/MWh).
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=cost_slice,
            name="Grid Avoided Cost ($/MWh)",
            line=dict(color=COLORS["purple"], width=2, dash='dash')
        ),
        secondary_y=True
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=baseline_slice,
            name="Baseline Load (kW)",
            line=dict(color=COLORS["red"], width=1.5)
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=proposed_slice,
            name="Proposed Load (kW)",
            line=dict(color=COLORS["teal"], width=1.5)
        ),
        secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=reduction_slice,
            name="Load reduction (kW)",
            line=dict(color=COLORS["amber"], width=2)
        ),
        secondary_y=False
    )

    fig.update_layout(
        template="plotly_white",
        height=400,
        margin=dict(l=40, r=40, t=20, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Customer Load / reduction (kW)",
                     secondary_y=False)
    fig.update_yaxes(title_text="Avoided Cost ($/MWh)", secondary_y=True)

    return fig


def build_annual_avoided_cost_chart(results_df):
    """
    Build a full-year hourly avoided cost time series chart.

    Parameters
    ----------
    results_df : pd.DataFrame
        Must contain 'Datetime' and 'Total_Avoided_Cost_MWh' columns.

    Returns
    -------
    go.Figure
        Single-trace line chart of hourly total avoided cost.
    """
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=results_df['Datetime'],
        y=results_df['Total_Avoided_Cost_MWh'],
        mode='lines',
        name='Total avoided cost rate ($/MWh)',
        line=dict(color=COLORS["purple"], width=1.2)
    ))
    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Avoided Cost ($/MWh)",
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=30, t=10, b=40)
    )
    return fig


def build_stacked_components_chart(slice_df, show_legend=True):
    """
    Build a stacked area chart of the 5 avoided cost components for a
    time window (typically a peak week).

    Parameters
    ----------
    slice_df : pd.DataFrame
        Slice of results_df containing 'Datetime' and all component columns.
    show_legend : bool
        Whether to show the chart legend (False for side-by-side pairs).

    Returns
    -------
    go.Figure
        Stacked area chart with one trace per grid cost component.
    """
    fig = go.Figure()
    for col_name, label, color in GRID_COMPONENTS:
        fig.add_trace(go.Scatter(
            x=slice_df['Datetime'], y=slice_df[col_name],
            mode='lines', name=label, stackgroup='one',
            line=dict(color=color, width=0.5),
            showlegend=show_legend
        ))
    fig.update_layout(
        template="plotly_white", height=320,
        margin=dict(l=40, r=20, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1) if show_legend else {}
    )
    return fig


def build_lifetime_npv_chart(years, projected_grid_nominal,
                             projected_grid_disc, projected_lost_disc):
    """
    Build a grouped bar chart comparing nominal grid savings, discounted
    grid NPV, and discounted lost revenue NPV over the asset lifetime.

    Parameters
    ----------
    years : np.ndarray
        Array of operating year numbers (1-indexed).
    projected_grid_nominal : np.ndarray
        Nominal (un-discounted) grid savings per year.
    projected_grid_disc : np.ndarray
        Discounted grid savings per year.
    projected_lost_disc : np.ndarray
        Discounted lost revenue per year.

    Returns
    -------
    go.Figure
        Grouped bar chart with 3 series.
    """
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=projected_grid_nominal,
        name='Nominal Grid savings', marker_color=COLORS["amber"]
    ))
    fig.add_trace(go.Bar(
        x=years, y=projected_grid_disc,
        name='Discounted Grid NPV', marker_color=COLORS["teal"]
    ))
    fig.add_trace(go.Bar(
        x=years, y=projected_lost_disc,
        name='Discounted Lost Revenue NPV', marker_color=COLORS["red"]
    ))

    fig.update_layout(
        title="Nominal vs. Discounted present value streams",
        xaxis_title="Operating Year",
        yaxis_title="Annual value ($)",
        template="plotly_white",
        height=350,
        margin=dict(l=40, r=20, t=30, b=40),
        barmode='group',
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1)
    )
    return fig


def build_temp_power_cost_bubble_chart(temp_vals, baseline_load, proposed_load,
                                        baseline_cost_hr, proposed_cost_hr,
                                        datetime_vals=None, front="Proposed"):
    """
    Build a bubble chart of hourly grid avoided cost ($/hr) vs. Outdoor Air
    Temperature (°F), with bubble size representing hourly Building Demand
    (kW) — so hours with high cost AND high demand stand out as large
    bubbles high on the chart. Both Baseline and Proposed cases are
    plotted; the case NOT selected as `front` is drawn faded in the
    background so the other stands out.

    Parameters
    ----------
    temp_vals : np.ndarray
        Outdoor air temperature (°F) for all 8760 hours.
    baseline_load : np.ndarray
        Baseline hourly load (kW).
    proposed_load : np.ndarray
        Proposed hourly load (kW).
    baseline_cost_hr : np.ndarray
        Hourly grid avoided-cost value ($/hr, actual dollars) of the baseline load.
    proposed_cost_hr : np.ndarray
        Hourly grid avoided-cost value ($/hr, actual dollars) of the proposed load.
    datetime_vals : array-like of datetime, optional
        Timestamp for each hour, used to show a short "day-of-week, date,
        hour" label in the hover tooltip (e.g. "Wed 08/19 14:00").
    front : str
        Which case to draw on top at full opacity: "Baseline" or "Proposed".
        The other case is drawn first, faded into the background.

    Returns
    -------
    go.Figure
        Scattergl bubble chart, X = temperature, Y = hourly cost, size = demand.
    """
    series = {
        "Baseline": dict(y=baseline_cost_hr, size=baseline_load, color=COLORS["red"]),
        "Proposed": dict(y=proposed_cost_hr, size=proposed_load, color=COLORS["teal"]),
    }
    front = front if front in series else "Proposed"
    back = "Baseline" if front == "Proposed" else "Proposed"

    # Non-negative bubble sizes (load values shouldn't be negative in
    # practice, but clip defensively so Plotly never receives a negative size).
    max_load = max(
        np.clip(baseline_load, 0, None).max(),
        np.clip(proposed_load, 0, None).max(),
        1e-9,
    )

    # Short-form "day-of-week date hour" label for the hover tooltip, e.g. "Wed 08/19 14:00".
    if datetime_vals is not None:
        date_labels = pd.to_datetime(pd.Series(datetime_vals)).dt.strftime('%a %m/%d %H:%M').to_numpy()
    else:
        date_labels = np.full(len(temp_vals), "")

    hover_template = (
        "%{customdata[0]}<br>"
        "Temp: %{x:.1f} °F<br>"
        "Cost: $%{y:.1f}/hr<br>"
        "Power: %{customdata[1]:.1f} kW<extra>%{fullData.name}</extra>"
    )

    fig = go.Figure()
    for name in (back, front):
        d = series[name]
        is_front = (name == front)
        size_vals = np.clip(d["size"], 0, None)
        customdata = np.column_stack([date_labels, size_vals])
        fig.add_trace(go.Scattergl(
            x=temp_vals, y=d["y"],
            mode="markers",
            name=f"{name} Load",
            customdata=customdata,
            hovertemplate=hover_template,
            marker=dict(
                size=size_vals,
                sizemode="area",
                sizeref=2.0 * max_load / (38.0 ** 2),
                sizemin=2,
                color=d["color"],
                opacity=0.85 if is_front else 0.22,
                line=dict(width=0),
            ),
        ))

    fig.update_layout(
        title=f"Temperature vs. Hourly Cost (bubble = building demand) — {front} in front",
        template="plotly_white",
        height=480,
        margin=dict(l=40, r=40, t=40, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_xaxes(title_text="Outdoor Air Temperature (°F)")
    fig.update_yaxes(title_text="Grid Avoided Cost ($/hr)")

    return fig


def plot_peaker_carrying_cost_breakdown(carrying_cost_dict):
    """
    Build a waterfall / component bar chart showing the composition of the
    avoided generation capacity scalar ($/kW-yr).

    Parameters
    ----------
    carrying_cost_dict : dict
        Output from calculations.calculate_ct_carrying_cost(), containing:
        - capital_recovery_annuity
        - fom_kw_yr
        - gross_carrying_cost
        - eas_offset_kw_yr
        - net_capacity_cost

    Returns
    -------
    go.Figure
    """
    cap_rec = carrying_cost_dict.get("capital_recovery_annuity", 0.0)
    fom = carrying_cost_dict.get("fom_kw_yr", 0.0)
    gross = carrying_cost_dict.get("gross_carrying_cost", 0.0)
    eas = carrying_cost_dict.get("eas_offset_kw_yr", 0.0)
    net = carrying_cost_dict.get("net_capacity_cost", gross)

    if eas > 0:
        x_labels = [
            "Capital Recovery<br>(CAPEX × FCR)",
            "Fixed O&M<br>(FOM)",
            "Gross Carrying Cost<br>(Total Peaker Annuity)",
            "Inframarginal Offset<br>(Net E&AS Margin)",
            "Net Avoided Capacity<br>(Net CONE / Scalar)"
        ]
        y_vals = [cap_rec, fom, gross, -eas, net]
        measures = ["relative", "relative", "total", "relative", "total"]
    else:
        x_labels = [
            "Capital Recovery<br>(CAPEX × FCR)",
            "Fixed O&M<br>(FOM)",
            "Avoided Capacity Scalar<br>(Gross Peaker Cost)"
        ]
        y_vals = [cap_rec, fom, gross]
        measures = ["relative", "relative", "total"]

    fig = go.Figure(go.Waterfall(
        name="Peaker Carrying Cost",
        orientation="v",
        measure=measures,
        x=x_labels,
        text=[f"${abs(v):,.2f}/kW-yr" for v in y_vals],
        textposition="outside",
        y=y_vals,
        connector={"line": {"color": "rgb(63, 63, 63)", "dash": "dot"}},
        decreasing={"marker": {"color": "#EF4444"}},
        increasing={"marker": {"color": "#3B82F6"}},
        totals={"marker": {"color": "#10B981"}}
    ))

    fig.update_layout(
        title="Avoided Generation Capacity: Next Planned Peaker Carrying Cost Breakdown",
        template="plotly_white",
        height=420,
        margin=dict(l=40, r=40, t=50, b=50),
        yaxis_title="Annual Carrying Cost ($/kW-year)",
        showlegend=False
    )
    return fig


def plot_southeast_cwf_distribution(cwf_array, datetime_series=None):
    """
    Build a dual-panel chart showing how Capacity Worth Factors (CWF)
    distribute reliability risk across hours of the day in winter vs summer.

    Parameters
    ----------
    cwf_array : np.ndarray
        8,760 array of capacity weights.
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps.

    Returns
    -------
    go.Figure
    """
    n_hours = len(cwf_array)
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

    df_cwf = pd.DataFrame({"month": months, "hour": hours, "cwf": cwf_array})

    # Group by season
    winter_mask = df_cwf["month"].isin([12, 1, 2])
    summer_mask = df_cwf["month"].isin([6, 7, 8, 9])

    winter_profile = df_cwf[winter_mask].groupby("hour")["cwf"].sum() * 100.0
    summer_profile = df_cwf[summer_mask].groupby("hour")["cwf"].sum() * 100.0

    all_hours = np.arange(24)
    w_vals = [winter_profile.get(h, 0.0) for h in all_hours]
    s_vals = [summer_profile.get(h, 0.0) for h in all_hours]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=all_hours,
        y=w_vals,
        name="Winter Cold Snaps (Dec–Feb)",
        marker_color="#2563EB",
        opacity=0.85
    ))
    fig.add_trace(go.Bar(
        x=all_hours,
        y=s_vals,
        name="Summer Heat Waves (Jun–Sep)",
        marker_color="#DC2626",
        opacity=0.85
    ))

    fig.update_layout(
        title="Southeast Capacity Risk Allocation by Hour of Day (% of Annual Risk)",
        template="plotly_white",
        barmode="group",
        height=400,
        margin=dict(l=40, r=40, t=50, b=50),
        xaxis=dict(
            title="Hour of Day (0 = Midnight, 6 = 6 AM, 14 = 2 PM)",
            tickmode="linear",
            tick0=0,
            dtick=1
        ),
        yaxis=dict(title="% of Total Annual Capacity Value"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


def plot_feeder_vs_system_load(feeder_weights, system_weights, datetime_series=None):
    """
    Build a comparison chart illustrating when localized feeder distribution stress
    occurs relative to bulk system transmission/wholesale peak hours.

    Parameters
    ----------
    feeder_weights : np.ndarray
        8,760 distribution peak weighting factors.
    system_weights : np.ndarray
        8,760 transmission / bulk system peak weighting factors.
    datetime_series : pd.Series or pd.DatetimeIndex, optional
        Timestamps.

    Returns
    -------
    go.Figure
    """
    n_hours = len(feeder_weights)
    if datetime_series is not None:
        dts = pd.to_datetime(datetime_series)
        hours = dts.dt.hour.to_numpy()
    else:
        hours = np.arange(n_hours) % 24

    df_comp = pd.DataFrame({
        "hour": hours,
        "feeder": feeder_weights * 100.0,
        "system": system_weights * 100.0
    })

    feeder_diurnal = df_comp.groupby("hour")["feeder"].sum()
    system_diurnal = df_comp.groupby("hour")["system"].sum()

    all_hours = np.arange(24)
    f_vals = [feeder_diurnal.get(h, 0.0) for h in all_hours]
    s_vals = [system_diurnal.get(h, 0.0) for h in all_hours]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=all_hours, y=f_vals,
        mode="lines+markers",
        name="Distribution Feeder Deferral",
        line=dict(color="#EC4899", width=3)
    ))
    fig.add_trace(go.Scatter(
        x=all_hours, y=s_vals,
        mode="lines+markers",
        name="Bulk Transmission / System PCAF",
        line=dict(color="#3B82F6", width=3, dash="dash")
    ))

    fig.update_layout(
        title="Feeder Distribution vs. Bulk Transmission Peak Allocation (% by Hour of Day)",
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=40, t=50, b=50),
        xaxis=dict(title="Hour of Day", tickmode="linear", tick0=0, dtick=1),
        yaxis=dict(title="% of Annual Value Stream"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig


def build_economic_balance_chart(npv_grid_savings, npv_retail_lost_revenue, npv_net_savings):
    """
    Build a clean horizontal comparison / waterfall chart for the Lifetime Economic Balance
    showing Grid Avoided Costs (+), Utility Lost Revenue (-), and Net Valuation NPV.

    Parameters
    ----------
    npv_grid_savings : float
        Discounted lifetime grid avoided costs ($).
    npv_retail_lost_revenue : float
        Discounted lifetime utility lost revenue / customer bill savings ($).
    npv_net_savings : float
        Net valuation NPV (grid savings minus lost revenue).

    Returns
    -------
    go.Figure
    """
    fig = go.Figure(go.Waterfall(
        name="Economic Balance",
        orientation="h",
        measure=["relative", "relative", "total"],
        y=["Grid Avoided Costs", "Utility Lost Revenue", "Net Valuation NPV"],
        x=[npv_grid_savings, -npv_retail_lost_revenue, 0],
        text=[f"+${npv_grid_savings:,.0f}", f"-${npv_retail_lost_revenue:,.0f}", f"${npv_net_savings:,.0f}"],
        textposition="outside",
        decreasing={"marker": {"color": "#F43F5E"}},
        increasing={"marker": {"color": "#10B981"}},
        totals={"marker": {"color": "#10B981" if npv_net_savings >= 0 else "#E11D48"}},
        connector={"line": {"color": "#94A3B8", "width": 1.5, "dash": "dot"}},
        hovertemplate="<b>%{y}:</b> %{text}<extra></extra>"
    ))

    fig.update_layout(
        template="plotly_white",
        height=190,
        margin=dict(l=145, r=110, t=15, b=25),
        xaxis=dict(
            title="",
            showgrid=True,
            gridcolor="#F1F5F9",
            zeroline=True,
            zerolinecolor="#94A3B8",
            zerolinewidth=1.5,
            tickprefix="$",
            tickformat=","
        ),
        yaxis=dict(
            autorange="reversed",
            tickfont=dict(size=12, family="sans-serif", color="#334155")
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def build_two_sided_cost_effectiveness_chart(
    annual_energy_savings,
    annual_gen_cap_savings,
    annual_trans_savings,
    annual_dist_savings,
    annual_emissions_savings,
    retail_energy_savings,
    retail_demand_savings,
    annual_net_savings
):
    """
    Build an interactive two-sided comparison bar chart for Tab 3 (Cost-Effectiveness Table).
    Visualizes Wholesale Grid Deferrals (5-component stacked bar) vs. Customer Bill
    Reductions / Lost Revenue (2-component stacked bar) alongside the Net Operating Margin.

    Parameters
    ----------
    annual_energy_savings : float
        Wholesale energy avoided costs ($/yr).
    annual_gen_cap_savings : float
        Generation capacity avoided costs ($/yr).
    annual_trans_savings : float
        Transmission deferral avoided costs ($/yr).
    annual_dist_savings : float
        Distribution deferral avoided costs ($/yr).
    annual_emissions_savings : float
        Carbon emissions avoided costs ($/yr).
    retail_energy_savings : float
        Retail volumetric energy bill reductions ($/yr).
    retail_demand_savings : float
        Retail demand charge bill reductions ($/yr).
    annual_net_savings : float
        Net annual operational margin (Grid avoided costs minus retail lost revenue, $/yr).

    Returns
    -------
    go.Figure
    """
    fig = go.Figure()

    annual_grid_savings = (
        annual_gen_cap_savings + annual_energy_savings +
        annual_dist_savings + annual_emissions_savings + annual_trans_savings
    )
    annual_lost_revenue = retail_energy_savings + retail_demand_savings

    # 1. Grid Avoided Cost Components (Stacked)
    grid_components = [
        ("Generation Capacity", annual_gen_cap_savings, "#0D9488"),
        ("Wholesale Energy", annual_energy_savings, "#F59E0B"),
        ("Distribution Deferral", annual_dist_savings, "#EC4899"),
        ("Carbon Avoided", annual_emissions_savings, "#10B981"),
        ("Transmission Deferral", annual_trans_savings, "#3B82F6"),
    ]
    for name, val, color in grid_components:
        pct = (val / annual_grid_savings * 100) if annual_grid_savings > 0 else 0
        txt = f"${val:,.0f} ({pct:.0f}%)" if val >= 25 else (f"${val:,.0f}" if val >= 10 else "")
        fig.add_trace(go.Bar(
            name=name,
            x=["Wholesale Grid Deferrals"],
            y=[val],
            marker_color=color,
            text=[txt],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate=f"<b>{name}:</b> $%{{y:,.2f}} / yr ({pct:.1f}%)<extra></extra>"
        ))

    # 2. Retail Bill Savings / Lost Revenue Components (Stacked)
    retail_components = [
        ("Retail Energy Savings", retail_energy_savings, "#F43F5E"),
        ("Retail Demand Savings", retail_demand_savings, "#BE123C"),
    ]
    for name, val, color in retail_components:
        pct = (val / annual_lost_revenue * 100) if annual_lost_revenue > 0 else 0
        txt = f"${val:,.0f} ({pct:.0f}%)" if val >= 25 else (f"${val:,.0f}" if val >= 10 else "")
        fig.add_trace(go.Bar(
            name=name,
            x=["Customer Bill Savings"],
            y=[val],
            marker_color=color,
            text=[txt],
            textposition="inside",
            insidetextanchor="middle",
            hovertemplate=f"<b>{name}:</b> $%{{y:,.2f}} / yr ({pct:.1f}%)<extra></extra>"
        ))

    # 3. Net Annual Operating Margin (Single bar)
    net_sign = "+" if annual_net_savings >= 0 else "-"
    net_color = "#059669" if annual_net_savings >= 0 else "#E11D48"
    fig.add_trace(go.Bar(
        name="Net Operating Margin",
        x=["Net Operating Margin"],
        y=[annual_net_savings],
        marker_color=net_color,
        text=[f"{net_sign}${abs(annual_net_savings):,.2f}"],
        textposition="outside",
        hovertemplate=f"<b>Net Operating Margin:</b> {net_sign}${abs(annual_net_savings):,.2f} / yr<extra></extra>"
    ))

    # Dynamic y-axis scale with padding for annotations
    max_top = max(annual_grid_savings, annual_lost_revenue, max(0, annual_net_savings))
    min_bottom = min(0, annual_net_savings)
    y_pad = max(max_top * 0.18, 50.0)
    y_min_pad = abs(min_bottom) * 1.25 if min_bottom < 0 else 0

    # Total and Net Annotations
    fig.add_annotation(
        x="Wholesale Grid Deferrals",
        y=annual_grid_savings,
        text=f"<b>Total: ${annual_grid_savings:,.2f}</b>",
        showarrow=False,
        yshift=14,
        font=dict(size=12, color="#0F172A")
    )
    fig.add_annotation(
        x="Customer Bill Savings",
        y=annual_lost_revenue,
        text=f"<b>Total: ${annual_lost_revenue:,.2f}</b>",
        showarrow=False,
        yshift=14,
        font=dict(size=12, color="#0F172A")
    )
    fig.add_annotation(
        x="Net Operating Margin",
        y=annual_net_savings,
        text=f"<b>Net: {net_sign}${abs(annual_net_savings):,.2f}</b>",
        showarrow=False,
        yshift=14 if annual_net_savings >= 0 else -16,
        font=dict(size=12, color=net_color)
    )

    fig.update_layout(
        barmode="stack",
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=40, t=35, b=40),
        yaxis=dict(
            title="Annual Value ($/yr)",
            tickprefix="$",
            tickformat=",",
            range=[-y_min_pad, max_top + y_pad],
            gridcolor="#F1F5F9",
            zeroline=True,
            zerolinecolor="#94A3B8",
            zerolinewidth=1.5,
        ),
        xaxis=dict(
            tickfont=dict(size=12, color="#1E293B", family="sans-serif")
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.04,
            xanchor="center",
            x=0.5,
            font=dict(size=10.5)
        ),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)"
    )
    return fig




