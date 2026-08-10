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
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from config import GRID_COMPONENTS, COLORS


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
