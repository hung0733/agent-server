from typing import Dict, Optional

from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel, ConfigDict, SecretStr

from backend.client.openai import OpenAIClient
from backend.dao import AgentDAO, LlmEndpointDAO, LlmLevelDAO
from backend.db.session import async_session_factory
from backend.dto.llm_endpoint import LlmEndpointRead
from backend.i18n import t
from backend.utils.tools import Tools


class LLMSet(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rte_model: OpenAIClient
    sys_act_model: OpenAIClient
    level: Dict[int, list[LlmEndpointRead]]
    sec_level: Dict[int, list[LlmEndpointRead]]

    @classmethod
    async def from_model(cls, agent_db_id: int) -> "LLMSet":
        async with async_session_factory() as session:
            level, sec_level = await cls._load_levels(session, agent_db_id)

        return cls(
            rte_model=await LLMSet.getRteModel(),
            sys_act_model=await LLMSet.getSysActModel(),
            level=level,
            sec_level=sec_level,
        )

    @staticmethod
    async def _load_levels(
        session: AsyncSession, agent_db_id: int
    ) -> tuple[Dict[int, list[LlmEndpointRead]], Dict[int, list[LlmEndpointRead]]]:
        level: Dict[int, list[LlmEndpointRead]] = {1: [], 2: [], 3: []}
        sec_level: Dict[int, list[LlmEndpointRead]] = {1: [], 2: [], 3: []}

        agent = await AgentDAO(session).get_by_id(agent_db_id)
        if agent is None:
            raise LookupError(t("llm.agent_not_found") % agent_db_id)

        endpoint_dao = LlmEndpointDAO(session)
        llm_levels = await LlmLevelDAO(session).list_by_llm_group_id(agent.llm_group_id)
        for llm_level in llm_levels:
            endpoint = await endpoint_dao.get_by_id(llm_level.llm_endpoint_id)
            if endpoint is None:
                continue

            target = sec_level if llm_level.is_confidential else level
            target.setdefault(llm_level.level, []).append(
                LlmEndpointRead.model_validate(endpoint)
            )

        return level, sec_level

    def getModel(self, level: int, is_sec: bool = False) -> Optional[ChatOpenAI]:
        models: Dict[int, list[LlmEndpointRead]] = (
            self.sec_level if is_sec else self.level
        )

        for model in models[level]:
            if not model.model_name:
                continue

            return ChatOpenAI(
                base_url=model.endpoint,
                api_key=SecretStr("NO_KEY" if not model.enc_key else model.enc_key),
                model=model.model_name,
            )

        return None

    @staticmethod
    async def getModelByName(name: str) -> OpenAIClient:
        async with async_session_factory() as session:
            endpoint = await LlmEndpointDAO(session).list_by_sys_llm_name(name)

        if endpoint is None:
            raise RuntimeError(t("llm.system_endpoint_not_found") % name)
        if not endpoint.model_name:
            raise RuntimeError(t("llm.system_endpoint_model_missing") % name)

        return OpenAIClient(
            base_url=endpoint.endpoint,
            api_key=endpoint.enc_key or "NO_KEY",
            model=endpoint.model_name,
        )

    @staticmethod
    async def getRteModel() -> OpenAIClient:
        return await LLMSet.getModelByName(Tools.require_env("ROUTING_LLM_REC_NAME"))

    @staticmethod
    async def getSysActModel() -> OpenAIClient:
        return await LLMSet.getModelByName(Tools.require_env("SYS_ACT_LLM_REC_NAME"))
