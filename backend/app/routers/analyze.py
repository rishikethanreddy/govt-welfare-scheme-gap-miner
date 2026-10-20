"""Analyze API — run the production NLP pipeline on a single text (nothing is stored)."""

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.database import get_db
from backend.app.nlp import embeddings
from backend.app.nlp.service import get_nlp_service
from backend.app.security import rate_limited

router = APIRouter(prefix="/api", tags=["Analysis"])


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=5, max_length=5000)
    text_role: str = Field("query", pattern="^(query|question|complaint|discussion|faq|news|article)$")


@router.post("/analyze", dependencies=[Depends(rate_limited)])
async def analyze(body: AnalyzeRequest, db: Session = Depends(get_db)):
    def work():
        from backend.app.routers.documents import _hydrate
        from backend.app.services.vector_index import VectorIndex
        vec = embeddings.encode([body.text])
        result = get_nlp_service().analyze_batch([body.text], [body.text_role], with_evidence=True, vecs=vec)[0]
        result["similar_records"] = {
            scope: _hydrate(db, VectorIndex.for_origin(db, scope).search(
                vec[0], k=5, min_similarity=get_settings().SIMILARITY_SEARCH_MIN))
            for scope in ("dataset", "live")
        }
        return result
    return await run_in_threadpool(work)
