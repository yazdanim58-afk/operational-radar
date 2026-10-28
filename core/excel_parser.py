import pandas as pd

def parse_hierarchical_excel(uploaded_file):
    # خواندن فایل اکسل و پر کردن سلول‌های ادغام‌شده (ffill) برای مدیریت ساختارهای درختی و سرگروه‌ها
    df = pd.read_excel(uploaded_file, header=None)
    df_filled = df.ffill(axis=0).ffill(axis=1)
    return df_filled
