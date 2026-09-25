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


def _rgba(hex_color, alpha=0.5):
    """Convert a '#RRGGBB' color to a Plotly 'rgba(r, g, b, a)' fill string."""
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def _add_signed_bars(fig, x, y, row, positive_name, negative_name, legend=None,
                      pos_color=None, neg_color=None, show_zero_line=True):
    """
    Add a two-trace signed bar chart to a subplot row: one bar per hour,
    green when the value is >= 0 (good), red when it's negative (bad), plus
    a dotted zero-reference line. Bars read much more cleanly than a filled
    area for a series that flips sign often (e.g. an hourly kW delta).

    `legend`, if given, assigns these traces to a named Plotly legend group
    (e.g. "legend2") so each subplot row can have its own legend instead of
    one long combined legend for the whole figure.

    `pos_color`/`neg_color` default to the standard green/red good-bad pair;
    override them (e.g. to a pink/rose pair) when a second signed-bar series
    shares a row with another one, so the two remain visually distinguishable.
    `show_zero_line` can be set False on a second call for the same row, so
    the dotted zero line isn't drawn twice.
    """
    y = np.asarray(y, dtype=float)
    pos_vals = np.where(y >= 0, y, np.nan)
    neg_vals = np.where(y < 0, y, np.nan)

    fig.add_trace(
        go.Bar(
            x=x, y=pos_vals, name=positive_name,
            marker_color=pos_color or COLORS["green"],
            legend=legend
        ),
        row=row, col=1
    )
    fig.add_trace(
        go.Bar(
            x=x, y=neg_vals, name=negative_name,
            marker_color=neg_color or COLORS["red"],
            legend=legend
        ),
        row=row, col=1
    )
    if show_zero_line:
        fig.add_hline(y=0, row=row, col=1, line_width=1, line_dash="dot", line_color="rgba(100,100,100,0.6)")


def _row_y_span(row_heights, vertical_spacing, row_idx):
    """
    Compute the (bottom, top) paper-y span (0-1) for a 1-indexed row in a
    make_subplots grid with the given row_heights fractions (summing to 1)
    and vertical_spacing between rows. Used to park a per-row legend next
    to its own subplot instead of one combined legend for the whole figure.
    """
    n = len(row_heights)
    usable = 1.0 - vertical_spacing * (n - 1)
    top = 1.0
    for i, frac in enumerate(row_heights):
        height = frac * usable
        bottom = top - height
        if i == row_idx - 1:
            return bottom, top
        top = bottom - vertical_spacing
    raise ValueError(f"row_idx {row_idx} out of range for {n} rows")


def build_weekly_load_and_temp_chart(datetime_slice, baseline_slice, proposed_slice, temp_slice):
    """
    Build a two-row chart: Baseline vs Proposed load profiles (kW) stacked
    on top, Outdoor Air Temperature (°F) on its own axis below, sharing a
    synced x-axis so hours line up vertically between the two.

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
        Two-row Plotly figure: kW demand on top, °F temperature on bottom.
    """
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.62, 0.38],
    )

    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=baseline_slice,
            name="Baseline Load (kW)",
            line=dict(color=COLORS["red"], width=2)
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=proposed_slice,
            name="Proposed Load (kW)",
            line=dict(color=COLORS["teal"], width=2)
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=datetime_slice, y=temp_slice,
            name="Outdoor Air Temp (°F)",
            line=dict(color=COLORS["blue"], width=1.5, dash='dot'),
            opacity=0.85
        ),
        row=2, col=1
    )

    fig.update_layout(
        template="plotly_white",
        height=560,
        margin=dict(l=40, r=40, t=30, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Building Demand (kW)", row=1, col=1)
    fig.update_yaxes(title_text="Outdoor Air Temp (°F)", row=2, col=1)
    fig.update_xaxes(showticklabels=True, row=2, col=1)

    return fig


def build_weekly_grid_economics_chart(slice_df, mode="Stacked Components"):
    """
    Build a 4-row subplot figure for weekly grid & customer economics analysis:
    - Row 1: Grid Avoided Cost Economics ($/MWh) — a grid-system-only view, not affected
             by which technology is selected. Configurable as stacked components,
             individual component lines, or total marginal cost.
    - Row 2: Load Reduction panel (kW), aligned on the exact same X-axis. Rendered as
             hourly bars (an area fill looked like a blob on a series that flips sign
             often) — green where the proposed case uses less than baseline (good) and
             red where it uses more (bad — e.g. a battery charging).
    - Row 3: Grid Value Created vs. Lost Retail Revenue ($/hr), side by side on the same
             axis rather than netted into one number — Grid Value Created (Row 1 x Row 2,
             green/red) is the grid's avoided cost actually captured by this technology's
             load reduction that hour; Lost Retail Revenue (green/pink) is the utility's
             retail revenue given up that same hour (Baseline − Proposed customer bill).
             Both are hourly bars grouped side by side so the two can be compared
             hour by hour without collapsing them into a single RIM-style net figure.
    - Row 4: Customer Retail Operating Cost ($/hr) — Baseline (purple) vs. Proposed
             (amber) bill impact as lines, with the applicable retail energy rate
             ($/kWh) on a secondary Y-axis. (The bill-delta bar now lives on Row 3 as
             "Lost Retail Revenue" instead of being duplicated here.)

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
        Grid Value Created vs. Lost Retail Revenue on Row 3, and Customer Retail
        Operating Cost on Row 4.
    """
    row_heights = [0.34, 0.20, 0.20, 0.26]
    vertical_spacing = 0.055

    fig = make_subplots(
        rows=4, cols=1,
        shared_xaxes=True,
        vertical_spacing=vertical_spacing,
        row_heights=row_heights,
        specs=[[{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": False}], [{"secondary_y": True}]],
        subplot_titles=(
            "Wholesale Grid Avoided Cost Economics ($/MWh) — not affected by the technology",
            "Load Change vs. Baseline (kW) — green = uses less, red = uses more",
            "Grid Value Created (green/red) vs. Lost Retail Revenue (green/pink) ($/hr)",
            "Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed"
        )
    )

    # Row 1: Grid Economics
    if mode == "Total Marginal Cost ($/MWh)":
        fig.add_trace(
            go.Scatter(
                x=slice_df['Datetime'], y=slice_df['Total_Avoided_Cost_MWh'],
                mode='lines', name='Total Avoided Cost ($/MWh)',
                line=dict(color=COLORS["purple"], width=2.5),
                legend='legend'
            ),
            row=1, col=1
        )
    elif mode == "Individual Component Lines":
        for col_name, label, color in GRID_COMPONENTS:
            fig.add_trace(
                go.Scatter(
                    x=slice_df['Datetime'], y=slice_df[col_name],
                    mode='lines', name=label,
                    line=dict(color=color, width=1.8),
                    legend='legend'
                ),
                row=1, col=1
            )
        fig.add_trace(
            go.Scatter(
                x=slice_df['Datetime'], y=slice_df['Total_Avoided_Cost_MWh'],
                mode='lines', name='Total Avoided Cost ($/MWh)',
                line=dict(color=COLORS["purple"], width=2, dash='dash'),
                legend='legend'
            ),
            row=1, col=1
        )
    else:  # Default: "Stacked Components"
        for col_name, label, color in GRID_COMPONENTS:
            fig.add_trace(
                go.Scatter(
                    x=slice_df['Datetime'], y=slice_df[col_name],
                    mode='lines', name=label, stackgroup='one',
                    line=dict(color=color, width=0.5),
                    legend='legend'
                ),
                row=1, col=1
            )

    # Row 2: Standalone Load Reduction Panel. Positive = proposed case uses
    # LESS than baseline that hour (good); negative = it uses MORE (bad —
    # e.g. a battery charging).
    if 'Load_Reduction_kW' in slice_df.columns:
        reduction_vals = slice_df['Load_Reduction_kW']
    else:
        reduction_vals = np.zeros(len(slice_df))

    _add_signed_bars(
        fig, slice_df['Datetime'], reduction_vals, row=2,
        positive_name='Reduces Demand (kW)',
        negative_name='Increases Demand (kW)',
        legend='legend2'
    )

    # Row 3, series A: Hourly Grid Value Created ($/hr). Positive = grid
    # value created / money saved that hour (good); negative = grid value
    # lost / cost increase (bad).
    if 'Hourly_Savings_hr' in slice_df.columns:
        hourly_savings = slice_df['Hourly_Savings_hr']
    else:
        hourly_savings = (reduction_vals / 1000.0) * slice_df['Total_Avoided_Cost_MWh']

    _add_signed_bars(
        fig, slice_df['Datetime'], hourly_savings, row=3,
        positive_name='Grid Value Created ($/hr)',
        negative_name='Grid Value Lost ($/hr)',
        legend='legend3'
    )

    # Customer bill cost (needed here for Row 3, series B, and again for Row 4's lines).
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

    # Row 3, series B: the utility's own hourly revenue effect (Proposed minus
    # Baseline customer bill) -- the mirror image of the customer's bill delta.
    # Negative = the utility collects less retail revenue that hour (bad, pink);
    # positive = it collects more (good, green) -- same sign convention as the
    # Lifetime Cash Flow tab's Utility view. Grouped side by side with Grid
    # Value Created above (not netted into one number) so both are visible.
    utility_revenue_vals = proposed_cost_vals - baseline_cost_vals
    _add_signed_bars(
        fig, slice_df['Datetime'], utility_revenue_vals, row=3,
        positive_name='Revenue Gain ($/hr)',
        negative_name='Lost Retail Revenue ($/hr)',
        legend='legend3',
        neg_color=COLORS["pink"],
        show_zero_line=False
    )

    # Row 4: Customer Retail Operating Cost ($/hr) — Baseline vs. Proposed,
    # with the applicable retail energy rate ($/kWh) on a secondary Y-axis.
    # (The bill-delta bar lives on Row 3 now, as "Lost Retail Revenue", so
    # it isn't duplicated here.)
    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=baseline_cost_vals,
            mode='lines', name='Customer Cost - Baseline ($/hr)',
            line=dict(color=COLORS["purple"], width=2),
            legend='legend4'
        ),
        row=4, col=1, secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=proposed_cost_vals,
            mode='lines', name='Customer Cost - Proposed ($/hr)',
            line=dict(color=COLORS["amber"], width=2),
            legend='legend4'
        ),
        row=4, col=1, secondary_y=False
    )
    fig.add_trace(
        go.Scatter(
            x=slice_df['Datetime'], y=retail_rate_vals,
            mode='lines', name='Retail Energy Rate ($/kWh)',
            line=dict(color=COLORS["blue"], width=1.5, dash='dot'),
            opacity=0.85,
            legend='legend4'
        ),
        row=4, col=1, secondary_y=True
    )

    # One legend per row, parked just to the right of the plot area and
    # top-aligned with that row, instead of one long combined legend that
    # mixes traces from all 4 panels together.
    legend_style = dict(
        orientation="v", xanchor="left", x=1.02, yanchor="top",
        font=dict(size=10.5),
        bgcolor="rgba(255,255,255,0.85)", bordercolor=COLORS["border"], borderwidth=1
    )
    _, row1_top = _row_y_span(row_heights, vertical_spacing, 1)
    _, row2_top = _row_y_span(row_heights, vertical_spacing, 2)
    _, row3_top = _row_y_span(row_heights, vertical_spacing, 3)
    _, row4_top = _row_y_span(row_heights, vertical_spacing, 4)

    fig.update_layout(
        template="plotly_white",
        height=900,
        # Row 4 has its own secondary y-axis (Retail Rate), which needs its
        # ticks/title drawn in the same right-hand margin as the legends —
        # so it gets extra right margin and its legend is pushed further
        # out (x=1.22 vs 1.02) to clear that axis instead of overlapping it.
        margin=dict(l=40, r=230, t=30, b=40),
        hovermode="x unified",
        # Row 2 and Row 4's bar pairs are each mutually exclusive per hour (a
        # value is either positive or negative, never both), so grouping is a
        # no-op there. Row 3 now has two independent series that can both be
        # non-zero in the same hour (grid value and lost revenue), so explicit
        # "group" mode places them side by side instead of overlapping.
        barmode='group',
        legend={**legend_style, "y": row1_top},
        legend2={**legend_style, "y": row2_top},
        legend3={**legend_style, "y": row3_top},
        legend4={**legend_style, "y": row4_top, "x": 1.22},
    )
    fig.update_yaxes(title_text="Avoided Cost ($/MWh)", row=1, col=1)
    fig.update_yaxes(title_text="Reduction (kW)", row=2, col=1)
    fig.update_yaxes(title_text="$/hr", row=3, col=1)
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


def build_annual_avoided_cost_chart(results_df, mode="Hourly Line (Full Year)"):
    """
    Build a full-year wholesale avoided cost chart, either as an hourly line
    or a monthly box-and-whisker distribution.

    Parameters
    ----------
    results_df : pd.DataFrame
        Must contain 'Datetime' and 'Total_Avoided_Cost_MWh' columns.
    mode : str
        "Hourly Line (Full Year)" (default) or "Monthly Box & Whisker". The
        box plot exists because a handful of extreme-price hours (cold
        snaps, heat waves) can dominate the hourly line and flatten out the
        rest of the year visually. The box plot's own y-axis is capped at a
        robust "normal range" ceiling (Q3 + 1.5*IQR across the full year) so
        the boxes stay legible; months with hours above that ceiling get a
        small text annotation ("▲N hrs, max $X") instead of being silently
        cut off.

    Returns
    -------
    go.Figure
        Hourly line chart, or a per-month box plot, of Total_Avoided_Cost_MWh.
    """
    if mode == "Monthly Box & Whisker":
        month_order = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        df = pd.DataFrame({
            'Month': pd.to_datetime(results_df['Datetime']).dt.strftime('%b'),
            'Value': results_df['Total_Avoided_Cost_MWh'].to_numpy()
        })

        fig = go.Figure()
        fig.add_trace(go.Box(
            x=df['Month'], y=df['Value'],
            name='Total avoided cost rate ($/MWh)',
            marker_color=COLORS["purple"],
            boxpoints='outliers'
        ))

        # A handful of extreme-price hours can be 10-100x the typical hour,
        # which forces the y-axis so tall that every month's actual box
        # (median + middle 50%) collapses to a flat line near zero. Cap the
        # visible range at a robust "normal range" ceiling (the classic
        # Q3 + 1.5*IQR outlier fence, computed across the full year) so the
        # boxes themselves are legible, and annotate any month with hours
        # above that ceiling instead of silently cutting them off.
        vals = df['Value'].to_numpy()
        q1, q3 = np.nanpercentile(vals, [25, 75])
        iqr = q3 - q1
        upper_fence = q3 + 1.5 * iqr
        if not np.isfinite(upper_fence) or upper_fence <= 0:
            y_ceiling = float(np.nanmax(vals)) * 1.1 if np.nanmax(vals) > 0 else 1.0
        else:
            y_ceiling = upper_fence * 1.2

        for month in month_order:
            month_vals = df.loc[df['Month'] == month, 'Value']
            if month_vals.empty:
                continue
            n_above = int((month_vals > y_ceiling).sum())
            if n_above > 0:
                fig.add_annotation(
                    x=month, y=y_ceiling, yanchor='top',
                    text=f"▲{n_above} hr{'s' if n_above != 1 else ''}<br>max ${month_vals.max():,.0f}",
                    showarrow=False,
                    font=dict(size=8.5, color=COLORS["slate_mid"]),
                    align="center"
                )

        fig.update_layout(
            xaxis_title="Month",
            yaxis_title="Wholesale Avoided Cost ($/MWh)",
            template="plotly_white",
            height=380,
            margin=dict(l=40, r=30, t=10, b=40)
        )
        fig.update_xaxes(categoryorder='array', categoryarray=month_order)
        fig.update_yaxes(range=[0, y_ceiling])
        return fig

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
        yaxis_title="Wholesale Avoided Cost ($/MWh)",
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


def build_winter_summer_comparison_chart(winter_slice, summer_slice,
                                          winter_label="Winter Peak", summer_label="Summer Peak",
                                          y_range=None):
    """
    Build a single figure with two side-by-side stacked-area panels (e.g.
    winter vs. summer peak component breakdown), sharing ONE legend across
    the top of both panels instead of a separate legend per panel — a
    combined Plotly figure is the only way to get a legend that visually
    spans two panels, since two independent st.plotly_chart() calls in
    separate Streamlit columns can't share one legend.

    Parameters
    ----------
    winter_slice, summer_slice : pd.DataFrame
        Slices of results_df containing 'Datetime' and all component columns.
    winter_label, summer_label : str
        Sub-title shown above each panel (e.g. the date range).
    y_range : tuple of (float, float), optional
        If given, caps both panels' y-axis to this range (e.g. to zoom into
        the "typical" hours when a few extreme-price hours would otherwise
        stretch the axis so tall that everything else looks flat). The
        underlying data is untouched — hours above the cap are just off the
        top of this particular view, same as scrolling/zooming manually.

    Returns
    -------
    go.Figure
        Two-panel figure, one shared legend, one trace per component per panel.
    """
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=(winter_label, summer_label),
        horizontal_spacing=0.08,
    )
    for col_idx, slice_df in enumerate([winter_slice, summer_slice], start=1):
        for col_name, label, color in GRID_COMPONENTS:
            fig.add_trace(
                go.Scatter(
                    x=slice_df['Datetime'], y=slice_df[col_name],
                    mode='lines', name=label, stackgroup='one',
                    line=dict(color=color, width=0.5),
                    legendgroup=label,
                    showlegend=(col_idx == 1),
                ),
                row=1, col=col_idx
            )
    fig.update_layout(
        template="plotly_white", height=380,
        margin=dict(l=40, r=20, t=90, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.22, xanchor="center", x=0.5)
    )
    if y_range is not None:
        fig.update_yaxes(range=list(y_range))
    return fig


def build_lifetime_npv_chart(years, benefit_stream, cost_stream=None,
                              benefit_name="Grid Savings (PV)",
                              benefit_negative_name="Grid Cost (PV)",
                              cost_name="Lost Retail Revenue (PV)",
                              cost_negative_name="Revenue Gain (PV)",
                              upfront_cost=0.0,
                              upfront_name="Upfront Cost (after rebate)"):
    """
    Lifetime cash-flow view, in today's dollars (present value). Each bar's
    color follows its own year-by-year sign — green when it actually helps
    this perspective's net position that year, red/pink when it hurts —
    rather than a fixed color per named series. This matters because
    `benefit_stream`/`cost_stream` are signed quantities that can flip in
    real data (e.g. a technology that usually reduces grid stress but adds
    it in a handful of hours, or a customer bill that goes up instead of
    down some years), and coloring by category instead of by sign would
    show a "cost" bar sitting above zero looking like a benefit. The bold
    line is the running cumulative net cash flow — where it crosses zero is
    the discounted payback period, its final value is the net NPV. No
    in-figure title, since the caller's page header already names the
    chart; adding one here just crowds the legend sitting right below it.

    Two perspectives share this one function:
    - Utility: `benefit_stream` = grid savings, `cost_stream` = lost retail
      revenue (a recurring annual cost, positive = revenue actually lost),
      `upfront_cost` = the program cost paid once at rollout (incentive +
      admin/marketing).
    - Customer: `benefit_stream` = bill savings, `upfront_cost` = their net
      equipment cost after any utility rebate, charged once at "Year 0"
      (no `cost_stream`).

    Parameters
    ----------
    years : np.ndarray
        Operating year numbers (1-indexed).
    benefit_stream : np.ndarray
        Discounted (present value) benefit per year. Usually positive; a
        negative year is plotted red under `benefit_negative_name`.
    cost_stream : np.ndarray, optional
        Discounted (present value) recurring cost per year, in
        positive-magnitude terms (e.g. dollars of revenue foregone).
        Displayed as a negative (red/pink) bar; a negative input year
        (a net gain instead of a cost) is plotted green under
        `cost_negative_name`.
    upfront_cost : float
        A one-time cost incurred before Year 1, plotted as its own "Year 0"
        bar. 0 (default) means there isn't one. Assumed non-negative.

    Returns
    -------
    go.Figure
    """
    years = np.asarray(years)
    benefit_stream = np.asarray(benefit_stream, dtype=float)
    has_cost_stream = cost_stream is not None
    cost_stream = np.asarray(cost_stream, dtype=float) if has_cost_stream else np.zeros_like(benefit_stream)
    has_upfront = upfront_cost > 0

    x_years = np.concatenate(([0], years)) if has_upfront else years
    benefit_full = np.concatenate(([0.0], benefit_stream)) if has_upfront else benefit_stream
    cost_full = np.concatenate(([0.0], cost_stream)) if has_upfront else cost_stream

    period_net = benefit_stream - cost_stream
    if has_upfront:
        period_net = np.concatenate(([-upfront_cost], period_net))
    cumulative_net = np.cumsum(period_net)

    def _add_signed(x, values, pos_name, neg_name, neg_color):
        pos_vals = np.where(values > 0, values, 0.0)
        neg_vals = np.where(values < 0, values, 0.0)
        if np.any(pos_vals != 0):
            fig.add_trace(go.Bar(x=x, y=pos_vals, name=pos_name, marker_color=COLORS["green"]))
        if np.any(neg_vals != 0):
            fig.add_trace(go.Bar(x=x, y=neg_vals, name=neg_name, marker_color=neg_color))

    fig = go.Figure()
    _add_signed(x_years, benefit_full, benefit_name, benefit_negative_name, COLORS["red"])
    if has_upfront:
        upfront_y = np.concatenate(([-upfront_cost], np.zeros_like(benefit_stream)))
        fig.add_trace(go.Bar(
            x=x_years, y=upfront_y,
            name=upfront_name, marker_color=COLORS["red"]
        ))
    if has_cost_stream:
        # cost_full is a cost in positive-magnitude terms, so its display
        # value (the effect on this perspective's cash position) is negated:
        # a real cost (cost_full > 0) shows red/pink below zero, a net gain
        # (cost_full < 0) shows green above zero.
        _add_signed(
            x_years, -cost_full, cost_negative_name, cost_name,
            COLORS["pink"] if has_upfront else COLORS["red"]
        )
    fig.add_trace(go.Scatter(
        x=x_years, y=cumulative_net, name='Cumulative Net Cash Flow (PV)',
        mode='lines+markers', line=dict(color=COLORS["slate_dark"], width=2.5)
    ))
    fig.add_hline(y=0, line_width=1, line_color="rgba(100,100,100,0.5)")

    fig.update_layout(
        xaxis_title="Operating Year (0 = upfront)" if has_upfront else "Operating Year",
        yaxis_title="Present value ($)",
        template="plotly_white",
        height=380,
        margin=dict(l=40, r=20, t=50, b=40),
        barmode='relative',
        hovermode="x unified",
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

    # Non-negative, non-NaN bubble sizes. Plotly's marker 'size' rejects both
    # negative and NaN values outright (a single missing hour in the source
    # file is enough to crash the whole chart), so clip and nan_to_num
    # defensively here rather than trusting every upstream caller to have
    # already scrubbed gaps out of the load arrays.
    max_load = max(
        np.nanmax(np.clip(baseline_load, 0, None)),
        np.nanmax(np.clip(proposed_load, 0, None)),
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
        size_vals = np.nan_to_num(np.clip(d["size"], 0, None), nan=0.0)
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
        title=dict(text="Capacity Risk by Hour of Day<br><sup>% of Annual Risk</sup>", font=dict(size=14)),
        template="plotly_white",
        barmode="group",
        height=400,
        margin=dict(l=40, r=20, t=60, b=90),
        xaxis=dict(
            title="Hour of Day (0 = Midnight, 6 = 6 AM, 14 = 2 PM)",
            tickmode="linear",
            tick0=0,
            dtick=2,
            range=[-0.5, 23.5]
        ),
        yaxis=dict(title="% of Total Annual Capacity Value"),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5)
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
        title=dict(text="Feeder vs. Bulk Transmission Peaking<br><sup>% of Annual Value, by Hour of Day</sup>", font=dict(size=14)),
        template="plotly_white",
        height=400,
        margin=dict(l=40, r=20, t=60, b=90),
        xaxis=dict(title="Hour of Day", tickmode="linear", tick0=0, dtick=2, range=[-0.5, 23.5]),
        yaxis=dict(title="% of Annual Value Stream"),
        legend=dict(orientation="h", yanchor="top", y=-0.25, xanchor="center", x=0.5)
    )
    return fig


def build_economic_balance_chart(npv_grid_savings, npv_retail_lost_revenue, npv_net_savings,
                                  npv_program_cost=0.0):
    """
    Build a clean horizontal comparison / waterfall chart for the Lifetime Economic Balance
    showing Grid Avoided Costs (+), Utility Lost Revenue (-), optionally Utility Program
    Cost (-), and Net Valuation NPV.

    Parameters
    ----------
    npv_grid_savings : float
        Discounted lifetime grid avoided costs ($).
    npv_retail_lost_revenue : float
        Discounted lifetime utility lost revenue / customer bill savings ($).
    npv_net_savings : float
        Net valuation NPV (grid savings minus lost revenue minus program cost).
    npv_program_cost : float
        One-time utility program cost (incentive + admin), undiscounted since it's
        already in today's dollars. 0 (default) omits the bar entirely, so the
        common "no program cost" case doesn't show a needless $0 step.

    Returns
    -------
    go.Figure
    """
    # Sign the label off the bar's own plotted value (not a hardcoded "+"/"-"),
    # since any of these can legitimately go negative -- e.g. Grid Avoided
    # Costs when a technology adds more grid stress than it relieves, or
    # Utility Lost Revenue's bar (-npv_retail_lost_revenue) flipping positive
    # when the customer's bill actually goes up. A fixed prefix would print
    # nonsense like "+$-474" or contradict a bar that's rendering green.
    def _signed_dollar(v):
        return f"+${v:,.0f}" if v >= 0 else f"-${abs(v):,.0f}"

    measure = ["relative", "relative"]
    y = ["Grid Avoided Costs", "Utility Lost Revenue"]
    x = [npv_grid_savings, -npv_retail_lost_revenue]
    text = [_signed_dollar(npv_grid_savings), _signed_dollar(-npv_retail_lost_revenue)]

    if npv_program_cost > 0:
        measure.append("relative")
        y.append("Utility Program Cost")
        x.append(-npv_program_cost)
        text.append(_signed_dollar(-npv_program_cost))

    measure.append("total")
    y.append("Net Valuation NPV")
    x.append(0)
    text.append(_signed_dollar(npv_net_savings))

    fig = go.Figure(go.Waterfall(
        name="Economic Balance",
        orientation="h",
        measure=measure,
        y=y,
        x=x,
        text=text,
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


def _stem_trace_xy(x_vals, values, mask):
    """
    Build (x, y) coordinate arrays for a stem/lollipop-style line trace:
    each selected point becomes an isolated (x, 0) -> (x, value) -> break
    vertical segment. Unlike a filled line (which draws a slanted boundary
    connecting one hour's value straight to the next and fills underneath
    it), a stem returns to a true gap between hours, so a handful of tall
    spikes reads as discrete up/down marks instead of blurring together
    into one continuous silhouette. Still a plain line stroke under the
    hood, so — unlike go.Bar — it stays visible even when hundreds/thousands
    of points are packed into the chart width.
    """
    x_arr = np.asarray(x_vals)[mask]
    y_arr = np.asarray(values, dtype=float)[mask]
    n = len(x_arr)
    stem_x = np.repeat(x_arr, 3)
    stem_y = np.empty(3 * n, dtype=float)
    stem_y[0::3] = 0.0
    stem_y[1::3] = y_arr
    stem_y[2::3] = np.nan
    return stem_x, stem_y


def build_cost_duration_chart(x_vals, baseline_vals, proposed_vals, x_title,
                               y_title="Cost ($/hr)", change_y_title="Change ($/hr)", y_range=None):
    """
    "Duration curve" style diagnostic at hourly resolution: Baseline cost
    (line) with Proposed overlaid (row 1), plus the hour-by-hour change —
    Baseline minus Proposed, positive = savings — as signed stems
    underneath (row 2, green = saves money, red = costs more). Each hour's
    change is its own isolated vertical stroke from zero (see
    `_stem_trace_xy`) rather than a continuous filled area, so it reads as
    up/down bars per hour instead of one smoothed-looking blob — while
    still staying visible at densities (a full month, even a full year)
    where an actual go.Bar trace would go sub-pixel and disappear.

    The caller controls the hour ordering via `x_vals`/pre-sorted
    `baseline_vals`/`proposed_vals` — e.g. sorted by cost descending (a
    classic duration-curve shape), left chronological, or sorted by
    outdoor temperature. Baseline and Proposed are NOT independently
    re-sorted from each other, so the second line/change stems show real
    hour-by-hour variability relative to whatever order was chosen, rather
    than two independently-smoothed curves.

    Parameters
    ----------
    x_vals : array-like
        X-axis values in the caller's chosen order (e.g. hour rank, or
        actual Datetime for a chronological view).
    baseline_vals, proposed_vals : np.ndarray
        Per-hour cost ($/hr), already arranged in the same order as x_vals.
    x_title, y_title, change_y_title : str
    y_range : tuple of (float, float), optional
        If given, caps row 1's y-axis (e.g. so a handful of extreme hours
        don't flatten the rest). Values above the cap are simply clipped
        from view — the caller is responsible for telling the user how many
        hours/what max got cut off, since that's easier to summarize in a
        caption than to annotate on a dense line.

    Returns
    -------
    go.Figure
    """
    baseline_vals = np.asarray(baseline_vals, dtype=float)
    proposed_vals = np.asarray(proposed_vals, dtype=float)
    change = baseline_vals - proposed_vals

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08,
        row_heights=[0.62, 0.38],
    )
    fig.add_trace(go.Scatter(
        x=x_vals, y=baseline_vals, name="Baseline", mode="lines",
        line=dict(color=COLORS["purple"], width=1.5)
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=x_vals, y=proposed_vals, name="Proposed", mode="lines",
        line=dict(color=COLORS["amber"], width=1.5)
    ), row=1, col=1)

    pos_x, pos_y = _stem_trace_xy(x_vals, change, change >= 0)
    neg_x, neg_y = _stem_trace_xy(x_vals, change, change < 0)
    fig.add_trace(go.Scatter(
        x=pos_x, y=pos_y, name="Saves Money", mode="lines",
        line=dict(color=COLORS["green"], width=1.5)
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=neg_x, y=neg_y, name="Costs More", mode="lines",
        line=dict(color=COLORS["red"], width=1.5)
    ), row=2, col=1)
    fig.add_hline(y=0, row=2, col=1, line_width=1, line_color="rgba(100,100,100,0.5)")

    if y_range is not None:
        fig.update_yaxes(range=list(y_range), row=1, col=1)

    fig.update_layout(
        template="plotly_white",
        height=560,
        margin=dict(l=50, r=20, t=30, b=50),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text=y_title, row=1, col=1)
    fig.update_yaxes(title_text=change_y_title, row=2, col=1)
    fig.update_xaxes(title_text=x_title, row=2, col=1)
    return fig


def build_hour_month_heatmap(datetime_series, values, title, colorbar_title="$ impact",
                              good_label="Saves Money", bad_label="Costs More"):
    """
    Pivot per-hour values into a 24 (hour-of-day) x 12 (month) grid, average
    per cell, and plot as a diverging heatmap centered at 0 — a fast way to
    see whether a technology's grid/customer dollar impact is predictable by
    time of day and season, rather than essentially random noise.

    Parameters
    ----------
    datetime_series : pd.Series or array-like of datetime
        Timestamp for each hour.
    values : np.ndarray
        Per-hour value to average within each (hour, month) cell (e.g.
        hourly grid $ impact or customer bill $ impact). Positive = good
        (savings/value created), negative = bad (cost increase).
    title : str
    colorbar_title : str
    good_label, bad_label : str
        Explicit labels placed directly on the colorbar's high/low ends, so
        "which color is good" doesn't depend on a caption above the chart.

    Returns
    -------
    go.Figure
    """
    dts = pd.to_datetime(pd.Series(np.asarray(datetime_series)).reset_index(drop=True))
    df = pd.DataFrame({"month": dts.dt.month.to_numpy(), "hour": dts.dt.hour.to_numpy(),
                        "value": np.asarray(values, dtype=float)})
    pivot = df.groupby(["hour", "month"])["value"].mean().unstack("month")
    pivot = pivot.reindex(index=range(24), columns=range(1, 13))

    month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    z = pivot.to_numpy()
    finite_z = z[np.isfinite(z)]
    zmax = float(np.nanmax(np.abs(finite_z))) if finite_z.size > 0 else 1.0
    zmax = zmax or 1.0

    fig = go.Figure(go.Heatmap(
        z=z, x=month_labels, y=list(range(24)),
        colorscale="RdYlGn", zmid=0, zmin=-zmax, zmax=zmax,
        colorbar=dict(
            title=dict(text=colorbar_title),
            thickness=14,
            tickvals=[-zmax, 0, zmax],
            ticktext=[f"▼ {bad_label}", "$0", f"▲ {good_label}"],
        ),
        hovertemplate="Month: %{x}<br>Hour: %{y}:00<br>Avg: %{z:.3f}<extra></extra>"
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        template="plotly_white",
        height=440,
        margin=dict(l=50, r=20, t=50, b=40),
        yaxis=dict(title="Hour of Day", autorange="reversed", dtick=2),
        xaxis=dict(title="Month"),
    )
    return fig


def build_day_hour_heatmap(datetime_series, values, title, colorbar_title="$ impact",
                            good_label="Saves Money", bad_label="Costs More"):
    """
    The single-month counterpart to build_hour_month_heatmap: pivot per-hour
    values into a 24 (hour-of-day) x N (day-of-month) grid instead of
    averaging days away into one column per month. `datetime_series` is
    expected to already be filtered down to one calendar month — if it spans
    multiple months, cells are averaged across whichever days share the same
    day-of-month number, which is rarely what's wanted here.

    Parameters mirror build_hour_month_heatmap.

    Returns
    -------
    go.Figure
    """
    dts = pd.to_datetime(pd.Series(np.asarray(datetime_series)).reset_index(drop=True))
    df = pd.DataFrame({"day": dts.dt.day.to_numpy(), "hour": dts.dt.hour.to_numpy(),
                        "value": np.asarray(values, dtype=float)})
    n_days = int(df["day"].max()) if len(df) else 31
    pivot = df.groupby(["hour", "day"])["value"].mean().unstack("day")
    pivot = pivot.reindex(index=range(24), columns=range(1, n_days + 1))

    z = pivot.to_numpy()
    finite_z = z[np.isfinite(z)]
    zmax = float(np.nanmax(np.abs(finite_z))) if finite_z.size > 0 else 1.0
    zmax = zmax or 1.0

    fig = go.Figure(go.Heatmap(
        z=z, x=list(range(1, n_days + 1)), y=list(range(24)),
        colorscale="RdYlGn", zmid=0, zmin=-zmax, zmax=zmax,
        colorbar=dict(
            title=dict(text=colorbar_title),
            thickness=14,
            tickvals=[-zmax, 0, zmax],
            ticktext=[f"▼ {bad_label}", "$0", f"▲ {good_label}"],
        ),
        hovertemplate="Day: %{x}<br>Hour: %{y}:00<br>Value: %{z:.3f}<extra></extra>"
    ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=14)),
        template="plotly_white",
        height=440,
        margin=dict(l=50, r=20, t=50, b=40),
        yaxis=dict(title="Hour of Day", autorange="reversed", dtick=2),
        xaxis=dict(title="Day of Month", dtick=2),
    )
    return fig


def build_cumulative_cost_chart(datetime_series, utility_net_hr, baseline_customer_cost,
                                 proposed_customer_cost, utility_row_title="Utility Perspective"):
    """
    Two-row chart of the running cumulative dollar DIFFERENCE (Proposed
    minus Baseline, utility-side netting already applied by the caller)
    across the year, one row per perspective: utility (top) and
    customer/occupant (bottom). Each line starts at $0 on Jan 1 and adds up
    hour by hour, so a line's value at any date is the net cumulative
    operating effect Proposed has had so far that year relative to
    Baseline — negative (green, filled below zero) means a net benefit to
    that perspective so far, positive (red, filled above zero) means a net
    cost — and its value on Dec 31 is the full annual net difference. This
    is purely the year's energy-usage cash flow; it intentionally excludes
    one-time capital costs (equipment, incentive, admin) — see the
    Lifetime Cash Flow tab for those. A filled area (rather than discrete
    bars/stems) is appropriate here because a cumulative sum is smooth by
    construction, not spiky per-hour data, so it doesn't have the
    density/legibility problems a raw hourly series would.

    The top row's `utility_net_hr` is caller-supplied rather than computed
    here, since which costs/benefits belong in the utility's net position
    depends on which cost-effectiveness test the caller wants (e.g. RIM:
    grid savings minus lost retail revenue; TRC: grid savings alone, with
    no retail-revenue netting) — this function just cumulatively sums and
    plots whatever signed hourly series it's given. The bottom row is
    always the customer's complete, un-netted experience (their whole bill
    difference), so it takes raw Baseline/Proposed arrays directly.

    Parameters
    ----------
    datetime_series : pd.Series or array-like of datetime
        Timestamp for each hour (assumed already in chronological order).
    utility_net_hr : np.ndarray
        Hourly utility net cash-flow difference ($/hr), Proposed-minus-
        Baseline sign convention (negative = benefit to the utility that
        hour), already netted by the caller under whichever cost-
        effectiveness test basis is selected.
    baseline_customer_cost, proposed_customer_cost : np.ndarray
        Hourly customer retail bill cost ($/hr) for Baseline and Proposed.
    utility_row_title : str
        Subplot title for row 1, naming which cost basis is in use.

    Returns
    -------
    go.Figure
    """
    dts = pd.to_datetime(pd.Series(np.asarray(datetime_series)).reset_index(drop=True))

    utility_net_cum = np.cumsum(np.asarray(utility_net_hr, dtype=float))
    cust_diff = np.asarray(proposed_customer_cost, dtype=float) - np.asarray(baseline_customer_cost, dtype=float)
    cust_diff_cum = np.cumsum(cust_diff)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.12,
        subplot_titles=(utility_row_title,
                         "Customer / Occupant Perspective (Retail Bill Basis)")
    )

    def _add_signed_diff(values, row, show_legend):
        neg_vals = np.where(values < 0, values, np.nan)
        pos_vals = np.where(values >= 0, values, np.nan)
        fig.add_trace(go.Scatter(
            x=dts, y=neg_vals, name="Cumulative Savings", mode="lines",
            line=dict(color=COLORS["green"], width=2), fill="tozeroy",
            fillcolor=_rgba(COLORS["green"], 0.3), connectgaps=False, showlegend=show_legend
        ), row=row, col=1)
        fig.add_trace(go.Scatter(
            x=dts, y=pos_vals, name="Cumulative Added Cost", mode="lines",
            line=dict(color=COLORS["red"], width=2), fill="tozeroy",
            fillcolor=_rgba(COLORS["red"], 0.3), connectgaps=False, showlegend=show_legend
        ), row=row, col=1)
        fig.add_hline(y=0, row=row, col=1, line_width=1, line_color="rgba(100,100,100,0.5)")

    _add_signed_diff(utility_net_cum, row=1, show_legend=True)
    _add_signed_diff(cust_diff_cum, row=2, show_legend=False)

    fig.update_layout(
        template="plotly_white",
        height=560,
        margin=dict(l=50, r=20, t=50, b=40),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    fig.update_yaxes(title_text="Cumulative Utility Net Position ($)", row=1, col=1)
    fig.update_yaxes(title_text="Cumulative Bill Difference ($)", row=2, col=1)
    fig.update_xaxes(title_text="Date", row=2, col=1)
    return fig




