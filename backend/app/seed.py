"""
Seed reference data (idempotent).

  * Scheme registry rows (from backend.app.nlp.schemes.DEFAULT_SCHEMES)
  * India states / union territories (for map reference)
  * Curated collection sources (backend.app.collection.registry)
  * The labelled research dataset, imported through the normal upload pipeline
    and processed synchronously (embeddings, NLP predictions, clustering)

Run: python -m backend.app.seed      (after: alembic upgrade head)
"""

import logging
from pathlib import Path

from backend.app.collection.registry import sync_registry
from backend.app.config import PROJECT_ROOT
from backend.app.database import SessionLocal
from backend.app.models.audit import AuditLog
from backend.app.models.geography import GeographicEntity
from backend.app.models.processing import DatasetVersion
from backend.app.models.scheme import Scheme
from backend.app.nlp.schemes import DEFAULT_SCHEMES

logger = logging.getLogger("seed")
INITIAL_DATASET = PROJECT_ROOT / "data" / "raw" / "welfare_awareness_dataset_with_split.csv"

STATES = [
    {"name": "Andhra Pradesh", "code": "AP", "iso_code": "IN-AP", "entity_type": "state", "latitude": 15.9129, "longitude": 79.7400},
    {"name": "Arunachal Pradesh", "code": "AR", "iso_code": "IN-AR", "entity_type": "state", "latitude": 28.2180, "longitude": 94.7278},
    {"name": "Assam", "code": "AS", "iso_code": "IN-AS", "entity_type": "state", "latitude": 26.2006, "longitude": 92.9376},
    {"name": "Bihar", "code": "BR", "iso_code": "IN-BR", "entity_type": "state", "latitude": 25.0961, "longitude": 85.3131},
    {"name": "Chhattisgarh", "code": "CT", "iso_code": "IN-CT", "entity_type": "state", "latitude": 21.2787, "longitude": 81.8661},
    {"name": "Goa", "code": "GA", "iso_code": "IN-GA", "entity_type": "state", "latitude": 15.2993, "longitude": 74.1240},
    {"name": "Gujarat", "code": "GJ", "iso_code": "IN-GJ", "entity_type": "state", "latitude": 22.2587, "longitude": 71.1924},
    {"name": "Haryana", "code": "HR", "iso_code": "IN-HR", "entity_type": "state", "latitude": 29.0588, "longitude": 76.0856},
    {"name": "Himachal Pradesh", "code": "HP", "iso_code": "IN-HP", "entity_type": "state", "latitude": 31.1048, "longitude": 77.1734},
    {"name": "Jharkhand", "code": "JH", "iso_code": "IN-JH", "entity_type": "state", "latitude": 23.6102, "longitude": 85.2799},
    {"name": "Karnataka", "code": "KA", "iso_code": "IN-KA", "entity_type": "state", "latitude": 15.3173, "longitude": 75.7139},
    {"name": "Kerala", "code": "KL", "iso_code": "IN-KL", "entity_type": "state", "latitude": 10.8505, "longitude": 76.2711},
    {"name": "Madhya Pradesh", "code": "MP", "iso_code": "IN-MP", "entity_type": "state", "latitude": 22.9734, "longitude": 78.6569},
    {"name": "Maharashtra", "code": "MH", "iso_code": "IN-MH", "entity_type": "state", "latitude": 19.7515, "longitude": 75.7139},
    {"name": "Manipur", "code": "MN", "iso_code": "IN-MN", "entity_type": "state", "latitude": 24.6637, "longitude": 93.9063},
    {"name": "Meghalaya", "code": "ML", "iso_code": "IN-ML", "entity_type": "state", "latitude": 25.4670, "longitude": 91.3662},
    {"name": "Mizoram", "code": "MZ", "iso_code": "IN-MZ", "entity_type": "state", "latitude": 23.1645, "longitude": 92.9376},
    {"name": "Nagaland", "code": "NL", "iso_code": "IN-NL", "entity_type": "state", "latitude": 26.1584, "longitude": 94.5624},
    {"name": "Odisha", "code": "OR", "iso_code": "IN-OR", "entity_type": "state", "latitude": 20.9517, "longitude": 85.0985},
    {"name": "Punjab", "code": "PB", "iso_code": "IN-PB", "entity_type": "state", "latitude": 31.1471, "longitude": 75.3412},
    {"name": "Rajasthan", "code": "RJ", "iso_code": "IN-RJ", "entity_type": "state", "latitude": 27.0238, "longitude": 74.2179},
    {"name": "Sikkim", "code": "SK", "iso_code": "IN-SK", "entity_type": "state", "latitude": 27.5330, "longitude": 88.5122},
    {"name": "Tamil Nadu", "code": "TN", "iso_code": "IN-TN", "entity_type": "state", "latitude": 11.1271, "longitude": 78.6569},
    {"name": "Telangana", "code": "TG", "iso_code": "IN-TG", "entity_type": "state", "latitude": 18.1124, "longitude": 79.0193},
    {"name": "Tripura", "code": "TR", "iso_code": "IN-TR", "entity_type": "state", "latitude": 23.9408, "longitude": 91.9882},
    {"name": "Uttar Pradesh", "code": "UP", "iso_code": "IN-UP", "entity_type": "state", "latitude": 26.8467, "longitude": 80.9462},
    {"name": "Uttarakhand", "code": "UK", "iso_code": "IN-UK", "entity_type": "state", "latitude": 30.0668, "longitude": 79.0193},
    {"name": "West Bengal", "code": "WB", "iso_code": "IN-WB", "entity_type": "state", "latitude": 22.9868, "longitude": 87.8550},
    # Union Territories
    {"name": "Andaman and Nicobar Islands", "code": "AN", "iso_code": "IN-AN", "entity_type": "union_territory", "latitude": 11.7401, "longitude": 92.6586},
    {"name": "Chandigarh", "code": "CH", "iso_code": "IN-CH", "entity_type": "union_territory", "latitude": 30.7333, "longitude": 76.7794},
    {"name": "Dadra and Nagar Haveli and Daman and Diu", "code": "DD", "iso_code": "IN-DD", "entity_type": "union_territory", "latitude": 20.1809, "longitude": 73.0169},
    {"name": "Delhi", "code": "DL", "iso_code": "IN-DL", "entity_type": "union_territory", "latitude": 28.7041, "longitude": 77.1025},
    {"name": "Jammu and Kashmir", "code": "JK", "iso_code": "IN-JK", "entity_type": "union_territory", "latitude": 33.7782, "longitude": 76.5762},
    {"name": "Ladakh", "code": "LA", "iso_code": "IN-LA", "entity_type": "union_territory", "latitude": 34.1526, "longitude": 77.5771},
    {"name": "Lakshadweep", "code": "LD", "iso_code": "IN-LD", "entity_type": "union_territory", "latitude": 10.5667, "longitude": 72.6417},
    {"name": "Puducherry", "code": "PY", "iso_code": "IN-PY", "entity_type": "union_territory", "latitude": 11.9416, "longitude": 79.8083},
]


def seed_schemes(db) -> int:
    n = 0
    for order, d in enumerate(DEFAULT_SCHEMES, start=1):
        row = db.query(Scheme).filter(Scheme.short_name == d.code).first() or Scheme(short_name=d.code)
        row.name, row.category, row.ministry, row.official_url = d.name, d.category, d.ministry, d.official_url
        row.aliases = ",".join(d.strong)
        row.weak_aliases = ",".join(d.weak)
        row.display_order, row.active = order, True
        db.add(row)
        n += 1
    db.commit()
    return n


def seed_geography(db) -> int:
    india = db.query(GeographicEntity).filter(GeographicEntity.code == "IN").first()
    if india is None:
        india = GeographicEntity(name="India", entity_type="country", code="IN", iso_code="IN",
                                 latitude=20.5937, longitude=78.9629)
        db.add(india)
        db.flush()
    added = 0
    for s in STATES:
        if not db.query(GeographicEntity.id).filter(GeographicEntity.code == s["code"]).first():
            db.add(GeographicEntity(parent_id=india.id, **s))
            added += 1
    db.commit()
    return added


def seed_dataset(db, path: Path = INITIAL_DATASET):
    import hashlib
    from backend.app.services import jobs
    from backend.app.services.dataset import import_dataset
    if not path.exists():
        return "missing"
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if db.query(DatasetVersion.id).filter(DatasetVersion.file_sha256 == sha).first():
        return "already imported"
    dv, job, summary = import_dataset(db, path.read_bytes(), path.name, name="Labelled research dataset",
                                      description="127 manually labelled public questions (train/val/test split)")
    jobs.run_job(job.id)
    return summary


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db = SessionLocal()
    try:
        print(f"Schemes: {seed_schemes(db)} upserted")
        print(f"Geography: {seed_geography(db)} states/UTs added")
        print(f"Sources: {sync_registry(db)}")
        print(f"Dataset: {seed_dataset(db)}")
        db.add(AuditLog(action="system", user="seed", description="Reference data seeded"))
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
