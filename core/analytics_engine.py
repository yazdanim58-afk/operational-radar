import pandas as pd
import numpy as np
from typing import List
from core.contracts import KPISpec, EvidenceItem

def run_deterministic_radar(df: pd.DataFrame, spec: KPISpec) -> tuple[pd.DataFrame, List[EvidenceItem]]:
    # فقط ردیف‌های معتبر (detail) وارد محاسبه می‌شوند
    clean_df = df[df["_row_type"] == "detail"].copy()
    
    # تجمیع بر اساس دسته‌بندی (مثلاً شعبه یا واحد)
    if spec.aggregation == "SUM":
        grouped = clean_df.groupby(spec.category_column, as_index=False)[spec.kpi_column].sum()
    elif spec.aggregation == "MEAN":
        grouped = clean_df.groupby(spec.category_column, as_index=False)[spec.kpi_column].mean()
    elif spec.aggregation == "MEDIAN":
        grouped = clean_df.groupby(spec.category_column, as_index=False)[spec.kpi_column].median()
    else:
        grouped = clean_df.groupby(spec.category_column, as_index=False)[spec.kpi_column].count()

    # محاسبه شاخص مقاوم میانه و انحراف مطلق از میانه (MAD) به جای میانگین ساده
    values = grouped[spec.kpi_column].dropna()
    median_val = float(values.median())
    mad_val = float(np.median(np.abs(values - median_val)))
    
    # ضریب استاندارد برای توزیع نرمال در MAD برابر 1.4826 است
    robust_sigma = mad_val * 1.4826 if mad_val > 0 else float(values.std() or 1.0)
    grouped["robust_z"] = (grouped[spec.kpi_column] - median_val) / robust_sigma
    
    # محاسبه سهم پارتو (80/20)
    total_kpi = grouped[spec.kpi_column].sum()
    grouped = grouped.sort_values(by=spec.kpi_column, ascending=False).reset_index(drop=True)
    grouped["share_pct"] = (grouped[spec.kpi_column] / total_kpi * 100) if total_kpi else 0
    grouped["cumulative_share_pct"] = grouped["share_pct"].cumsum()

    evidences: List[EvidenceItem] = []
    ev_counter = 1
    for _, row in grouped.iterrows():
        z = float(row["robust_z"])
        val = float(row[spec.kpi_column])
        cat = str(row[spec.category_column])
        dev_pct = ((val - median_val) / median_val * 100) if median_val != 0 else 0.0

        # تشخیص ناهنجاری بر اساس جهت مطلوبیت شاخص
        is_bad_anomaly = (spec.direction == "higher_is_better" and z < -2.0) or \
                         (spec.direction == "lower_is_better" and z > 2.0)
        is_good_outlier = (spec.direction == "higher_is_better" and z > 2.5) or \
                          (spec.direction == "lower_is_better" and z < -2.5)

        if is_bad_anomaly or is_good_outlier:
            sev = "high" if abs(z) > 3.0 else "medium"
            status_fa = "انحراف نامطلوب شدید (گلوگاه)" if is_bad_anomaly else "عملکرد استثنایی (نقطه قوت)"
            evidences.append(EvidenceItem(
                evidence_id=f"EV-{ev_counter:02d}",
                category_value=cat,
                metric_name=spec.kpi_column,
                observed_value=round(val, 2),
                baseline_value=round(median_val, 2),
                deviation_pct=round(dev_pct, 1),
                detection_method="Robust MAD Z-Score",
                severity=sev,
                description_fa=f"{status_fa} در «{cat}»: مقدار مشاهده‌شده ({val:,.0f}) دارای {dev_pct:+.1f}% انحراف نسبت به خط مبنای میانه ({median_val:,.0f}) است."
            ))
            ev_counter += 1

    return grouped, evidences
