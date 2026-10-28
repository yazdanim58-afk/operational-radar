import io
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
from core.simulator import run_what_if_simulation
from core.llm_service import generate_safe_egress_payload, mock_llm_cognitive_analysis

st.set_page_config(page_title="رادار عیب‌یاب عملیاتی Enterprise", page_icon="🛡️", layout="wide")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@300;400;500;700;800&display=swap');
html, body, [class*="css"], .stMarkdown, .stButton button, .stSelectbox, .stAlert, .stTabs {
    font-family: 'Vazirmatn', Tahoma, sans-serif !important;
}
.main .block-container { direction: rtl; text-align: right; }
h1, h2, h3, h4, h5, h6, p, label, .stCaption {
    direction: rtl !important; text-align: right !important;
    font-family: 'Vazirmatn', sans-serif !important;
}
div[data-testid="stMetric"] {
    background-color: #f8fafc; border: 1px solid #e2e8f0;
    border-right: 5px solid #2563eb; border-radius: 10px;
    padding: 15px 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    direction: rtl; text-align: right;
}
div[data-baseweb="select"], div[data-testid="stAlert"], div[data-testid="stExpander"] {
    direction: rtl; text-align: right;
}
</style>
""", unsafe_allow_html=True)

def smart_guess_column(cols, keywords, fallback_idx=0):
    for i, c in enumerate(cols):
        for kw in keywords:
            if kw in str(c):
                return i
    return min(fallback_idx, max(0, len(cols) - 1))

def build_excel_export(df_clean, grouped_df, evidences):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        grouped_df.to_excel(writer, sheet_name="رتبه‌بندی_و_پارتو", index=False)
        df_clean.to_excel(writer, sheet_name="داده‌های_پاکسازی‌شده", index=False)
        if evidences:
            ev_df = pd.DataFrame([e.model_dump() for e in evidences])
        else:
            ev_df = pd.DataFrame([{"وضعیت": "هیچ ناهنجاری شدیدی خارج از آستانه شناسایی نشد"}])
        ev_df.to_excel(writer, sheet_name="کاتالوگ_شواهد", index=False)
    return output.getvalue()

def build_printable_executive_report(spec, q_report, grouped_df, evidences, ai_text):
    ev_rows = "".join([
        f"<tr><td><b>{e.evidence_id}</b></td><td>{e.severity}</td><td>{e.description_fa}</td></tr>"
        for e in evidences
    ]) or "<tr><td colspan='3'>هیچ ناهنجاری بحرانی شناسایی نشد.</td></tr>"
    
    top_rows = ""
    for _, r in grouped_df.head(10).iterrows():
        top_rows += (
            f"<tr><td>{r[spec.category_column]}</td>"
            f"<td>{r[spec.kpi_column]:,.0f}</td>"
            f"<td>{r['share_pct']:.1f}%</td>"
            f"<td>{r['robust_z']:+.2f}</td></tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>گزارش مدیریتی رادار عملکرد و عملیات</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Vazirmatn:wght@400;700&display=swap');
body {{ font-family: 'Vazirmatn', Tahoma, sans-serif; direction: rtl; text-align: right; padding: 30px; color: #0f172a; line-height: 1.7; }}
.header {{ border-bottom: 3px solid #1e40af; padding-bottom: 12px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }}
.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
.card {{ background: #f8fafc; border: 1px solid #cbd5e1; border-right: 4px solid #2563eb; padding: 12px; border-radius: 8px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 24px; font-size: 13px; }}
th, td {{ border: 1px solid #cbd5e1; padding: 8px 12px; text-align: right; }}
th {{ background-color: #f1f5f9; }}
.ai-box {{ background: #eff6ff; border: 1px solid #bfdbfe; padding: 16px; border-radius: 8px; margin-top: 16px; }}
.print-btn {{ background: #2563eb; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer; font-family: inherit; font-weight: bold; }}
@media print {{ .no-print {{ display: none; }} }}
</style>
</head>
<body>
<div class="no-print" style="margin-bottom: 20px; text-align: left;">
    <button class="print-btn" onclick="window.print()">🖨️ چاپ یا ذخیره به عنوان PDF رسمی (Ctrl + P)</button>
</div>
<div class="header">
    <div>
        <h1 style="margin:0; font-size: 22px;">🛡️ گزارش رسمی رادار عیب‌یاب عملکرد و عملیات</h1>
        <p style="margin:4px 0 0 0; color:#475569;">شاخص هدف: <b>{spec.kpi_column}</b> | سطح تحلیل: <b>{spec.category_column}</b> | متد تجمیع: <b>{spec.aggregation}</b></p>
    </div>
</div>
<h3>۱. خلاصه کنترل کیفیت داده</h3>
<div class="cards">
    <div class="card">کل ردیف‌ها: <b>{q_report.total_raw_rows:,}</b></div>
    <div class="card">ردیف‌های معتبر: <b>{q_report.valid_detail_rows:,}</b></div>
    <div class="card">جمع‌کل ایزوله‌شده: <b>{q_report.suspected_total_rows:,}</b></div>
    <div class="card">ردیف خالی حذف‌شده: <b>{q_report.empty_rows_dropped:,}</b></div>
</div>
<h3>۲. کاتالوگ شواهد و ناهنجاری‌های آماری (معیار مقاوم MAD)</h3>
<table>
    <thead><tr><th>کد شاهد</th><th>سطح بحران</th><th>شرح یافته آماری</th></tr></thead>
    <tbody>{ev_rows}</tbody>
</table>
<h3>۳. جدول رتبه‌بندی و سهم پارتو (۱۰ واحد اول)</h3>
<table>
    <thead><tr><th>{spec.category_column}</th><th>مقدار ({spec.kpi_column})</th><th>سهم از کل</th><th>امتیاز انحراف (Robust Z)</th></tr></thead>
    <tbody>{top_rows}</tbody>
</table>
<h3>۴. جمع‌بندی استنتاجی و برنامه اقدام</h3>
<div class="ai-box">{ai_text.replace(chr(10), '<br>')}</div>
</body>
</html>"""
    return html.encode("utf-8")

st.markdown(
    "<h1 style='color:#0f172a; margin-bottom:0;'>🛡️ رادار عیب‌یاب عملکرد و عملیات "
    "<span style='font-size:1.15rem; color:#2563eb;'>(نسخه سازمانی Enterprise - فاز ۳)</span></h1>",
    unsafe_allow_html=True
)
st.caption("پشتیبانی از ساختارهای درختی اکسل، کاوشگر مقایسه‌ای استان‌ها/واحدها، تحلیل روند زمانی، شبیه‌ساز What-If و خروجی گزارش رسمی")
st.markdown("---")

uploaded_file = st.file_uploader("📂 فایل اکسل عملیاتی خود را بارگذاری کنید", type=["xlsx", "xls"])

if uploaded_file:
    # تنظیمات تعاملی ساختار درختی و سرستون‌ها
    with st.expander("⚙️ تنظیمات هوشمند خوانش فایل (ساختارهای درختی، سلول‌های ادغام‌شده و ردیف سرستون)", expanded=False):
        hc1, hc2 = st.columns(2)
        header_row_idx = hc1.number_input("شماره ردیف سرستون اصلی (0 = ردیف اول):", min_value=0, max_value=15, value=0, step=1)
        enable_ffill = hc2.checkbox(
            "پر کردن خودکار سلول‌های ادغام‌شده و درختی (Forward-Fill برای سرگروه‌ها/استان‌ها)",
            value=True,
            help="اگر فایل شما دارای سلول‌های Merge شده در ستون استان، منطقه یا تاریخ است، این گزینه زیرگروه‌ها را به صورت خودکار تکمیل می‌کند."
        )

    uploaded_file.seek(0)
    df_raw, q_report = inspect_and_sanitize_excel(uploaded_file)

    # اعمال تخت‌سازی ساختار درختی روی ستون‌های متنی/دسته‌ای در صورت فعال بودن
    if enable_ffill:
        obj_cols = [c for c in df_raw.columns if c != "_row_type" and df_raw[c].dtype == "object"]
        df_raw[obj_cols] = df_raw[obj_cols].ffill()

    st.markdown("### ۱. دروازه کیفیت داده (Data Quality Gate)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("کل ردیف‌های فایل", f"{q_report.total_raw_rows:,}")
    col2.metric("ردیف‌های معتبر عملیاتی", f"{q_report.valid_detail_rows:,}")
    col3.metric("ردیف‌های جمع‌کل ایزوله‌شده", f"{q_report.suspected_total_rows:,}")
    col4.metric("ردیف‌های خالی حذف‌شده", f"{q_report.empty_rows_dropped:,}")

    for w in q_report.warnings:
        st.warning(f"⚠️ {w}")

    with st.expander("🔍 پیش‌نمایش داده‌های استانداردشده و ساختار درختی تکمیل‌شده"):
        st.dataframe(df_raw, use_container_width=True)

    st.markdown("---")
    st.markdown("### ۲. تشخیص هوشمند ستون‌ها و قرارداد معنایی شاخص (Smart Semantic Layer)")
    cols = [c for c in df_raw.columns if c != "_row_type"]

    default_cat = smart_guess_column(cols, ["شعبه", "استان", "واحد", "منطقه", "نام", "مرکز", "بخش"], 1)
    default_kpi = smart_guess_column(cols, ["مبلغ", "فروش", "درآمد", "تعداد", "عملکرد", "ریال", "ارزش", "هزینه"], min(3, len(cols)-1))
    default_time = smart_guess_column(cols, ["تاریخ", "ماه", "دوره", "سال", "فصل", "روز", "زمان"], 0)

    c1, c2, c3, c4, c5 = st.columns(5)
    cat_col = c1.selectbox("ستون دسته‌بندی اصلی (شعبه/استان)", cols, index=default_cat)
    kpi_col = c2.selectbox("ستون شاخص هدف (KPI)", cols, index=default_kpi)
    time_col = c3.selectbox("ستون تاریخ یا دوره زمانی", cols, index=default_time)
    agg_map = {"SUM": "مجموع (SUM)", "MEAN": "میانگین (MEAN)", "MEDIAN": "میانه (MEDIAN)", "COUNT": "تعداد (COUNT)"}
    agg_func = c4.selectbox("نحوه تجمیع ریاضی", list(agg_map.keys()), format_func=lambda x: agg_map[x])
    direction = c5.selectbox(
        "جهت مطلوبیت شاخص",
        ["higher_is_better", "lower_is_better"],
        format_func=lambda x: "بیشتر بهتر است (فروش)" if x == "higher_is_better" else "کمتر بهتر است (خطا/هزینه)"
    )

    if st.button("🚀 اجرای رادار محاسباتی و فعال‌سازی داشبوردهای تحلیلی", type="primary", use_container_width=True):
        df_work = df_raw[df_raw["_row_type"] == "DETAIL"].copy()
        df_work[kpi_col], bad_nums = clean_currency_and_numbers(df_work[kpi_col])
        df_work["_parsed_date"], bad_dates = parse_jalali_vectorized(df_work[time_col])

        spec = KPISpec(
            kpi_column=kpi_col, time_column=time_col,
            category_column=cat_col, aggregation=agg_func, direction=direction
        )
        # ارسال کل df_raw به موتور رادار چون خودش فیلتر DETAIL را انجام می‌دهد
        df_for_radar = df_raw.copy()
        df_for_radar[kpi_col], _ = clean_currency_and_numbers(df_for_radar[kpi_col])
        grouped_df, evidences = run_deterministic_radar(df_for_radar, spec)

        st.session_state["grouped_df"] = grouped_df
        st.session_state["evidences"] = evidences
        st.session_state["spec"] = spec
        st.session_state["df_work"] = df_work
        st.session_state["q_report"] = q_report

    if "grouped_df" in st.session_state:
        grouped_df = st.session_state["grouped_df"]
        evidences = st.session_state["evidences"]
        spec = st.session_state["spec"]
        df_work = st.session_state["df_work"]
        q_report = st.session_state["q_report"]

        st.markdown("---")
        tab1, tab2, tab3, tab4 = st.tabs([
            "📊 ۱. کاتالوگ شواهد و پارتو",
            "🧭 ۲. کاوشگر مقایسه‌ای استان‌ها و روند زمانی",
            "🎛️ ۳. شبیه‌ساز سناریو (What-If)",
            "📥 ۴. هوش مصنوعی و خروجی گزارش (Excel / PDF)"
        ])

        with tab1:
            col_ev, col_chart = st.columns([1, 1.2])
            with col_ev:
                st.markdown("##### 🚨 شواهد و ناهنجاری‌های کشف‌شده (معیار مقاوم MAD)")
                if not evidences:
                    st.success("✅ هیچ ناهنجاری شدیدی خارج از آستانه استاندارد شناسایی نشد.")
                for ev in evidences:
                    st.error(f"**کد شاهد [{ev.evidence_id}]** — {ev.description_fa}")

                st.markdown("##### 📋 جدول رتبه‌بندی و سهم پارتو (80/20)")
                disp = grouped_df[[spec.category_column, spec.kpi_column, "share_pct", "cumulative_share_pct", "robust_z"]].copy()
                disp.columns = [spec.category_column, spec.kpi_column, "سهم (%)", "سهم تجمعی (%)", "انحراف (Z)"]
                st.dataframe(disp.style.format({
                    spec.kpi_column: "{:,.0f}",
                    "سهم (%)": "{:.1f}%",
                    "سهم تجمعی (%)": "{:.1f}%",
                    "انحراف (Z)": "{:+.2f}"
                }), use_container_width=True)

            with col_chart:
                scale = "RdYlGn" if spec.direction == "higher_is_better" else "RdYlGn_r"
                fig = px.bar(
                    grouped_df, x=spec.category_column, y=spec.kpi_column, text_auto=".3s",
                    color="robust_z", color_continuous_scale=scale,
                    title=f"رتبه‌بندی «{spec.kpi_column}» به تفکیک «{spec.category_column}»"
                )
                fig.update_layout(font=dict(family="Vazirmatn, Tahoma", size=13), title_x=0.5)
                st.plotly_chart(fig, use_container_width=True)

        with tab2:
            st.markdown("#### 🧭 کاوشگر مقایسه‌ای استان‌ها/واحدها و تحلیل روند دوره به دوره")
            st.caption("مقایسه مستقیم دو یا چند واحد (مثلاً مقایسه گیلان و مازندران در فصل مسافرپذیر) به همراه روند تغییرات زمانی.")
            unique_items = grouped_df[spec.category_column].dropna().unique().tolist()

            if len(unique_items) >= 2:
                mc1, mc2, mc3 = st.columns([1, 1, 1.2])
                item_a = mc1.selectbox("واحد/استان مبنا (الف):", unique_items, index=0)
                item_b = mc2.selectbox("واحد/استان هدف برای مقایسه (ب):", unique_items, index=min(1, len(unique_items)-1))
                selected_multi = mc3.multiselect(
                    "انتخاب واحدها برای رسم نمودار روند زمانی:",
                    unique_items,
                    default=unique_items[:min(3, len(unique_items))]
                )

                val_a = float(grouped_df.loc[grouped_df[spec.category_column] == item_a, spec.kpi_column].sum())
                val_b = float(grouped_df.loc[grouped_df[spec.category_column] == item_b, spec.kpi_column].sum())
                diff_ab = val_b - val_a
                pct_ab = ((diff_ab / val_a) * 100.0) if val_a != 0 else 0.0

                k1, k2, k3 = st.columns(3)
                k1.metric(f"عملکرد «{item_a}» (مبنا)", f"{val_a:,.0f}")
                k2.metric(f"عملکرد «{item_b}»", f"{val_b:,.0f}", delta=f"{pct_ab:+.1f}% نسبت به {item_a}")
                k3.metric("اختلاف خالص عملکرد", f"{diff_ab:+,.0f}")

                # نمودار روند زمانی / دوره‌ای
                trend_df = df_work[df_work[spec.category_column].isin(selected_multi)].copy()
                trend_df["_period_label"] = trend_df[spec.time_column].astype(str)
                if not trend_df.empty:
                    trend_grouped = trend_df.groupby(["_period_label", spec.category_column], as_index=False)[spec.kpi_column].sum()
                    fig_trend = px.line(
                        trend_grouped, x="_period_label", y=spec.kpi_column, color=spec.category_column,
                        markers=True, title=f"روند تغییرات «{spec.kpi_column}» در دوره‌ها/تاریخ‌های مختلف"
                    )
                    fig_trend.update_layout(font=dict(family="Vazirmatn, Tahoma", size=13), title_x=0.5, xaxis_title="دوره / تاریخ", yaxis_title=spec.kpi_column)
                    st.plotly_chart(fig_trend, use_container_width=True)
            else:
                st.info("برای مقایسه حداقل ۲ دسته‌بندی مختلف در ستون انتخاب‌شده نیاز است.")

        with tab3:
            st.markdown("#### 🎛️ شبیه‌ساز تعاملی سناریو (What-If Simulator)")
            pct_change = st.slider("درصد تغییر فرضی شاخص (مدیریت سناریو):", min_value=-50, max_value=50, value=15, step=5)
            sim_df = run_what_if_simulation(grouped_df, spec, pct_change)

            s_col1, s_col2 = st.columns([1, 1.2])
            with s_col1:
                sim_display = sim_df[[spec.category_column, spec.kpi_column, f"simulated_{spec.kpi_column}"]].copy()
                sim_display.columns = [spec.category_column, "مقدار فعلی", f"سناریوی ({pct_change:+.0f}٪)"]
                st.dataframe(sim_display.style.format({"مقدار فعلی": "{:,.0f}", f"سناریوی ({pct_change:+.0f}٪)": "{:,.0f}"}), use_container_width=True)
            with s_col2:
                fig_sim = px.bar(
                    sim_df, x=spec.category_column, y=[spec.kpi_column, f"simulated_{spec.kpi_column}"],
                    barmode="group", title=f"مقایسه وضعیت فعلی با سناریوی {pct_change:+.0f}٪"
                )
                fig_sim.update_layout(font=dict(family="Vazirmatn, Tahoma", size=13), title_x=0.5)
                st.plotly_chart(fig_sim, use_container_width=True)

        with tab4:
            st.markdown("#### 🤖 استنتاج امن هوش مصنوعی و مرکز دانلود گزارش‌های مدیریتی")
            safe_payload = generate_safe_egress_payload(evidences)
            ai_response = mock_llm_cognitive_analysis(safe_payload)
            st.info(ai_response)

            st.markdown("##### 📥 دریافت خروجی‌های رسمی (Excel & Printable PDF Report)")
            dl_col1, dl_col2 = st.columns(2)

            excel_bytes = build_excel_export(df_work, grouped_df, evidences)
            dl_col1.download_button(
                label="📊 دانلود فایل اکسل مدیریتی چندشیته (.xlsx)",
                data=excel_bytes,
                file_name="operational_radar_analysis.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

            html_report_bytes = build_printable_executive_report(spec, q_report, grouped_df, evidences, ai_response)
            dl_col2.download_button(
                label="📄 دانلود گزارش رسمی راست‌چین (قابل چاپ مستقیم به PDF)",
                data=html_report_bytes,
                file_name="executive_report_rtl.html",
                mime="text/html",
                use_container_width=True
            )
            st.caption("💡 راهنما: پس از دانلود گزارش رسمی، روی آن دبل‌کلیک کنید تا در مرورگر با فونت استاندارد فارسی باز شود؛ سپس دکمه آبی «چاپ یا ذخیره به عنوان PDF» را بزنید.")
