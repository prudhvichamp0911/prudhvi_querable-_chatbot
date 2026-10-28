"""Optional Graphiti/Neo4j context for general answers.

Enabled with GRAPHITI_ENABLED=true and NEO4J_PASSWORD. Uses the existing
``GraphitiService``; failures are reported to the caller, which continues
without graph context.
"""

import asyncio

from backend.config import settings

_service = None
_lock = asyncio.Lock()

GROUP_ID = "queryable_chatbot"


async def _get_service():
    global _service
    async with _lock:
        if _service is None:
            if not settings.neo4j_password:
                raise RuntimeError("NEO4J_PASSWORD is not set")
            from backend.graphiti_service import GraphitiService

            service = GraphitiService(settings.neo4j_password)
            await service.initialize()
            _service = service
    return _service


async def search_context(question, num_results=5):
    service = await _get_service()
    results = await service.search_context(GROUP_ID, question, num_results)
    facts = [getattr(item, "fact", None) or str(item) for item in results or []]
    return "\n".join(f"- {fact}" for fact in facts[:num_results]) or None
