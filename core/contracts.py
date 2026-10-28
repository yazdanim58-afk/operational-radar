from typing import Literal, List, Optional
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
