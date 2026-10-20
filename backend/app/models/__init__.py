"""Database models package. Import all models here for Alembic discovery."""

from backend.app.models.document import Document
from backend.app.models.scheme import Scheme
from backend.app.models.source import Source, SourceRun
from backend.app.models.processing import DatasetVersion, ProcessingJob
from backend.app.models.cluster import Cluster, DocumentCluster
from backend.app.models.geography import GeographicEntity
from backend.app.models.model_version import ModelVersion
from backend.app.models.audit import AuditLog
from backend.app.models.crawl import CrawlUrl, CrawlPage, CollectionCampaign, CollectionEvent
from backend.app.models.embedding import DocumentEmbedding, SystemState

__all__ = [
    "Document",
    "Scheme",
    "Source",
    "SourceRun",
    "DatasetVersion",
    "ProcessingJob",
    "Cluster",
    "DocumentCluster",
    "GeographicEntity",
    "ModelVersion",
    "AuditLog",
    "CrawlUrl",
    "CrawlPage",
    "CollectionCampaign",
    "CollectionEvent",
    "DocumentEmbedding",
    "SystemState",
]
