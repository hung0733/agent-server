from backend.dao.base import BaseDAO
from backend.entities.llm_usage import LlmUsage


class LlmUsageDAO(BaseDAO[LlmUsage]):
    model = LlmUsage
