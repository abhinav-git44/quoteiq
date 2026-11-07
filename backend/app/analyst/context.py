"""Everything the analyst tools may read. Built from persisted data by the API layer
(or from the core pipeline in scripts/tests). Tools never touch the DB directly."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from app.core.config import Settings, get_settings
from app.domain.normalized import NormalizationResult, VendorQuoteInput
from app.normalization.engine import FxTable, normalize
from app.optimization.award import Scenario
from app.quality.eligibility import VendorEligibility


@dataclass
class AnalysisContext:
    rfx: dict
    lines: list[dict]
    vendors: list[dict]                       # vendor master records
    questionnaire: list[dict]
    vendor_inputs: list[VendorQuoteInput]
    fx_rates: list[dict]
    eligibility: dict[str, VendorEligibility]
    extraction: dict[str, dict] = field(default_factory=dict)   # vendor_id -> {status, filename, document_id, exceptions:[...]}
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    exporter: Optional[Callable[[str, dict], dict]] = None
    on_scenario: Optional[Callable[[Scenario], None]] = None
    settings: Settings = field(default_factory=get_settings)
    norm: Optional[NormalizationResult] = None

    def __post_init__(self):
        if self.norm is None:
            self.norm = normalize(self.lines, self.vendor_inputs, self.fx(), self.settings)

    def fx(self, overrides: Optional[dict[str, float]] = None) -> FxTable:
        rates = []
        for r in self.fx_rates:
            r = dict(r)
            if overrides and r["from_currency"] in overrides:
                r.update(rate=overrides[r["from_currency"]], source="What-if override (not a market rate)", rate_type="WHAT_IF")
            rates.append(r)
        return FxTable(rates, base=self.settings.base_currency)

    @property
    def names(self) -> dict[str, str]:
        return {v["vendor_id"]: v["name"] for v in self.vendors}

    def resolve_vendor(self, ref: str) -> Optional[str]:
        """Accept 'V-A', 'A', 'Vendor A' or a (partial) name."""
        if not ref:
            return None
        r = ref.strip().lower()
        for v in self.vendors:
            vid = v["vendor_id"].lower()
            if r in (vid, vid.replace("v-", ""), f"vendor {vid.replace('v-', '')}") or r == v["name"].lower():
                return v["vendor_id"]
        for v in self.vendors:
            if r in v["name"].lower():
                return v["vendor_id"]
        return None

    def line(self, line_id: str) -> Optional[dict]:
        return next((l for l in self.lines if l["line_id"] == line_id.upper()), None)
