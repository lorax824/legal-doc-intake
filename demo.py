#!/usr/bin/env python3
"""
Legal document intake — self-contained demo.

A sanitized, dependency-free illustration of a document-intake pipeline I
designed and run in production at a plaintiff-side litigation firm. The
production system classifies incoming legal PDFs with the Claude API against
the firm's own rulebook; this public demo uses a small LOCAL rule set and
entirely FICTIONAL documents, so it runs anywhere with zero dependencies and
nothing leaves your machine.

It mirrors the same four stages as production:
  1. Eligibility gate  — INCLUDE / EXCLUDE / REVIEW  (keep real mail, drop junk)
  2. Classification    — document type + case + house-style filename
  3. Routing           — file it / needs human review / exclude
  4. Mail log          — an auto-drafted daily summary

Run:  python3 demo.py
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

# ── Fictional "master case table" ────────────────────────────────────────────
# Production matches against the firm's real active matters. Everything here
# is invented. A document whose case is on this table is high-confidence;
# one derived from the caption is medium and gets spot-checked.
MASTER_CASES = {
    "nguyen":  "Nguyen v. Westfield Logistics, Inc.",
    "okafor":  "Okafor v. Brightline Transit",
    "alvarez": "Alvarez v. Kraft Haulage",
    "diaz":    "Diaz v. Summit Construction",
    "chen":    "Chen v. Wong",
    "ramirez": "Ramirez v. Pacific Grocery Co.",
}

# Vendor/admin noise that should never reach the mail log.
EXCLUDE_MARKERS = ("transaction receipt", "e-service confirmation",
                   "filing was submitted", "payment received",
                   "your document was received")

# Ambiguous items that go to a human instead of being guessed.
REVIEW_MARKERS = ("notice of rejection", "filing failed", "failed service")

# doc_type rules — ORDER MATTERS (most specific first). "first match wins"
# is deliberate: "Motion to Compel ... Interrogatories" must classify as a
# Motion, not Interrogatories, and "Answer to Complaint" as an Answer, not a
# Complaint. Getting this order wrong silently misfiles documents.
DOC_TYPE_RULES = [
    ("Motion to Compel",  ("motion to compel",)),
    ("Motion",            ("motion", "summary judgment", "msj")),
    ("Interrogatories",   ("interrogatories", "rogs", "frogs")),
    ("Deposition Notice", ("notice of deposition", "deposition of")),
    ("Minute Order",      ("minute order",)),
    ("Order",             ("order",)),
    ("Answer",            ("answer to complaint", "answer")),
    ("Complaint",         ("complaint for",)),
    ("Proof of Service",  ("proof of service",)),
    ("Correspondence",    ("meet and confer", "deficien", "letter")),
]

# Firm-shorthand descriptions used in the filename.
DESCRIPTION = {
    "Motion to Compel": "Mtn to Compel", "Motion": "Mtn",
    "Interrogatories": "ROGs", "Deposition Notice": "Depo Ntc",
    "Minute Order": "Min Order", "Order": "Order", "Answer": "Answer",
    "Complaint": "Complaint", "Proof of Service": "POS", "Correspondence": "Ltr",
}


@dataclass
class Doc:
    filename: str   # the ugly original name
    doc_date: str   # YYYY.MM.DD — the date ON the document, not today
    caption: str    # the case caption text, or "" if none/unreadable
    text: str       # the title / snippet the classifier reads


# A fictional day's inbox (a deliberate mix of file / review / exclude).
INBOX = [
    Doc("scan001.pdf", "2026.03.12", "Nguyen v. Westfield Logistics, Inc.",
        "Defendant's Motion to Compel Further Responses to Special Interrogatories, Set One"),
    Doc("Document(3).pdf", "2026.03.12", "Chen v. Wong",
        "Notice of Deposition of Plaintiff"),
    Doc("receipt.pdf", "2026.03.12", "",
        "OneLegal Transaction Receipt — your filing was submitted. Payment received."),
    Doc("mo_cmc.pdf", "2026.03.11", "Ramirez v. Pacific Grocery Co.",
        "Minute Order re Case Management Conference"),
    Doc("ltr.pdf", "2026.03.10", "Diaz v. Summit Construction",
        "Meet and Confer Letter re deficient discovery responses"),
    Doc("cmplt.pdf", "2026.03.09", "Okafor v. Brightline Transit",
        "Complaint for Damages"),
    Doc("scan_0412.pdf", "2026.03.12", "",
        "Notice of Rejection — your filing failed and was not accepted"),
    Doc("ans.pdf", "2026.03.08", "Harper v. Delcon Freight",
        "Answer to Complaint"),   # not on the master table → derived from caption
]


def eligibility(text: str) -> str:
    low = text.lower()
    if any(m in low for m in EXCLUDE_MARKERS):
        return "EXCLUDE"
    if any(m in low for m in REVIEW_MARKERS):
        return "REVIEW"
    return "INCLUDE"


def classify_type(text: str) -> str:
    low = text.lower()
    for name, keys in DOC_TYPE_RULES:
        if any(k in low for k in keys):
            return name
    return "Document"


def match_case(caption: str) -> tuple[str, str, str]:
    """Return (shortname, source, confidence)."""
    m = re.match(r"\s*([A-Za-z][\w.&'-]*)", caption)
    if not m:
        return "UNKNOWN", "unreadable", "low"
    key = m.group(1).lower()
    if key in MASTER_CASES:
        return m.group(1), "master", "high"
    return m.group(1), "derived", "medium"


def build_filename(doc: Doc, shortname: str, doc_type: str) -> str:
    desc = DESCRIPTION.get(doc_type, doc_type)
    return f"{doc.doc_date} {shortname} - {desc}.pdf"


def process(doc: Doc) -> dict:
    status = eligibility(doc.text)
    doc_type = classify_type(doc.text)

    if status == "EXCLUDE":
        return {"route": "excluded", "doc_type": doc_type}

    shortname, source, conf = match_case(doc.caption)

    if status == "REVIEW":
        return {"route": "review", "doc_type": doc_type,
                "case": shortname, "source": source, "confidence": "low"}

    # INCLUDE — file it unless the case is genuinely unidentifiable.
    route = "review" if source == "unreadable" else "output"
    name = build_filename(doc, shortname, doc_type) if route == "output" else None
    return {"route": route, "doc_type": doc_type, "case": shortname,
            "source": source, "confidence": conf, "new_filename": name}


def main() -> None:
    results = [(d, process(d)) for d in INBOX]

    print("\n  Legal document intake — demo run")
    print("  " + "-" * 54)
    tag = {"output": "FILE", "review": "REVIEW", "excluded": "EXCLUDE"}
    for d, r in results:
        print(f"  [{tag[r['route']]:7}] {d.filename:16} {r['doc_type']}")
        if r.get("new_filename"):
            note = "   (case derived from caption — spot-check)" \
                if r.get("source") == "derived" else ""
            print(f"             → {r['new_filename']}{note}")

    # ── Auto-drafted mail log: filed docs grouped by case ────────────────────
    by_case: dict[str, list[str]] = {}
    for _, r in results:
        if r["route"] == "output":
            by_case.setdefault(r["case"], []).append(r["new_filename"])

    print("\n  " + "-" * 54)
    print(f"  DRAFT MAIL LOG — {date.today():%m/%d/%Y}\n")
    for case in sorted(by_case):
        print(f"  {case}")
        for fn in by_case[case]:
            print(f"       •  {fn[:-4]}")   # drop .pdf — house style
        print()

    n = len(results)
    out = sum(1 for _, r in results if r["route"] == "output")
    rev = sum(1 for _, r in results if r["route"] == "review")
    exc = sum(1 for _, r in results if r["route"] == "excluded")
    print("  " + "-" * 54)
    print(f"  {n} documents → {out} filed, {rev} for review, {exc} excluded.\n")
    print("  (In production, step 2 is done by the Claude API against the firm's")
    print("   rulebook; this demo uses local keyword rules so it runs anywhere.)\n")


if __name__ == "__main__":
    main()
