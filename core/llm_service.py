def generate_safe_egress_payload(evidences):
    return {"total_evidences_flagged": len(evidences), "evidence_summaries": [{"id": ev.evidence_id, "metric": ev.metric_name, "deviation_pct": ev.deviation_pct, "severity": ev.severity} for ev in evidences]}

def mock_llm_cognitive_analysis(payload):
    if payload["total_evidences_flagged"] == 0:
        return "تحلیل هوش مصنوعی: شاخص‌ها در محدوده تعادل هستند."
    return "🤖 تحلیل استنتاجی هوش مصنوعی: تعداد " + str(payload["total_evidences_flagged"]) + " گلوگاه عملیاتی شناسایی شد. پیشنهاد می‌شود بررسی فوری روی شعب یا واحدهای پرچم‌گذاری شده انجام شود."
