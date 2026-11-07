"""Score real extraction output against the generator's ground truth.

The number that matters most is SILENT ERRORS: a wrong comparable price that was NOT
flagged for review. A flagged error costs a buyer a click; a silent one costs money.

  python scripts/eval_extraction.py            # after scripts/run_pipeline.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from run_pipeline import FILES, load_context  # noqa: E402

GT = json.loads((ROOT / "demo_data" / "ground_truth.json").read_text())


def main():
    ctx = load_context()
    rows, tot = [], {"lines": 0, "status_ok": 0, "price_ok": 0, "flagged_wrong": 0, "silent_wrong": 0, "edge_caught": 0, "edges": 0}
    for vid in FILES:
        g = GT["vendors"][vid]["lines"]
        s = {"lines": 0, "status_ok": 0, "price_ok": 0, "flagged_wrong": 0, "silent_wrong": 0}
        for lid, t in g.items():
            n = ctx.norm.get(vid, lid)
            s["lines"] += 1
            exp = t["status"]
            if (n.status == exp) or (exp == "QUOTED" and n.status == "UNREADABLE" and "ILLEGIBLE" in t.get("flags", [])):
                s["status_ok"] += 1
            if exp == "QUOTED" and n.comparable:
                ok = abs(n.unit_price_base - t["unit_price_inr_per_rfx_uom"]) <= max(0.01, 0.005 * t["unit_price_inr_per_rfx_uom"])
                if ok:
                    s["price_ok"] += 1
                elif n.review_required:
                    s["flagged_wrong"] += 1
                else:
                    s["silent_wrong"] += 1
                    rows.append(f"  SILENT {vid} {lid}: got {n.unit_price_base} expected {t['unit_price_inr_per_rfx_uom']}")
            elif exp != "QUOTED" and n.comparable and not n.review_required:
                s["silent_wrong"] += 1
                rows.append(f"  SILENT {vid} {lid}: priced {n.unit_price_base} but truth is {exp}")
            for f in t.get("flags", []):
                tot["edges"] += 1
                if n.review_required or n.status != "QUOTED":
                    tot["edge_caught"] += 1
                else:
                    rows.append(f"  MISSED EDGE {vid} {lid} {f}")
        for k in s:
            tot[k] += s[k]
        print(f"{vid}: status {s['status_ok']}/{s['lines']}  price {s['price_ok']}  flagged-wrong {s['flagged_wrong']}  SILENT-WRONG {s['silent_wrong']}")
    print("\n".join(rows))
    print(f"\nTOTAL: status accuracy {tot['status_ok']}/{tot['lines']}, prices correct {tot['price_ok']}, "
          f"wrong-but-flagged {tot['flagged_wrong']}, SILENT wrong {tot['silent_wrong']}, "
          f"planted edge cases caught {tot['edge_caught']}/{tot['edges']}")
    hdr = GT["vendors"]
    for vid in FILES:
        vs = next(v for v in ctx.norm.vendors if v.vendor_id == vid)
        print(f"{vid} terms: freight={vs.freight_basis} ({vs.freight_note}) payment={vs.payment_days} "
              f"conditional={[(d.get('value'), d.get('condition_type')) for d in vs.conditional_discounts]}  truth={hdr[vid]['header'].get('freight')}")


if __name__ == "__main__":
    main()
