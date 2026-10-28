import pandas as pd

def run_cross_market_comparison(df, group_col, kpi_col, group1, group2):
    sub1 = df[df[group_col] == group1][kpi_col].sum()
    sub2 = df[df[group_col] == group2][kpi_col].sum()
    diff = sub2 - sub1
    pct_growth = (diff / sub1 * 100) if sub1 else 0
    return {"group1": group1, "val1": sub1, "group2": group2, "val2": sub2, "diff": diff, "growth_pct": pct_growth}
