"""Ingestion (validation, redaction, dedup), NLP decision rules, idempotent reprocessing."""

import numpy as np
import pytest

from backend.app.models.document import Document
from backend.app.models.embedding import DocumentEmbedding
from backend.app.nlp.service import get_nlp_service
from backend.app.services.pipeline import IncomingRecord, ingest_records, process_documents


def rec(text, origin="live", **kw):
    return IncomingRecord(text=text, origin=origin, **kw)


# ── Ingestion ─────────────────────────────────────────────────────────────

def test_validation_rejects_short_and_garbled(db):
    res = ingest_records(db, [rec("too short"), rec("1234567890 !!!! ---- 99999"), rec("")])
    assert res.stored == [] and len(res.rejected) == 3


def test_exact_duplicates_skipped_within_batch_and_against_db(db):
    t = "How do I check my PM-KISAN installment status online?"
    first = ingest_records(db, [rec(t), rec(t.upper())])
    assert len(first.stored) == 1 and len(first.duplicates) == 1
    again = ingest_records(db, [rec(t + "  ")])
    assert again.stored == [] and again.duplicates[0][1] == first.stored[0]


def test_dedup_is_scoped_per_workspace(db):
    t = "Is there an age limit for the Atal Pension Yojana scheme?"
    assert len(ingest_records(db, [rec(t, origin="live")]).stored) == 1
    assert len(ingest_records(db, [rec(t, origin="dataset")]).stored) == 1


def test_dataset_duplicates_persisted_but_flagged(db):
    t = "What documents are required for the Ujjwala gas connection?"
    res = ingest_records(db, [rec(t, origin="dataset"), rec(t, origin="dataset")], persist_duplicates=True)
    docs = db.query(Document).filter(Document.id.in_(res.stored)).order_by(Document.id).all()
    assert [d.is_duplicate for d in docs] == [False, True] and docs[1].duplicate_of_id == docs[0].id


def test_pii_redacted_before_storage(db):
    res = ingest_records(db, [rec("Sir my PM Awas application is pending, call 9876543210", role="discussion")])
    d = db.get(Document, res.stored[0])
    assert "9876543210" not in d.original_text and "[PHONE]" in d.original_text and d.pii_redacted


def test_source_timestamps_preserved_and_not_invented(db):
    from datetime import datetime, timezone
    pub = datetime(2017, 1, 24, 10, 26, tzinfo=timezone.utc)
    res = ingest_records(db, [rec("My name is not in the PMAY gramin list, what to do?", published_at=pub),
                              rec("Undated question about PMAY gramin list eligibility rules")])
    a, b = (db.get(Document, i) for i in res.stored)
    assert a.source_published_at == pub and a.collected_at > pub and a.first_seen_at is not None
    assert b.source_published_at is None


# ── NLP decision rules ────────────────────────────────────────────────────

def test_question_mark_alone_does_not_make_a_gap():
    """The old heuristic flagged any text containing '?'. The model's decision must not hinge on it."""
    s = get_nlp_service()
    for t in ("I received my 15th PM-KISAN installment in my bank account",
              "My Ujjwala refill subsidy was credited this month",
              "We applied for the PMAY gramin house last year"):
        plain = s.analyze(t, "query")["awareness_gap"]
        asked = s.analyze(t + "?", "query")["awareness_gap"]
        assert abs(plain["p_yes"] - asked["p_yes"]) < 0.1          # '?' barely moves the probability
        assert not (plain["label"] == "no" and asked["label"] == "yes")   # and never creates a gap by itself
    news = s.analyze("Government approves 18.77 lakh houses under PMAY-U 2.0 in Odisha?", "news")
    assert news["awareness_gap"]["label"] == "not_applicable"


def test_informational_roles_not_applicable():
    s = get_nlp_service()
    for role in ("news", "article", "faq", "site_reply"):
        assert s.analyze("Who is eligible for the PM-KISAN scheme benefits?", role)["awareness_gap"]["label"] == "not_applicable"


def test_hindi_and_romanized_hindi_are_classified():
    s = get_nlp_service()
    for text in ("Mujhe abhi tak PM Kisan ka paisa nahi mila hai, kya karu?",
                 "मुझे पीएम किसान का पैसा नहीं मिला, क्या करूं?"):
        r = s.analyze(text, "discussion")
        assert r["awareness_gap"]["status"] in ("predicted", "uncertain", "out_of_distribution")
        assert r["intent"]["label"] is not None and r["intent"]["status"] in ("predicted", "low_confidence")
        assert r["scheme"]["primary"] == "PM-KISAN"


def test_out_of_distribution_guard(monkeypatch):
    s = get_nlp_service()
    meta = dict(s.models["awareness_gap"].meta)
    meta["ood_similarity_threshold"] = 0.999
    monkeypatch.setattr(s.models["awareness_gap"], "meta", meta)
    r = s.analyze("How do I apply for the PM-KISAN scheme online?", "query")
    assert r["awareness_gap"]["label"] == "unclear" and r["awareness_gap"]["status"] == "out_of_distribution"
    assert r["needs_review"]


def test_in_domain_question_gets_prediction_with_evidence():
    r = get_nlp_service().analyze("Am I eligible for PM-KISAN if the land is in my father's name?", "query")
    assert r["awareness_gap"]["status"] in ("predicted", "uncertain")
    assert r["intent"]["label"] is not None
    assert r["scheme"]["primary"] == "PM-KISAN"
    assert len(r["evidence"]) == 3 and all("similarity" in e for e in r["evidence"])
    assert r["model_versions"]["awareness_gap"]


def test_uncertainty_band_yields_unclear(monkeypatch):
    s = get_nlp_service()
    m = s.models["awareness_gap"]
    yes = list(m.model.classes_).index("yes")

    def fake_proba(texts, vecs):
        p = np.zeros((len(texts), 2))
        p[:, yes], p[:, 1 - yes] = 0.52, 0.48
        return p
    monkeypatch.setattr(m, "proba", fake_proba)
    r = s.analyze("Am I eligible for PM-KISAN if the land is in my father's name?", "query")
    assert r["awareness_gap"]["label"] == "unclear" and r["awareness_gap"]["status"] == "uncertain"
    assert r["needs_review"] and r["gap_type"] is None


# ── Processing ────────────────────────────────────────────────────────────

def test_process_preserves_manual_labels_and_is_idempotent(db):
    res = ingest_records(db, [rec("Am I eligible for PM-KISAN if the land is in my father's name?", origin="dataset",
                                  intent="Eligibility", awareness_gap="No", gap_type="none", scheme="PM-KISAN")])
    did = res.stored[0]
    out1 = process_documents(db, [did])
    d = db.get(Document, did)
    assert out1["processed"] == 1 and d.processing_status == "completed"
    assert (d.intent, d.awareness_gap, d.label_source) == ("eligibility", "no", "manual")
    assert d.predicted_gap in ("yes", "no", "unclear") and d.explanation["evidence"]
    first = (d.predicted_gap, d.predicted_gap_confidence)
    process_documents(db, [did])
    db.refresh(d)
    assert (d.predicted_gap, d.predicted_gap_confidence) == first
    assert db.query(DocumentEmbedding).filter(DocumentEmbedding.document_id == did).count() == 1


def test_near_duplicates_flagged(db):
    a = "How can I check my PM Kisan beneficiary status online?"
    b = "How can I check my PM Kisan beneficiary status online please"
    res = ingest_records(db, [rec(a, role="question"), rec(b, role="question")])
    out = process_documents(db, res.stored)
    docs = db.query(Document).filter(Document.id.in_(res.stored)).order_by(Document.id).all()
    assert out["near_duplicates"] == 1
    assert not docs[0].is_duplicate and docs[1].is_duplicate and docs[1].near_duplicate_of_id == docs[0].id


def test_comment_inherits_page_scheme_only_when_text_names_none(db):
    res = ingest_records(db, [
        rec("Sir I have no house please give me one, I am very poor", role="discussion", scheme_context="PMAY"),
        rec("What about my Ujjwala gas connection application?", role="discussion", scheme_context="PMAY"),
    ])
    process_documents(db, res.stored)
    a, b = (db.get(Document, i) for i in res.stored)
    assert (a.scheme_name, a.scheme_match_strength) == ("PMAY", "context")
    assert (b.scheme_name, b.scheme_match_strength) == ("PMUY", "strong")


@pytest.mark.parametrize("role,expected", [("news", "not_applicable"), ("faq", "not_applicable")])
def test_processed_roles(db, role, expected):
    res = ingest_records(db, [rec("PM Kisan 21st installment released for farmers across states", role=role)])
    process_documents(db, res.stored)
    assert db.get(Document, res.stored[0]).awareness_gap == expected


def test_call_logs_are_deduplicated_by_record_id_not_text(db):
    """Two farmers asking the same summarised question are two events (KCC call logs)."""
    from backend.app.models.source import Source
    src = Source(name="KCC", url="https://api.data.gov.in/resource/x", content_type="datagovin",
                 source_type="open_data", policy_status="allowed", active=True, verification_status="configured")
    db.add(src)
    db.commit()
    text = "Ask about information on PM-KISAN beneficiary status"
    mk = lambda cid: rec(text, role="query", source_id=src.id, source_document_id=cid, extraction_method="json_api")
    first = ingest_records(db, [mk("101"), mk("102")])
    assert len(first.stored) == 2 and not first.duplicates
    again = ingest_records(db, [mk("101")])            # the same call fetched again IS a duplicate
    assert again.stored == [] and again.duplicates[0][1] == first.stored[0]
    out = process_documents(db, first.stored)
    assert out["near_duplicates"] == 0
    assert all(not db.get(Document, i).is_duplicate for i in first.stored)
