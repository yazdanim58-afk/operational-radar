import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def generate_executive_pdf(filename, summary_text):
    c = canvas.Canvas(filename, pagesize=letter)
    # در نسخه پایه گزارش اجرایی ساخته می‌شود
    c.drawString(100, 750, "Operational Radar - Executive Report")
    c.drawString(100, 720, summary_text)
    c.save()
