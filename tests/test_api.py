"""API: authorization, upload→NLP→analytics workflow, filtering, export, review, search, SSE."""

import csv
import io
import json

import pytest

from tests.conftest import wait_for_job

CSV = """id,text,scheme,intent,awareness_gap,gap_type,state,district,source,split
1,"Am I eligible for PM-KISAN if the agricultural land is registered in my father's name?",PM-KISAN,eligibility,yes,eligibility_gap,Haryana,Ambala,KCC,train
2,"My 15th PM-KISAN installment has not been credited even though e-KYC is complete, whom do I contact?",PM-KISAN,payment,no,none,Bihar,,KCC,train
3,"Someone told me the Ujjwala scheme gives free cylinders every month forever, is that true?",PMUY,benefits,yes,misconception,,,News,test
4,"What documents do I need to apply for a Mudra loan under the Shishu category?",PMMY,documentation,yes,documentation_gap,Uttar Pradesh,,Forum,val
5,"What documents do I need to apply for a Mudra loan under the Shishu category?",PMMY,documentation,yes,documentation_gap,Uttar Pradesh,,Forum,val
6,"short",PMMY,documentation,yes,documentation_gap,,,Forum,val
"""

PROTECTED = [
    ("post", "/api/datasets/upload"), ("post", "/api/datasets/preview"), ("post", "/api/collection/campaigns"),
    ("post", "/api/collection/autopilot?enabled=true"), ("post", "/api/sources/sync"),
    ("patch", "/api/documents/1/review"), ("post", "/api/jobs/reprocess"), ("post", "/api/clusters/run?scope=dataset"),
    ("get", "/api/auth/check"),
]


def upload(client, admin, content=CSV, name="sample.csv", **form):
    return client.post("/api/datasets/upload", headers=admin, files={"file": (name, content.encode(), "text/csv")},
                       data=form)


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_endpoints_require_key(client, method, path):
    r = getattr(client, method)(path)
    assert r.status_code == 401
    r = getattr(client, method)(path, headers={"X-API-Key": "wrong-key"})
    assert r.status_code == 401


def test_protected_endpoints_disabled_without_configured_key(client, monkeypatch):
    from backend.app.config import get_settings
    monkeypatch.setattr(get_settings(), "ADMIN_API_KEY", "")
    assert client.get("/api/auth/check", headers={"X-API-Key": "anything"}).status_code == 503


def test_auth_check_with_valid_key(client, admin):
    assert client.get("/api/auth/check", headers=admin).json() == {"authenticated": True}


def test_public_read_endpoints(client):
    for path in ("/api/health", "/api/analytics/overview?scope=dataset", "/api/documents", "/api/sources",
                 "/api/collection/status", "/api/models", "/api/schemes"):
        assert client.get(path).status_code == 200, path


def test_upload_to_dashboard_workflow(client, admin):
    r = upload(client, admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["rows"] == 6 and body["summary"]["rejected"] == 1 and body["summary"]["duplicates"] == 1
    job = wait_for_job(client, body["dataset"]["job"]["id"])
    assert job["status"] == "completed" and job["result"]["processed"] == 5

    ds = client.get(f"/api/datasets/{body['dataset']['id']}").json()
    assert ds["processing_status"] == "processed" and ds["rejections"][0]["row"] == 6

    ov = client.get("/api/analytics/overview?scope=dataset").json()
    assert ov["total_records"] == 4                       # 6 rows − 1 rejected − 1 duplicate
    gap = ov["awareness_gap"]
    assert (gap["yes"], gap["no"]) == (3, 1) and gap["gap_rate"] == 0.75
    assert ov["excluded"]["duplicates"] == 1
    assert ov["label_sources"] == {"manual": 4}
    assert ov["location_coverage"] == 0.75                # 3 of 4 have a stated state

    live = client.get("/api/analytics/overview?scope=live").json()
    assert live["total_records"] == 0                     # workspaces are separate

    schemes = {r["value"]: r for r in client.get("/api/analytics/schemes?scope=dataset").json()}
    assert schemes["PM-KISAN"]["yes"] == 1 and schemes["PM-KISAN"]["no"] == 1 and schemes["PM-KISAN"]["gap_rate"] == 0.5

    geo = client.get("/api/analytics/geography?scope=dataset").json()
    assert geo["unknown_location"] == 1 and {r["value"] for r in geo["regions"]} == {"Haryana", "Bihar", "Uttar Pradesh"}

    clusters = client.get("/api/clusters?scope=dataset").json()
    assert clusters["run"]["status"] == "skipped"         # too few records to cluster honestly


def test_reimport_same_file_is_refused(client, admin):
    first = upload(client, admin)
    assert first.status_code == 200
    r = upload(client, admin)
    wait_for_job(client, first.json()["dataset"]["job"]["id"])
    assert r.status_code == 409 and "already imported" in r.json()["detail"]["message"]


def test_upload_validation_errors(client, admin):
    assert upload(client, admin, content="a,b\n1,2\n").status_code == 422          # no text column
    assert upload(client, admin, content="", name="empty.csv").status_code == 400
    assert upload(client, admin, content="text\nhello", name="data.xlsx").status_code == 400
    r = client.post("/api/datasets/upload", headers=admin,
                    files={"file": ("bad.json", b"{not json", "application/json")})
    assert r.status_code == 422


def test_json_upload_with_explicit_mapping(client, admin):
    records = [{"question": "How can I check whether my name is on the PMAY gramin beneficiary list?", "region": "Bihar"},
               {"question": "Is the Atal Pension Yojana available for people above forty years of age?"}]
    r = client.post("/api/datasets/upload", headers=admin,
                    files={"file": ("q.json", json.dumps(records).encode(), "application/json")},
                    data={"mapping": json.dumps({"text": "question", "state": "region"})})
    assert r.status_code == 200, r.text
    wait_for_job(client, r.json()["dataset"]["job"]["id"])
    docs = client.get("/api/documents?scope=dataset&sort_by=id&sort_order=asc").json()["items"]
    assert docs[0]["state"] == "Bihar" and docs[0]["label_source"] == "model"
    assert docs[1]["scheme_name"] == "APY"


def test_preview_does_not_store(client, admin):
    r = client.post("/api/datasets/preview", headers=admin, files={"file": ("p.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 200 and r.json()["row_count"] == 6 and r.json()["mapping"]["text"] == "text"
    assert client.get("/api/datasets").json() == []


def test_documents_filter_sort_paginate_export(client, admin):
    wait_for_job(client, upload(client, admin).json()["dataset"]["job"]["id"])
    page = client.get("/api/documents?scope=dataset&page_size=2&sort_by=id&sort_order=asc").json()
    assert page["total"] == 4 and page["total_pages"] == 2 and len(page["items"]) == 2
    only = client.get("/api/documents?scope=dataset&scheme=PM-KISAN&awareness_gap=no").json()
    assert only["total"] == 1 and only["items"][0]["intent"] == "payment"
    assert client.get("/api/documents?scope=dataset&search=ujjwala").json()["total"] == 1
    assert client.get("/api/documents?sort_by=original_text").status_code == 400

    r = client.get("/api/documents/export?scope=dataset&scheme=PM-KISAN&fmt=csv")
    lines = r.text.splitlines()
    assert lines[0].startswith("# filters:") and "PM-KISAN" in lines[0]
    rows = list(csv.DictReader(io.StringIO("\n".join(lines[1:]))))
    assert len(rows) == 2 and {x["scheme_name"] for x in rows} == {"PM-KISAN"}
    j = client.get("/api/documents/export?scope=dataset&fmt=json").json()
    assert len(j["records"]) == 4


def test_document_detail_similar_and_review(client, admin):
    wait_for_job(client, upload(client, admin).json()["dataset"]["job"]["id"])
    items = client.get("/api/documents?scope=dataset&sort_by=id&sort_order=asc").json()["items"]
    d = client.get(f"/api/documents/{items[0]['id']}").json()
    assert d["explanation"]["evidence"] and d["predicted_gap"] in ("yes", "no", "unclear")
    assert d["dataset"]["version"] == "v1"
    sim = client.get(f"/api/documents/{items[0]['id']}/similar").json()
    assert all(s["id"] != items[0]["id"] for s in sim["items"])

    r = client.patch(f"/api/documents/{items[0]['id']}/review", headers=admin,
                     json={"awareness_gap": "no", "note": "Asker already knows the rule"})
    assert r.status_code == 200 and r.json()["label_source"] == "review" and r.json()["gap_type"] == "none"
    logs = client.get("/api/system/audit-logs?action=document_reviewed").json()
    assert logs and logs[0]["details"]["after"]["awareness_gap"] == "no"
    assert client.patch(f"/api/documents/{items[0]['id']}/review", headers=admin,
                        json={"awareness_gap": "maybe"}).status_code == 422


def test_semantic_search(client, admin):
    wait_for_job(client, upload(client, admin).json()["dataset"]["job"]["id"])
    r = client.post("/api/search/semantic", json={"query": "free gas cylinder every month", "scope": "dataset"}).json()
    assert r["items"] and r["items"][0]["scheme_name"] == "PMUY"


def test_analyze_endpoint(client):
    r = client.post("/api/analyze", json={"text": "Can tenant farmers get PM-KISAN money?", "text_role": "query"})
    body = r.json()
    assert r.status_code == 200 and body["scheme"]["primary"] == "PM-KISAN"
    assert set(body["similar_records"]) == {"dataset", "live"}
    assert client.post("/api/analyze", json={"text": "hi"}).status_code == 422


def test_campaign_queue_cancel_and_validation(client, admin, db):
    from backend.app.models.source import Source
    s = Source(name="S", url="https://example.org/feed", content_type="rss", policy_status="allowed", active=True,
               source_type="news", verification_status="configured")
    blocked = Source(name="B", url="https://example.org/b", content_type="html", policy_status="blocked",
                     active=False, source_type="news", verification_status="configured")
    db.add_all([s, blocked])
    db.commit()
    assert client.post("/api/collection/campaigns", headers=admin,
                       json={"name": "bad", "source_ids": [blocked.id]}).status_code == 409
    c = client.post("/api/collection/campaigns", headers=admin, json={"name": "test run", "source_ids": [s.id]}).json()
    assert c["status"] == "queued" and c["crawl_started_at"] is None
    assert client.post(f"/api/collection/campaigns/{c['id']}/cancel", headers=admin).json()["status"] == "cancelled"
    assert client.post(f"/api/collection/campaigns/{c['id']}/cancel", headers=admin).status_code == 409
    st = client.get("/api/collection/status").json()
    assert st["worker_alive"] is False and st["active_campaigns"] == []


def test_source_enable_rules(client, admin, db):
    from backend.app.models.source import Source
    s = Source(name="U", url="https://www.myscheme.gov.in/", content_type="html", policy_status="unsupported",
               active=False, source_type="official", verification_status="configured")
    db.add(s)
    db.commit()
    assert client.patch(f"/api/sources/{s.id}", headers=admin, json={"active": True}).status_code == 409
    r = client.post("/api/sources", headers=admin, json={"name": "Internal", "url": "http://127.0.0.1/feed"})
    assert r.status_code == 422 and "rejected" in r.json()["detail"]


def test_sse_stream_emits_status(client):
    with client.stream("GET", "/api/collection/stream?timeout=1") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        lines = [ln for ln in r.iter_lines() if ln.startswith("event:")]
    assert lines[0] == "event: status" and lines[-1] == "event: reconnect"


def test_request_size_limit(client, admin):
    r = client.post("/api/analyze", content=b"x" * (2 * 1024 * 1024),
                    headers={"content-type": "application/json", "content-length": str(2 * 1024 * 1024)})
    assert r.status_code == 413


def test_health_reports_migrations_and_models(client):
    h = client.get("/api/health").json()
    assert h["database"] == "connected" and h["migrations"]["up_to_date"] and h["models_loaded"]
