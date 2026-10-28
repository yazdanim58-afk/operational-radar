import streamlit as st
import pandas as pd
import plotly.express as px
from core.contracts import KPISpec
from core.ingestion_quality import (
    inspect_and_sanitize_excel,
    clean_currency_and_numbers,
    parse_jalali_vectorized
)
from core.analytics_engine import run_deterministic_radar

st.set_page_config(page_title="رادار عیب‌یاب عملکرد و عملیات", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;800&display=swap');

html, body, [class*="css"], .stMarkdown, .stButton button, .stSelectbox, .stAlert {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}
.main .block-container {
    direction: rtl;
    text-align: right;
}
h1, h2, h3, h4, h5, h6, p, label, .stCaption {
    direction: rtl !important;
    text-align: right !important;
    font-family: 'Vazirmatn', sans-serif !important;
}
div[data-testid="stMetric"] {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-right: 5px solid #3b82f6;
    border-radius: 10px;
    padding: 15px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    direction: rtl;
    text-align: right;
}
div[data-testid="stMetricLabel"] {
    font-weight: 700 !important;
    color: #475569 !important;
}
div[data-baseweb="select"], div[data-testid="stAlert"], div[data-testid="stExpander"] {
    direction: rtl;
    text-align: right;
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    "<h1 style='color:#0f172a; margin-bottom:0;'>🛡️ رادار عیب‌یاب عملکرد و عملیات "
    "<span style='font-size:1.2rem; color:#3b82f6;'>(نسخه MVP - فاز ۱)</span></h1>",
    unsafe_allow_html=True
)
st.caption("معماری ترکیبی: جداسازی محاسبات قطعی پایتون از استنتاج هوش مصنوعی به همراه دروازه کیفیت داده")
st.markdown("---")

uploaded_file = st.file_uploader(
    "📂 فایل اکسل عملیاتی خود را بارگذاری کنید (پیشنهاد تستی: sample_dirty_branches.xlsx)",
    type=["xlsx", "xls"]
)

if uploaded_file:
    df_raw, q_report = inspect_and_sanitize_excel(uploaded_file)

    st.markdown("### ۱. دروازه کیفیت داده (Data Quality Gate)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("کل ردیف‌های فایل", f"{q_report.total_raw_rows:,}")
    col2.metric("ردیف‌های معتبر عملیاتی", f"{q_report.valid_detail_rows:,}")
    col3.metric("ردیف‌های جمع‌کل ایزوله‌شده", f"{q_report.suspected_total_rows:,}")
    col4.metric("ردیف‌های خالی حذف‌شده", f"{q_report.empty_rows_dropped:,}")

    for w in q_report.warnings:
        st.warning(f"⚠️ {w}")

    with st.expander("🔍 مشاهده پیش‌نمایش داده‌ها و ردیف‌های علامت‌گذاری شده"):
        st.dataframe(df_raw, use_container_width=True)

    st.markdown("---")
    st.markdown("### ۲. قرارداد معنایی شاخص (Semantic Layer)")
    cols = [c for c in df_raw.columns if c != "_row_type"]

    c1, c2, c3, c4, c5 = st.columns(5)
    cat_col = c1.selectbox("ستون دسته‌بندی (شعبه/واحد)", cols, index=min(1, len(cols)-1))
    kpi_col = c2.selectbox("ستون شاخص هدف (KPI)", cols, index=min(3, len(cols)-1))
    time_col = c3.selectbox("ستون تاریخ شمسی", cols, index=0)
    agg_map = {"SUM": "مجموع (SUM)", "MEAN": "میانگین (MEAN)", "MEDIAN": "میانه (MEDIAN)", "COUNT": "تعداد (COUNT)"}
    agg_func = c4.selectbox("نحوه تجمیع ریاضی", list(agg_map.keys()), format_func=lambda x: agg_map[x])
    direction = c5.selectbox(
        "جهت مطلوبیت شاخص",
        ["higher_is_better", "lower_is_better"],
        format_func=lambda x: "بیشتر بهتر است (فروش)" if x == "higher_is_better" else "کمتر بهتر است (خطا/هزینه)"
    )

    if st.button("🚀 اجرای رادار محاسباتی و استخراج کاتالوگ شواهد", type="primary", use_container_width=True):
        df_work = df_raw.copy()
        df_work[kpi_col], bad_nums = clean_currency_and_numbers(df_work[kpi_col])
        df_work["_parsed_date"], bad_dates = parse_jalali_vectorized(df_work[time_col])

        if bad_dates > 0 or bad_nums > 0:
            st.info(
                f"📋 گزارش استانداردسازی: {bad_dates} تاریخ نامعتبر/خالی و "
                f"{bad_nums} مقدار غیرعددی شناسایی و مدیریت شد."
            )

        spec = KPISpec(
            kpi_column=kpi_col,
            time_column=time_col,
            category_column=cat_col,
            aggregation=agg_func,
            direction=direction
        )
        grouped_df, evidences = run_deterministic_radar(df_work, spec)

        st.markdown("---")
        st.markdown("### ۳. کاتالوگ شواهد قطعی (Evidence Catalog) و توزیع عملکرد")
        col_ev, col_chart = st.columns([1, 1.2])

        with col_ev:
            st.markdown("##### 🚨 شواهد و ناهنجاری‌های کشف‌شده (معیار مقاوم MAD)")
            if not evidences:
                st.success("✅ هیچ ناهنجاری شدیدی خارج از آستانه استاندارد شناسایی نشد.")
            for ev in evidences:
                st.error(f"**کد شاهد [{ev.evidence_id}]** — {ev.description_fa}")

            st.markdown("##### 📊 جدول رتبه‌بندی و سهم پارتو (80/20)")
            disp = grouped_df[[cat_col, kpi_col, "share_pct", "cumulative_share_pct", "robust_z"]].copy()
            disp.columns = [cat_col, kpi_col, "سهم (%)", "سهم تجمعی (%)", "انحراف (Z)"]
            st.dataframe(disp.style.format({
                kpi_col: "{:,.0f}",
                "سهم (%)": "{:.1f}%",
                "سهم تجمعی (%)": "{:.1f}%",
                "انحراف (Z)": "{:+.2f}"
            }), use_container_width=True)

        with col_chart:
            scale = "RdYlGn" if direction == "higher_is_better" else "RdYlGn_r"
            chart_title = f"رتبه‌بندی {kpi_col} به تفکیک {cat_col} (خالص‌شده)"
            fig = px.bar(
                grouped_df, x=cat_col, y=kpi_col, text_auto=".3s",
                color="robust_z", color_continuous_scale=scale, title=chart_title
            )
            fig.update_layout(font=dict(family="Vazirmatn, Tahoma", size=13), title_x=0.5)
            st.plotly_chart(fig, use_container_width=True)
