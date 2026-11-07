"""Board-area and weight estimation for corrugated items.

Used when a vendor prices by weight (e.g. "USD 0.59/kg") and the RFx is in pieces.
The estimate is deterministic and fully disclosed; it is an *assumption*, never
treated as a verified fact. Weight = blank area (m^2) x total board grammage (g/m^2).

Blank-area formulas (industry approximations):
  RSC (regular slotted container): (2L + 2W + glue flap) x (W + H)
  Tray / die-cut:                  (L + 2H + 20) x (W + 2H + 20)
  Sleeve:                          (2L + 2W + 30) x H
  Sheet / pad:                     L x W
  Roll:                            width x length
Items without a defined geometry (edge protectors, laminated solid board) cannot be
converted and return None so the comparison is blocked rather than guessed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

GLUE_FLAP_MM = 35.0


@dataclass(frozen=True)
class WeightEstimate:
    area_m2: float
    board_gsm: float
    weight_kg: float
    formula: str

    def explain(self) -> str:
        return (
            f"{self.formula}; area {self.area_m2:.4f} m² × {self.board_gsm:.0f} g/m² "
            f"= {self.weight_kg * 1000:.1f} g per unit"
        )


def blank_area_m2(spec: dict) -> Optional[tuple[float, str]]:
    kind = spec.get("kind")
    if spec.get("area_m2"):
        return float(spec["area_m2"]), f"stated blank area {spec['area_m2']} m²"
    L, W, H = spec.get("length_mm"), spec.get("width_mm"), spec.get("height_mm")
    if kind in ("rsc", "pallet_box"):
        if not (L and W and H):
            return None
        a = (2 * L + 2 * W + GLUE_FLAP_MM) * (W + H) / 1e6
        return a, f"RSC blank (2×{L}+2×{W}+{GLUE_FLAP_MM:.0f})×({W}+{H}) mm"
    if kind in ("tray", "die_cut"):
        if not (L and W and H):
            return None
        a = (L + 2 * H + 20) * (W + 2 * H + 20) / 1e6
        return a, f"die-cut blank ({L}+2×{H}+20)×({W}+2×{H}+20) mm"
    if kind == "sleeve":
        if not (L and W and H):
            return None
        a = (2 * L + 2 * W + 30) * H / 1e6
        return a, f"sleeve blank (2×{L}+2×{W}+30)×{H} mm"
    if kind in ("sheet", "pad"):
        if not (L and W):
            return None
        return L * W / 1e6, f"sheet {L}×{W} mm"
    if kind == "roll":
        if not (spec.get("roll_width_mm") and spec.get("roll_length_m")):
            return None
        a = spec["roll_width_mm"] / 1000 * spec["roll_length_m"]
        return a, f"roll {spec['roll_width_mm']} mm × {spec['roll_length_m']} m"
    return None


def estimate_weight(spec: dict) -> Optional[WeightEstimate]:
    gsm = spec.get("board_gsm")
    area = blank_area_m2(spec)
    if not gsm or area is None:
        return None
    a, formula = area
    return WeightEstimate(area_m2=round(a, 6), board_gsm=float(gsm), weight_kg=a * gsm / 1000.0, formula=formula)
