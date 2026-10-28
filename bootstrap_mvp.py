import os
from pathlib import Path

# تعریف ساختار فایل‌ها و محتوای معماری فاز ۱ (مبتنی بر قرارداد داده و کیفیت)
PROJECT_FILES = {
    ".gitignore": """# Python & Environment
__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
env/
.env

# Streamlit & Secrets
.streamlit/secrets.toml

# OS & IDE
.DS_Store
.vscode/
.idea/

# Temporary Data & Cache
*.tmp
temp_uploads/
""",

    "requirements.txt": """streamlit>=1.38.0
pandas>=2.2.0
python-calamine>=0.2.0
openpyxl>=3.1.2
persiantools>=4.0.0
pydantic>=2.8.0
plotly>=5.22.0
scipy>=1.13.0
numpy>=1.26.0
""",

    "core/__init__.py": "",

    "core/contracts.py": """from typing import Literal, List, Optional
from pydantic import BaseModel, Field

class DataQualityReport(BaseModel):
    total_raw_rows: int
    valid_detail_rows: int
    suspected_total_rows: int
    empty_rows_dropped: int
    invalid_dates_count: int
    unparseable_numbers_count: int
    warnings: List[str] = Field(default_factory=list)
    is_gate_passed: bool = True

class KPISpec(BaseModel):
    kpi_column: str
    time_column: str
    category_column: str
    aggregation: Literal["SUM", "MEAN", "MEDIAN", "COUNT"] = "SUM"
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"

class EvidenceItem(BaseModel):
    evidence_id: str
    category_value: str
    metric_name: str
    observed_value: float
    baseline_value: float
    deviation_pct: float
    detection_method: str
    severity: Literal["high", "medium", "low"]
    description_fa: str
""",

    "core/ingestion_quality.py": """import re
import pandas as pd
import numpy as np
from functools import lru_cache
from persiantools.jdatetime import JalaliDate
from core.contracts import DataQualityReport

# جدول تبدیل سریع ارقام فارسی و عربی به انگلیسی
DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

def normalize_persian_text(series: pd.Series) -> pd.Series:
    s = series.astype("string").str.strip()
    s = s.str.translate(DIGIT_MAP)
    s = s.str.replace("ي", "ی").str.replace("ك", "ک")
    s = s.str.replace(r"[\\u200c\\u200e\\u200f]", " ", regex=True)
    return s.str.replace(r"\\s+", " ", regex=True).str.strip()

def clean_currency_and_numbers(series: pd.Series) -> tuple[pd.Series, int]:
    s = series.astype("string").str.translate(DIGIT_MAP).str.strip()
    # تبدیل اعداد منفی داخل پرانتز مثل (۱۲۰۰) به -1200
    s = s.str.replace(r"^\\((.*)\\)$", r"-\\1", regex=True)
    # حذف کلمات رایج مالی و جداکننده‌های هزارگان
    s = s.str.replace(r"(ریال|تومان|,|٬|_| )", "", regex=True)
    numeric_series = pd.to_numeric(s, errors="coerce")
    unparseable = int(series.notna().sum() - numeric_series.notna().sum())
    return numeric_series, max(0, unparseable)

@lru_cache(maxsize=100_000)
def _cached_jalali_to_gregorian(y: int, m: int, d: int) -> Optional[str]:
    try:
        return JalaliDate(y, m, d).to_gregorian().isoformat()
    except ValueError:
        return None

def parse_jalali_vectorized(series: pd.Series) -> tuple[pd.Series, int]:
    s = normalize_persian_text(series)
    s = s.str.replace(r"[-\\.]", "/", regex=True)
    extracted = s.str.extract(r"^(\\d{4})/(\\d{1,2})/(\\d{1,2})")
    
    valid_mask = extracted.notna().all(axis=1)
    unique_dates = extracted[valid_mask].drop_duplicates()
    
    date_map = {}
    for _, row in unique_dates.iterrows():
        y, m, d = int(row[0]), int(row[1]), int(row[2])
        # اگر سال ۲ رقمی بود (مثلاً 04 به جای 1404)
        if y < 100:
            y += 1400
        greg_iso = _cached_jalali_to_gregorian(y, m, d)
        date_map[(row[0], row[1], row[2])] = greg_iso

    keys = list(zip(extracted[0], extracted[1], extracted[2]))
    mapped_iso = [date_map.get(k, None) for k in keys]
    dt_series = pd.to_datetime(mapped_iso, errors="coerce")
    invalid_count = int(series.notna().sum() - dt_series.notna().sum())
    return dt_series, max(0, invalid_count)

def inspect_and_sanitize_excel(file_obj) -> tuple[pd.DataFrame, DataQualityReport]:
    # استفاده از موتور سریع calamine در صورت امکان
    try:
        df_raw = pd.read_excel(file_obj, engine="calamine")
    except Exception:
        file_obj.seek(0)
        df_raw = pd.read_excel(file_obj)

    total_raw = len(df_raw)
    df = df_raw.dropna(how="all").copy()
    empty_dropped = total_raw - len(df)

    # استانداردسازی نام ستون‌ها
    df.columns = [str(c).strip().replace("ي", "ی").replace("ك", "ک") for c in df.columns]

    # تشخیص ردیف‌های خطرناک «جمع کل» یا «میانگین» در میانه جدول
    row_text = df.astype(str).agg(" ".join, axis=1)
    total_pattern = r"(جمع کل|مجموع|میانگین کل|کل شعب|Grand Total|Subtotal)"
    suspected_mask = row_text.str.contains(total_pattern, case=False, regex=True)
    
    df["_row_type"] = np.where(suspected_mask, "suspected_total", "detail")
    suspected_count = int(suspected_mask.sum())

    warnings = []
    if suspected_count > 0:
        warnings.append(f"{suspected_count} ردیف مشکوک به «جمع کل/میانگین» شناسایی و از محاسبات اصلی ایزوله شد تا از خطای دوباره‌شماری جلوگیری شود.")

    report = DataQualityReport(
        total_raw_rows=total_raw,
        valid_detail_rows=int((df["_row_type"] == "detail").sum()),
        suspected_total_rows=suspected_count,
        empty_rows_dropped=empty_dropped,
        invalid_dates_count=0,
        unparseable_numbers_count=0,
        warnings=warnings
    )
    return df, report
""",

    "core/analytics_engine.py": """import pandas as pd
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
        is_bad_anomaly = (spec.direction == "higher_is_better" and z < -2.0) or \\
                         (spec.direction == "lower_is_better" and z > 2.0)
        is_good_outlier = (spec.direction == "higher_is_better" and z > 2.5) or \\
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
""",

    "generate_dirty_sample.py": """import pandas as pd

def create_dirty_iranian_excel():
    data = [
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۱", "نام شعبه": "شعبه ونک", "تعداد تراکنش": "1,250", "مبلغ فروش (ریال)": "4,500,000,000 ریال"},
        {"تاریخ تراکنش": "1404-07-02", "نام شعبه": "شعبه ونک", "تعداد تراکنش": "1,310", "مبلغ فروش (ریال)": "4,800,000,000"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۱", "نام شعبه": "شعبه مطهری", "تعداد تراکنش": "980", "مبلغ فروش (ریال)": "3,200,000,000 ریال"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۲", "نام شعبه": "شعبه مطهری", "تعداد تراکنش": "1,020", "مبلغ فروش (ریال)": "3,400,000,000"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۱", "نام شعبه": "شعبه سعادت‌آباد", "تعداد تراکنش": "1,100", "مبلغ فروش (ریال)": "3,900,000,000"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۲", "نام شعبه": "شعبه سعادت‌آباد", "تعداد تراکنش": "1,150", "مبلغ فروش (ریال)": "4,100,000,000"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۱", "نام شعبه": "شعبه فردوسی", "تعداد تراکنش": "1,050", "مبلغ فروش (ریال)": "3,700,000,000"},
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۲", "نام شعبه": "شعبه فردوسی", "تعداد تراکنش": "990", "مبلغ فروش (ریال)": "3,600,000,000"},
        # ردیف ناهنجار (افت شدید عملکرد در شعبه انقلاب)
        {"تاریخ تراکنش": "۱۴۰۴/۰۷/۰۱", "نام شعبه": "شعبه انقلاب", "تعداد تراکنش": "120", "مبلغ فروش (ریال)": "350,000,000 ریال"},
        {"تاریخ تراکنش": "۱۴۰۴/۱۲/۳۱", "نام شعبه": "شعبه انقلاب", "تعداد تراکنش": "95", "مبلغ فروش (ریال)": "280,000,000"}, # تاریخ نامعتبر کبیسه!
        # تله رایج در اکسل‌های ایران: ردیف جمع کل در وسط یا انتهای جدول!
        {"تاریخ تراکنش": "-", "نام شعبه": "جمع کل شعب تهران", "تعداد تراکنش": "8,065", "مبلغ فروش (ریال)": "31,830,000,000 ریال"},
    ]
    df = pd.DataFrame(data)
    df.to_excel("sample_dirty_branches.xlsx", index=False)
    print("فایل تستی sample_dirty_branches.xlsx با موفقیت ساخته شد.")

if __name__ == "__main__":
    create_dirty_iranian_excel()
""",

    "app.py": """import streamlit as st
import pandas as pd
import plotly.express as px
from core.contracts import KPISpec
from core.ingestion_quality import inspect_and_sanitize_excel, clean_currency_and_numbers, parse_jalali_vectorized
from core.analytics_engine import run_deterministic_radar

st.set_page_config(page_title="رادار عیب‌یاب عملکرد و عملیات", layout="wide")
st.title("🛡️ رادار عیب‌یاب عملکرد و عملیات (نسخه MVP - فاز ۱)")
st.caption("مبتنی بر معماری جداسازی محاسبه قطعی از استنتاج زبانی و دروازه کیفیت داده")

uploaded_file = st.file_uploader("فایل اکسل عملیاتی خود را آپلود کنید (یا فایل sample_dirty_branches.xlsx را تست کنید)", type=["xlsx", "xls"])

if uploaded_file:
    df_raw, q_report = inspect_and_sanitize_excel(uploaded_file)
    
    st.subheader("۱. دروازه کیفیت داده (Data Quality Gate)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("کل ردیف‌های فایل", q_report.total_raw_rows)
    col2.metric("ردیف‌های معتبر عملیاتی", q_report.valid_detail_rows)
    col3.metric("ردیف‌های جمع‌کل ایزوله‌شده", q_report.suspected_total_rows)
    col4.metric("ردیف‌های خالی حذف‌شده", q_report.empty_rows_dropped)
    
    for w in q_report.warnings:
        st.warning(f"⚠️ {w}")

    with st.expander("مشاهده پیش‌نمایش داده‌ها و ردیف‌های علامت‌گذاری شده"):
        st.dataframe(df_raw, use_container_width=True)

    st.divider()
    st.subheader("۲. قرارداد معنایی شاخص (Semantic Layer)")
    cols = [c for c in df_raw.columns if c != "_row_type"]
    
    c1, c2, c3, c4, c5 = st.columns(5)
    cat_col = c1.selectbox("ستون دسته‌بندی (شعبه/واحد)", cols, index=min(1, len(cols)-1))
    kpi_col = c2.selectbox("ستون شاخص هدف (KPI)", cols, index=min(3, len(cols)-1))
    time_col = c3.selectbox("ستون تاریخ شمسی", cols, index=0)
    agg_func = c4.selectbox("نحوه تجمیع", ["SUM", "MEAN", "MEDIAN", "COUNT"])
    direction = c5.selectbox("جهت مطلوبیت شاخص", ["higher_is_better", "lower_is_better"], 
                             format_func=lambda x: "بیشتر بهتر است (مثل فروش)" if x == "higher_is_better" else "کمتر بهتر است (مثل خطا/زمان)")

    if st.button("🚀 اجرای رادار محاسباتی و استخراج کاتالوگ شواهد", type="primary"):
        df_work = df_raw.copy()
        df_work[kpi_col], bad_nums = clean_currency_and_numbers(df_work[kpi_col])
        df_work["_parsed_date"], bad_dates = parse_jalali_vectorized(df_work[time_col])

        if bad_dates > 0 or bad_nums > 0:
            st.info(f"🔍 گزارش استانداردسازی: {bad_dates} تاریخ شمسی نامعتبر/خالی و {bad_nums} مقدار غیرعددی شناسایی شد.")

        spec = KPISpec(
            kpi_column=kpi_col,
            time_column=time_col,
            category_column=cat_col,
            aggregation=agg_func,
            direction=direction
        )
        
        grouped_df, evidences = run_deterministic_radar(df_work, spec)

        st.divider()
        st.subheader("۳. کاتالوگ شواهد قطعی (Evidence Catalog) و تحلیل پارتو")
        
        left, right = st.columns([1, 1])
        with left:
            st.markdown("##### 🚨 شواهد و ناهنجاری‌های کشف‌شده (بر اساس معیار مقاوم MAD)")
            if not evidences:
                st.success("هیچ ناهنجاری شدیدی خارج از آستانه استاندارد شناسایی نشد.")
            for ev in evidences:
                st.error(f"**[{ev.evidence_id}]** {ev.description_fa}")
                
        with right:
            fig = px.bar(grouped_df, x=cat_col, y=kpi_col, text_auto=".2s",
                         title=f"توزیع و رتبه‌بندی {kpi_col} به تفکیک {cat_col} (بدون احتساب ردیف‌های جمع کل)")
            st.plotly_chart(fig, use_container_width=True)
"""
}

def build_project():
    for filepath, content in PROJECT_FILES.items():
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"✅ Created: {filepath}")
    print("\n🎉 ساختار پروژه با موفقیت ساخته شد!")

if __name__ == "__main__":
    build_project()