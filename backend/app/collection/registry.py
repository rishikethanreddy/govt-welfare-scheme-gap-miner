"""
Curated source registry.

Each entry records *why* it is (or is not) collected. Registration does not
claim a source works: verification_status is only updated by real runs.

policy_status:
  allowed              — public, robots.txt permits our agent; collected when active
  manual_review        — terms of use are unclear/restrictive; not collected by default
  blocked              — login wall or terms prohibit automated access; never collected
  unsupported          — content requires JavaScript rendering or is not a data endpoint
  credentials_required — official API that needs a key the operator must configure
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.models.audit import AuditLog
from backend.app.models.source import Source

logger = logging.getLogger(__name__)

SARKARIYOJANA_NOTE = ("Public scheme-information site. robots.txt permits crawling except /page/ and a few "
                      "internal paths (enforced automatically). Reader comments are public-voice text; "
                      "phone numbers, Aadhaar, e-mail and PAN are redacted before storage.")

REGISTRY: list[dict] = [
    # ── Public-voice sources (comments / queries) ─────────────────────────
    {"name": "SarkariYojana — latest posts (RSS)", "url": "https://sarkariyojana.com/feed/",
     "adapter": "rss", "source_type": "publication", "category": "public_comments", "schedule": "daily",
     "policy_status": "allowed", "active": True, "max_pages": 25,
     "config": {"follow_links": True}, "policy_note": SARKARIYOJANA_NOTE},
    {"name": "SarkariYojana — scheme guides with reader comments",
     "url": "https://sarkariyojana.com/pradhan-mantri-awas-yojana-gramin-list/",
     "adapter": "html", "source_type": "publication", "category": "public_comments", "schedule": "weekly",
     "policy_status": "allowed", "active": True, "max_pages": 12,
     "config": {"seed_urls": [
         "https://sarkariyojana.com/pradhan-mantri-mudra-yojana/",
         "https://sarkariyojana.com/pmay-online-form/",
         "https://sarkariyojana.com/pm-awas-yojana-urban-2-0-blc-guidelines/",
         "https://sarkariyojana.com/pm-swamitva-yojana/",
     ], "follow_links": False}, "policy_note": SARKARIYOJANA_NOTE},
    {"name": "Kisan Call Centre query logs (data.gov.in OGD API)", "url": "https://api.data.gov.in/resource/",
     "adapter": "datagovin", "source_type": "open_data", "category": "public_queries", "schedule": "weekly",
     "policy_status": "credentials_required", "active": False, "max_pages": 10,
     "config": {"resource_id": "cef25fe2-9231-4128-8aec-2c948fedd43f", "role": "query", "page_size": 100,
                # Server-side filter: only calls categorised as government-scheme queries.
                "filters": {"QueryType": "Government Schemes"},
                "field_map": {"text": "QueryText", "state": "StateName", "district": "DistrictName",
                              "published_at": "CreatedOn", "id": "KCCCallID"}},
     "policy_note": "Official Open Government Data API (Ministry of Agriculture & Farmers Welfare). Requires "
                    "DATA_GOV_IN_API_KEY. QueryText is the call-centre operator's summary of the farmer's "
                    "question, not the farmer's verbatim words. State and district come from the dataset's own "
                    "columns. Records with identical summaries are de-duplicated."},

    # ── News / publications (informational; no gap detection) ─────────────
    {"name": "Down To Earth — news sitemap", "url": "https://www.downtoearth.org.in/news_sitemap.xml",
     "adapter": "sitemap", "source_type": "news", "category": "news", "schedule": "daily",
     "policy_status": "allowed", "active": True, "max_pages": 15, "config": {},
     "policy_note": "robots.txt allows all agents and publishes this sitemap. Only scheme-related URLs are fetched."},
    {"name": "Gaon Connection — recent articles sitemap",
     "url": "https://www.gaonconnection.com/staticsitemap/id-466/sitemap-48hours.xml",
     "adapter": "sitemap", "source_type": "news", "category": "news", "schedule": "daily",
     "policy_status": "allowed", "active": True, "max_pages": 15, "config": {},
     "policy_note": "robots.txt allows all agents and lists this sitemap."},
    {"name": "Krishi Jagran — government schemes", "url": "https://krishijagran.com/",
     "adapter": "html", "source_type": "publication", "category": "news", "schedule": "weekly",
     "policy_status": "allowed", "active": True, "max_pages": 15, "config": {"follow_links": True},
     "policy_note": "robots.txt allows all paths except /api/."},

    # ── Official portals (FAQ / guideline pages) ──────────────────────────
    {"name": "Vikaspedia — central schemes", "url": "https://en.vikaspedia.in/viewcontent/schemesall/central-schemes",
     "adapter": "html", "source_type": "official", "category": "official_portal", "schedule": "weekly",
     "policy_status": "allowed", "active": True, "max_pages": 15, "config": {"follow_links": True},
     "policy_note": "Government knowledge portal (MeitY/C-DAC). robots.txt permits these paths."},
    {"name": "PM-KISAN portal", "url": "https://pmkisan.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "PM-JAY portal", "url": "https://pmjay.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "MGNREGA portal", "url": "https://nrega.nic.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "PM Jan Dhan Yojana portal", "url": "https://pmjdy.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "PM Vishwakarma portal", "url": "https://pmvishwakarma.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "NSAP portal", "url": "https://nsap.nic.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "Mudra portal", "url": "https://www.mudra.org.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Official scheme portal."},
    {"name": "PIB press releases", "url": "https://pib.gov.in/allRel.aspx", "adapter": "html", "source_type": "official",
     "category": "official_portal", "schedule": "weekly", "policy_status": "allowed", "active": True,
     "max_pages": 8, "config": {"follow_links": True}, "policy_note": "Press Information Bureau."},

    # ── Registered but not collected (reasons recorded) ───────────────────
    {"name": "MyScheme.gov.in", "url": "https://www.myscheme.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "policy_status": "unsupported", "active": False,
     "policy_note": "Content is rendered client-side by JavaScript; the server HTML contains no scheme text. "
                    "A headless browser would be required, which this collector intentionally does not use."},
    {"name": "PMFBY portal", "url": "https://pmfby.gov.in/", "adapter": "html", "source_type": "official",
     "category": "official_portal", "policy_status": "unsupported", "active": False,
     "policy_note": "Single-page application; content is not present in server-rendered HTML."},
    {"name": "Quora — government scheme topics", "url": "https://www.quora.com/topic/Indian-Government-Schemes",
     "adapter": "html", "source_type": "forum", "category": "public_qa", "policy_status": "blocked", "active": False,
     "policy_note": "Requires login for full content and its terms prohibit automated collection."},
    {"name": "Commercial news topic pages (Indian Express, HT, NDTV, Mint, ET)",
     "url": "https://indianexpress.com/about/government-schemes/", "adapter": "html", "source_type": "news",
     "category": "news", "policy_status": "manual_review", "active": False,
     "policy_note": "Commercial publishers whose terms of use restrict automated reuse; not collected."},
]


def sync_registry(db: Session) -> dict:
    """Upsert curated sources by URL. Run statistics are never touched.
    Sources that are no longer curated are deactivated (kept for provenance)."""
    settings = get_settings()
    curated_urls = {e["url"] for e in REGISTRY}
    created = updated = 0
    for e in REGISTRY:
        src = db.query(Source).filter(Source.url == e["url"]).order_by(Source.id).first()
        if src is None:
            src = Source(url=e["url"], name=e["name"], verification_status="configured")
            db.add(src)
            created += 1
        else:
            updated += 1
        src.name = e["name"]
        src.source_type = e["source_type"]
        src.category = e.get("category")
        src.content_type = e["adapter"]
        src.collection_method = "api" if e["adapter"] in ("datagovin", "json_api") else "crawler"
        src.schedule = e.get("schedule", "manual")
        src.max_pages = e.get("max_pages")
        src.config = e.get("config") or {}
        src.policy_note = e.get("policy_note")
        status = e["policy_status"]
        active = e["active"]
        if e["adapter"] == "datagovin":
            ready = bool(settings.DATA_GOV_IN_API_KEY and (src.config or {}).get("resource_id"))
            status, active = ("allowed", True) if ready else ("credentials_required", False)
        if src.policy_status == "paused" and status == "allowed":
            active = False  # keep circuit-breaker pauses until an operator re-enables the source
            status = "paused"
        src.policy_status = status
        src.active = active
        src.api_available = e["adapter"] in ("datagovin", "json_api")
        src.auth_required = e["adapter"] == "datagovin"
    db.flush()
    canonical_ids = {db.query(Source.id).filter(Source.url == u).order_by(Source.id).first()[0] for u in curated_urls}
    retired = 0
    for src in db.query(Source).filter(Source.source_type != "csv_upload").all():
        superseded = src.url not in curated_urls or src.id not in canonical_ids  # duplicate registrations too
        if superseded and src.policy_status != "retired":
            src.active = False
            src.policy_status = "retired"
            src.policy_note = "Legacy registration superseded by the curated registry; kept for provenance."
            retired += 1
    db.add(AuditLog(action="sources_synced", entity_type="source", entity_id="registry", user="system",
                    description=f"Registry sync: {created} created, {updated} updated, {retired} retired",
                    created_at=datetime.now(timezone.utc)))
    db.commit()
    return {"created": created, "updated": updated, "retired": retired}
