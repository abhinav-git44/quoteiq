"""Seed the SYNTHETIC demo: org, buyer, vendors, the RFx, questionnaire answers (portal form),
assumed FX rates — and register the five vendor documents + certificates through the SAME
ingestion path as a user upload. No extracted values are seeded."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (ExchangeRate, Organization, QuestionnaireQuestion, Rfx, RfxLineItem, RfxTerm, RfxVendor,
                           UnitConversion, User, Vendor, VendorContact, VendorQuestionnaireAnswer)
from app.demo.catalog import (EXCHANGE_RATES, QUESTIONNAIRE, QUESTIONNAIRE_ANSWERS, RFX, VENDORS, rfx_line_items)
from app.services.common import audit, hash_password
from app.services.rfx_service import queue_extraction, register_document

DEMO_EMAIL = "buyer@kaveri.example"
DEMO_PASSWORD = "quoteiq-demo"
FILES = {"V-A": "vendor_a_packpro_quotation.xlsx", "V-B": "vendor_b_ecocarton_quotation.pdf",
         "V-C": "vendor_c_prime_quotation.docx", "V-D": "vendor_d_shree_quotation_photo.jpg",
         "V-E": "vendor_e_globalpack_email.eml"}


def seed(db: Session, demo_dir: Path) -> tuple[Rfx, list[str]]:
    if db.scalar(select(Rfx).where(Rfx.reference == RFX["reference"])):
        raise RuntimeError("Demo already seeded (RFX-2026-0147 exists). Drop the database or run with --reset.")
    org = Organization(name="Kaveri Home Appliances Pvt. Ltd. (fictional)")
    db.add(org); db.flush()
    user = User(org_id=org.id, email=DEMO_EMAIL, name="Priya Nair", role="BUYER", password_hash=hash_password(DEMO_PASSWORD))
    approver = User(org_id=org.id, email="vp@kaveri.example", name="R. Iyer (VP Procurement)", role="APPROVER",
                    password_hash=hash_password(DEMO_PASSWORD))
    db.add_all([user, approver]); db.flush()
    for v in VENDORS:
        vv = Vendor(id=v["vendor_id"], org_id=org.id, name=v["name"], city=v["city"], address=v["address"],
                    categories=v["categories"], certifications=v["certifications"], capacity_tpm=v["capacity_tpm"],
                    historical_score=v["historical_score"], submission_format=v["submission_format"])
        vv.contacts.append(VendorContact(name=v["contact"], email=v["email"]))
        db.add(vv)
    for r in EXCHANGE_RATES:
        db.add(ExchangeRate(**r))
    for f, t, k, rule in [("HUNDRED", "PIECE", 0.01, "÷100"), ("THOUSAND", "PIECE", 0.001, "÷1000"),
                          ("BUNDLE", "PIECE", None, "only with stated pack size"), ("BOX", "PIECE", None, "only with stated pack size"),
                          ("KG", "PIECE", None, "derived: blank area × board GSM (assumption, review required)")]:
        db.add(UnitConversion(from_uom=f, to_uom=t, factor=k, rule=rule))
    rfx = Rfx(org_id=org.id, reference=RFX["reference"], title=RFX["title"], category=RFX["category"],
              description=RFX["description"], business_justification=RFX["business_justification"],
              delivery_location=RFX["delivery_location"], issue_date=date.fromisoformat(RFX["issue_date"]),
              submission_deadline=date.fromisoformat(RFX["submission_deadline"]), currency=RFX["currency"],
              required_delivery_days=RFX["required_delivery_days"], status="EVALUATION", created_by=user.id)
    rfx.terms = [RfxTerm(kind="PAYMENT", text=RFX["payment_terms"]), RfxTerm(kind="COMMERCIAL", text=RFX["commercial_terms"]),
                 RfxTerm(kind="ELIGIBILITY_RULE", text="Vendor is eligible only if every mandatory questionnaire item passes.")]
    rfx.lines = [RfxLineItem(line_id=l["line_id"], item_code=l["item_code"], name=l["name"], description=l["description"],
                             spec=l["spec"], quantity=l["quantity"], uom=l["uom"], target_price=l["target_price_inr"],
                             required_delivery_days=l["required_delivery_days"], mandatory=l["mandatory"])
                 for l in rfx_line_items()]
    rfx.questions = [QuestionnaireQuestion(qid=q["qid"], position=i, text=q["text"], type=q["type"], mandatory=q["mandatory"],
                                           pass_rule=q["pass_rule"]) for i, q in enumerate(QUESTIONNAIRE)]
    db.add(rfx); db.flush()
    audit(db, "RFX_CREATED", "rfx", rfx.id, user.id, after={"reference": rfx.reference, "lines": 30}, org_id=org.id)
    for v in VENDORS:
        db.add(RfxVendor(rfx_id=rfx.id, vendor_id=v["vendor_id"]))
        for qid, ans in QUESTIONNAIRE_ANSWERS[v["vendor_id"]].items():
            db.add(VendorQuestionnaireAnswer(rfx_id=rfx.id, vendor_id=v["vendor_id"], qid=qid, answer=ans))
    db.flush()
    audit(db, "RFX_PUBLISHED", "rfx", rfx.id, user.id, meta={"channel": "EMAIL_STUB", "vendors": len(VENDORS)})
    jobs = []
    for vid, fn in FILES.items():
        doc = register_document(db, rfx, vid, demo_dir / fn, fn, "QUOTATION", user.id)
        jobs.append(queue_extraction(db, doc, user.id).id)
        cert = demo_dir / "certificates" / f"{vid.lower()}_iso9001_certificate.pdf"
        cdoc = register_document(db, rfx, vid, cert, cert.name, "CERTIFICATE", user.id)
        jobs.append(queue_extraction(db, cdoc, user.id).id)
    return rfx, jobs
