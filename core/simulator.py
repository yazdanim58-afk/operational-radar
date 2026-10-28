import pandas as pd
from core.contracts import KPISpec

def run_what_if_simulation(grouped_df, spec, percentage_change):
    sim_df = grouped_df.copy()
    multiplier = 1.0 + (percentage_change / 100.0)
    sim_df["simulated_" + spec.kpi_column] = sim_df[spec.kpi_column] * multiplier
    total_kpi = sim_df["simulated_" + spec.kpi_column].sum()
    sim_df["simulated_share_pct"] = (sim_df["simulated_" + spec.kpi_column] / total_kpi * 100) if total_kpi else 0
    return sim_df
