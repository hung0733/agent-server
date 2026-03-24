import logging
from typing import Any, Dict, Optional
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from models.llm import LLMSet

logger = logging.getLogger(__name__)

class GraphNode:
    
    @staticmethod
    def prepare_chat_node_config(
        thread_id: str,
        model: LLMSet,
        sys_prompt: str,
        involves_secrets: bool,
        think_mode: Optional[bool],
        args: Optional[Dict[str, Any]] = None,
    ) -> RunnableConfig:
        return {
            "configurable": {
                "thread_id": thread_id,
                "model": model,
                "sys_prompt": sys_prompt,
                "involves_secrets": involves_secrets,
                "think_mode": think_mode,
                "args": args,
            }
        }
    
    @staticmethod
    def get_model(config:RunnableConfig, think_mode:bool = False) :
        # 由 config 攞返 LLM 同 System Prompt 出嚟
        models: LLMSet = config["configurable"]["model"]  # type: ignore
        opt_think_mode: Optional[bool] = config["configurable"]["think_mode"]  # type: ignore
        args: Dict[str, Any] = config["configurable"]["args"]  # type: ignore
        
        if opt_think_mode is not None:
            think_mode = opt_think_mode

        temperature = 0.6 if think_mode else 0.7
        top_p = 0.95 if think_mode else 0.7
        presence_penalty = 0.0 if think_mode else 0.3

        extra_body = {
            "top_k": 20,
            "repetition_penalty": 1.0 if think_mode else 1.1,
            "chat_template_kwargs": {"enable_thinking": think_mode},
        }

        if args is not None:
            try:
                if args.get("temperature"):
                    temperature = args["temperature"]
                if args.get("top_p"):
                    top_p = args["top_p"]
                if args.get("presence_penalty"):
                    presence_penalty = args["presence_penalty"]
                if args.get("top_k"):
                    extra_body["top_k"] = args["top_k"]
                if args.get("repetition_penalty"):
                    extra_body["repetition_penalty"] = args["repetition_penalty"]
            except Exception as e:
                logger.error(f"❌ 解析 args 失敗：{e}, args: {args}")
                raise
        
        return (models, temperature, top_p, presence_penalty, extra_body)