from typing import Any, Dict

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from langchain_core.language_models.chat_models import BaseChatModel

from db.dto.llm_endpoint_dto import (
    LLMEndpoint,
    LLMEndpointWithLevel,
    LLMLevelEndpointBase,
)
from utils.tools import Tools


class LLMSet(BaseModel):
    rte_model: BaseChatModel
    level: Dict[int, list[LLMEndpoint]]
    sec_level: Dict[int, list[LLMEndpoint]]

    def __init__(
        self,
        rte_model: BaseChatModel,
        level: Dict[int, list[LLMEndpoint]],
        sec_level: Dict[int, list[LLMEndpoint]],
    ):
        self.rte_model = rte_model
        self.level = level
        self.sec_level = sec_level

    @classmethod
    def from_model(cls, end_points: list[LLMEndpointWithLevel]):
        rte_model: BaseChatModel = ChatOpenAI(
            base_url=Tools.require_env("ROUTING_LLM_ENDPOINT"),
            api_key=SecretStr(Tools.require_env("ROUTING_LLM_API_KEY")),
            model=Tools.require_env("ROUTING_LLM_MODEL"),
            streaming=True,
        )
        level: Dict[int, list[LLMEndpoint]] = {1: [], 2: [], 3: []}
        sec_level: Dict[int, list[LLMEndpoint]] = {1: [], 2: [], 3: []}

        for ep in end_points:
            if not ep.is_active:
                continue
            target = sec_level if ep.involves_secrets else level
            target[ep.difficulty_level].append(ep)  # type: ignore[arg-type]

        return cls(rte_model=rte_model, level=level, sec_level=sec_level)
