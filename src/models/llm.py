import logging
from typing import Any, Dict

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, SecretStr
from langchain_core.language_models.chat_models import BaseChatModel

from db.dto.llm_endpoint_dto import (
    LLMEndpoint,
    LLMEndpointWithLevel,
    LLMLevelEndpointBase,
)
from i18n import _
from utils.tools import Tools

logger = logging.getLogger(__name__)


class LLMSet(BaseModel):
    rte_model: BaseChatModel
    level: Dict[int, list[LLMEndpoint]]
    sec_level: Dict[int, list[LLMEndpoint]]

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def from_model(cls, end_points: list[LLMEndpointWithLevel]):
        logger.debug(_("LLMSet.from_model: 收到 %d 個端點"), len(end_points))

        rte_model: BaseChatModel = ChatOpenAI(
            base_url=Tools.require_env("ROUTING_LLM_ENDPOINT"),
            api_key=SecretStr(Tools.require_env("ROUTING_LLM_API_KEY")),
            model=Tools.require_env("ROUTING_LLM_MODEL"),
            streaming=True,
        )
        level: Dict[int, list[LLMEndpoint]] = {1: [], 2: [], 3: []}
        sec_level: Dict[int, list[LLMEndpoint]] = {1: [], 2: [], 3: []}

        active_count = 0
        for ep in end_points:
            logger.debug(
                _("端點: %s, 難度: %d, 啟用: %s, 涉密: %s"),
                ep.name,
                ep.difficulty_level,
                ep.is_active,
                ep.involves_secrets,
            )
            if not ep.is_active:
                logger.debug(_("跳過非啟用端點: %s"), ep.name)
                continue
            active_count += 1
            target = sec_level if ep.involves_secrets else level
            target[ep.difficulty_level].append(ep)  # type: ignore[arg-type]

        logger.debug(
            _("LLMSet: 啟用 %d/%d 個端點。Level 1: %d, Level 2: %d, Level 3: %d"),
            active_count,
            len(end_points),
            len(level[1]),
            len(level[2]),
            len(level[3]),
        )

        return cls(rte_model=rte_model, level=level, sec_level=sec_level)
