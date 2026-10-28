from typing import Optional
import re
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
    s = s.str.replace(r"[\u200c\u200e\u200f]", " ", regex=True)
    return s.str.replace(r"\s+", " ", regex=True).str.strip()

def clean_currency_and_numbers(series: pd.Series) -> tuple[pd.Series, int]:
    s = series.astype("string").str.translate(DIGIT_MAP).str.strip()
    # تبدیل اعداد منفی داخل پرانتز مثل (۱۲۰۰) به -1200
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
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
    s = s.str.replace(r"[-\.]", "/", regex=True)
    extracted = s.str.extract(r"^(\d{4})/(\d{1,2})/(\d{1,2})")
    
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
