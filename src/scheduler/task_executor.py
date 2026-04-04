# pyright: reportMissingImports=false
"""
Task execution module for scheduled tasks.

Handles execution of two types of scheduled tasks:
1. Message tasks: Simulates user prompt to agent via Message Queue
2. Method tasks: Directly invokes static methods with agent_id

Import path: scheduler.task_executor
"""
from __future__ import annotations

import importlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from db.dao.agent_instance_dao import AgentInstanceDAO
from db.dto.task_dto import Task, TaskUpdate
from db.types import TaskStatus
from i18n import _

logger = logging.getLogger(__name__)


class TaskExecutor:
    """Main executor that dispatches tasks to appropriate handlers."""

    @staticmethod
    async def execute_task(task: Task) -> dict[str, Any]:
        """
        Execute a scheduled task based on its execution type.

        This method manages agent status lifecycle:
        1. Claims the agent (idle -> busy)
        2. Executes the task
        3. Releases the agent (busy -> idle)

        Args:
            task: The task to execute (must have payload with task_execution_type)

        Returns:
            dict with execution result: {"success": bool, "output": Any, "error": str?}

        Raises:
            ValueError: If task_execution_type is unknown or agent not available
            Exception: Various execution-specific exceptions
        """
        from uuid import UUID

        execution_type = (
            task.payload.get("task_execution_type") if task.payload else None
        )

        if not task.agent_id:
            raise ValueError(_("任務缺少 agent_id"))

        agent_instance_id = UUID(str(task.agent_id))

        # 1. Claim the agent (atomic idle -> busy transition)
        claimed = await AgentInstanceDAO.claim_agent_for_task(agent_instance_id)
        if not claimed:
            raise ValueError(
                _("Agent 不是 idle 狀態，無法執行任務: %s") % agent_instance_id
            )

        logger.info(
            _("[TaskExecutor] ✅ 已認領 agent: %s"), agent_instance_id
        )

        try:
            # 2. Execute the task
            if execution_type == "message":
                result = await MessageTaskExecutor.execute(task)
            elif execution_type == "agent_to_agent":
                result = await AgentToAgentTaskExecutor.execute(task)
            elif execution_type == "method":
                result = await MethodTaskExecutor.execute(task)
            else:
                raise ValueError(
                    _("未知的任務執行類型: %s (期望: message、agent_to_agent 或 method)") % execution_type
                )

            logger.info(
                _("[TaskExecutor] ✅ 任務執行完成: task_id=%s"), task.id
            )
            return result

        finally:
            # 3. Always release the agent back to idle (even on error)
            released = await AgentInstanceDAO.release_agent(agent_instance_id)
            if released:
                logger.info(
                    _("[TaskExecutor] ✅ 已釋放 agent: %s"), agent_instance_id
                )
            else:
                logger.warning(
                    _("[TaskExecutor] ⚠️ 釋放 agent 失敗: %s"), agent_instance_id
                )


class MessageTaskExecutor:
    """Executes message-type tasks by submitting to Message Queue."""

    @staticmethod
    async def execute(task: Task) -> dict[str, Any]:
        """
        Execute a message task via Message Queue.

        Submits the prompt to the Message Queue system, which handles the full
        pipeline (memory loading, LLM routing, tool execution, etc).
        Collects chunks and assembles them into a structured ReAct flow format.

        Args:
            task: Task with payload containing:
                - prompt: str - the user prompt
                - system_prompt: Optional[str] - custom system prompt (not used in MQ)
                - think_mode: Optional[bool] - whether to enable thinking

        Returns:
            {
                "success": True,
                "output": str - final answer (first 500 chars),
                "react_flow": dict - structured ReAct format,
                "session_id": str
            }

        Raises:
            ValueError: If agent not found or required fields missing
            Exception: If Message Queue processing fails
        """
        try:
            # 1. Get execution parameters from payload
            if not task.payload:
                raise ValueError(_("任務 payload 為空"))

            prompt = task.payload.get("prompt")
            if not prompt:
                raise ValueError(_("message 類型任務缺少 prompt 字段"))

            think_mode = task.payload.get("think_mode", False)

            if not task.agent_id:
                raise ValueError(_("任務缺少 agent_id"))

            logger.info(
                _(
                    "[MessageTaskExecutor] 正在執行 message 任務: task_id=%s, agent_id=%s"
                ),
                task.id,
                task.agent_id,
            )

            # 2. Get agent instance from agent_id
            from db.dao.agent_instance_dao import AgentInstanceDAO
            from uuid import UUID

            agent_instance_id_str = str(task.agent_id)
            agent_instance = await AgentInstanceDAO.get_by_id(
                UUID(agent_instance_id_str)
            )
            if not agent_instance or not agent_instance.agent_id:
                raise ValueError(
                    _("Agent instance 不存在或缺少 agent_id: %s")
                    % agent_instance_id_str
                )

            agent_id_str = agent_instance.agent_id

            # 3. Create new session ID for this execution
            session_id = f"ghost-{agent_id_str[6:]}"
            logger.debug(_("[MessageTaskExecutor] 創建新 session: %s"), session_id)

            # 4. Submit to Message Queue and collect ReAct flow
            from msg_queue.handler import MsgQueueHandler
            from msg_queue.models import QueueTaskPriority

            logger.debug(
                _(
                    "[MessageTaskExecutor] 提交消息到 Message Queue: "
                    "agent=%s, session=%s"
                ),
                agent_id_str,
                session_id,
            )

            # Collect chunks into structured ReAct flow
            react_flow = {
                "input": prompt,
                "thinking": None,  # Collect thinking chunks
                "actions": [],  # Collect tool calls
                "observations": [],  # Collect tool results
                "final_answer": None,  # Final response
            }

            thinking_parts = []

            try:
                async for chunk in MsgQueueHandler.create_msg_queue(
                    agent_id=agent_id_str,
                    session_id=session_id,
                    message=prompt,
                    think_mode=think_mode,
                    priority=QueueTaskPriority.NORMAL,
                    metadata={
                        "scheduled_task_id": str(task.id),
                        "task_id": str(task.id),
                        "source": "task_scheduler",
                    },
                ):
                    # Parse chunk into ReAct flow
                    if not hasattr(chunk, "chunk_type") or not hasattr(
                        chunk, "content"
                    ):
                        continue

                    chunk_type = getattr(chunk, "chunk_type", "")
                    chunk_content = getattr(chunk, "content", "")

                    if not chunk_content:
                        continue

                    # Categorize chunk into ReAct flow
                    if chunk_type == "think":
                        # AI thinking/reasoning
                        thinking_parts.append(str(chunk_content))

                    elif chunk_type == "tool" or "tool_call" in str(chunk_type):
                        # Tool invocation
                        react_flow["actions"].append(
                            {
                                "type": "tool_call",
                                "content": str(chunk_content),
                            }
                        )

                    elif chunk_type == "tool_result" or "observation" in str(
                        chunk_type
                    ):
                        # Tool result/observation
                        react_flow["observations"].append(
                            {
                                "type": "observation",
                                "content": str(chunk_content),
                            }
                        )

                    else:
                        # Main response content (final answer)
                        if react_flow["final_answer"] is None:
                            react_flow["final_answer"] = ""
                        react_flow["final_answer"] += str(chunk_content)

                # Assemble thinking if collected
                if thinking_parts:
                    react_flow["thinking"] = "\n".join(thinking_parts)

            except Exception as e:
                logger.error(
                    _("[MessageTaskExecutor] Message Queue 處理失敗: %s"),
                    str(e),
                    exc_info=True,
                )
                raise

            # 5. Assemble final output
            final_answer = react_flow["final_answer"] or ""

            logger.info(
                _(
                    "[MessageTaskExecutor] ✅ message 任務執行成功: "
                    "task_id=%s, has_answer=%s"
                ),
                task.id,
                bool(final_answer),
            )

            return {
                "success": True,
                "output": final_answer[:500] if final_answer else "",
                "react_flow": react_flow,
                "session_id": session_id,
            }

        except Exception as e:
            logger.error(
                _(
                    "[MessageTaskExecutor] ❌ message 任務執行失敗: task_id=%s, error=%s"
                ),
                task.id,
                str(e),
                exc_info=True,
            )
            raise


class AgentToAgentTaskExecutor:
    """Executes delegated agent-to-agent tasks asynchronously."""

    @staticmethod
    async def execute(task: Task) -> dict[str, Any]:
        if not task.payload:
            raise ValueError(_("任務 payload 為空"))

        sender = await AgentToAgentTaskExecutor._get_sender_agent(task)
        worker = await AgentToAgentTaskExecutor._select_sub_agent(task, sender.id)
        session = await AgentToAgentTaskExecutor._get_or_create_private_session(
            sender=sender,
            worker=worker,
        )
        worker_result = await AgentToAgentTaskExecutor._run_worker_task(
            sender=sender,
            worker=worker,
            session_id=session.session_id,
            task=task,
        )
        review_result = await AgentToAgentTaskExecutor._review_worker_result(
            sender=sender,
            task=task,
            worker_result=worker_result,
        )

        callback_result = None
        if review_result.get("accepted"):
            callback_result = await AgentToAgentTaskExecutor._dispatch_callback(
                task.payload.get("callback") or {},
                review_result.get("response") or worker_result.get("output", ""),
            )

        return {
            "success": bool(review_result.get("accepted")),
            "selected_agent_id": str(worker.id),
            "session_id": session.session_id,
            "worker_output": worker_result.get("output", ""),
            "worker_react_flow": worker_result.get("react_flow"),
            "manager_verdict": "accepted" if review_result.get("accepted") else "rejected",
            "manager_reason": review_result.get("reason", ""),
            "callback_result": callback_result,
            "final_response": review_result.get("response") or worker_result.get("output", ""),
        }

    @staticmethod
    async def _get_sender_agent(task: Task):
        from db.dao.agent_instance_dao import AgentInstanceDAO

        requester_agent_id = (task.payload or {}).get("requester_agent_id")
        if not requester_agent_id:
            raise ValueError(_("agent_to_agent 任務缺少 requester_agent_id"))

        sender = await AgentInstanceDAO.get_by_id(uuid.UUID(str(requester_agent_id)))
        if sender is None:
            raise ValueError(_("找不到 sender agent: %s") % requester_agent_id)
        return sender

    @staticmethod
    async def _select_sub_agent(task: Task, sender_agent_id: uuid.UUID):
        from db.dao.agent_instance_dao import AgentInstanceDAO

        idle_agents = await AgentInstanceDAO.get_idle_agents()
        for agent in idle_agents:
            if (
                agent.user_id == task.user_id
                and agent.is_sub_agent
                and agent.id != sender_agent_id
                and agent.agent_id
            ):
                return agent
        raise ValueError(_("沒有可用的 idle sub-agent"))

    @staticmethod
    async def _get_or_create_private_session(sender, worker):
        from db.dao.collaboration_session_dao import CollaborationSessionDAO
        from db.dto.collaboration_dto import CollaborationSessionCreate

        session = await CollaborationSessionDAO.get_private_session(
            user_id=sender.user_id,
            sender_agent_id=sender.id,
            main_agent_id=worker.id,
        )
        if session is not None:
            return session

        return await CollaborationSessionDAO.create(
            CollaborationSessionCreate(
                user_id=sender.user_id,
                main_agent_id=worker.id,
                sender_agent_id=sender.id,
                session_id=f"session-{uuid.uuid4()}",
                name=f"{sender.name} -> {worker.name}",
            )
        )

    @staticmethod
    async def _run_worker_task(sender, worker, session_id: str, task: Task) -> dict[str, Any]:
        from msg_queue.handler import MsgQueueHandler
        from msg_queue.models import QueueTaskPriority

        content_parts: list[str] = []
        react_flow: dict[str, Any] = {
            "input": task.payload.get("instruction", ""),
            "thinking": None,
            "actions": [],
            "observations": [],
            "final_answer": None,
        }
        thinking_parts: list[str] = []

        async for chunk in MsgQueueHandler.create_msg_queue(
            agent_id=worker.agent_id,
            session_id=session_id,
            message=task.payload.get("instruction", ""),
            sender_agent_id=str(sender.id),
            think_mode=False,
            priority=QueueTaskPriority.NORMAL,
            metadata={
                "source": "agent_to_agent",
                "task_id": str(task.id),
                "sender_agent_id": str(sender.id),
            },
        ):
            if chunk.chunk_type == "think" and chunk.content:
                thinking_parts.append(chunk.content)
            elif chunk.chunk_type == "tool" and chunk.content:
                react_flow["actions"].append({"type": "tool_call", "content": str(chunk.content)})
            elif chunk.chunk_type == "tool_result" and chunk.content:
                react_flow["observations"].append({"type": "observation", "content": str(chunk.content)})
            elif chunk.chunk_type == "content" and chunk.content:
                content_parts.append(chunk.content)

        final_output = "".join(content_parts).strip()
        if thinking_parts:
            react_flow["thinking"] = "\n".join(thinking_parts)
        react_flow["final_answer"] = final_output
        return {
            "output": final_output,
            "react_flow": react_flow,
            "session_id": session_id,
        }

    @staticmethod
    async def _review_worker_result(sender, task: Task, worker_result: dict[str, Any]) -> dict[str, Any]:
        from agent.bulter import Bulter
        from msg_queue.handler import MsgQueueHandler
        from msg_queue.models import QueueTaskPriority

        goal = task.payload.get("goal", "")
        instruction = task.payload.get("instruction", "")
        review_session_id = f"review-a2a-{uuid.uuid4()}"
        sender_agent = await Bulter.get_agent(sender.agent_id, review_session_id)
        sender_prompt = await sender_agent.get_memory_prompt()
        sender_prompt = (
            f"{sender_prompt}\n\n[最終目標]\n{goal}\n\n"
            "你而家要驗收另一個 sub-agent 嘅輸出。"
            "你必須只輸出 JSON，格式："
            '{"accepted": true|false, "reason": "...", "response": "..."}'
        )
        review_message = (
            "請根據最終目標驗收以下 sub-agent 輸出。\n\n"
            f"[Instruction]\n{instruction}\n\n"
            f"[Worker Output]\n{worker_result.get('output', '')}\n"
        )

        content_parts: list[str] = []
        async for chunk in MsgQueueHandler.create_msg_queue(
            agent_id=sender.agent_id,
            session_id=review_session_id,
            message=review_message,
            sender_agent_id=str(sender.id),
            system_prompt=sender_prompt,
            think_mode=False,
            priority=QueueTaskPriority.NORMAL,
            metadata={
                "source": "review_msg",
                "task_id": str(task.id),
                "thread_id_override": review_session_id,
                "sender_agent_id": str(sender.id),
            },
        ):
            if chunk.chunk_type == "content" and chunk.content:
                content_parts.append(chunk.content)

        raw_output = "".join(content_parts).strip()
        try:
            parsed = json.loads(raw_output)
        except json.JSONDecodeError:
            return {
                "accepted": False,
                "reason": _("sender review 輸出唔係有效 JSON"),
                "response": worker_result.get("output", ""),
            }

        return {
            "accepted": bool(parsed.get("accepted")),
            "reason": str(parsed.get("reason") or ""),
            "response": str(parsed.get("response") or worker_result.get("output", "")),
        }

    @staticmethod
    async def _dispatch_callback(callback: dict[str, Any], message: str) -> dict[str, Any]:
        from channels.whatsapp import WhatsAppChannel

        channel = callback.get("channel")
        if channel != "whatsapp":
            raise ValueError(_("未支援的 callback channel: %s") % channel)

        target = str(callback.get("target") or "").lstrip("+")
        reply_context = callback.get("reply_context") or {}
        instance_id = reply_context.get("instance_id")
        if not instance_id or not target:
            raise ValueError(_("whatsapp callback 缺少 instance_id 或 target"))

        await WhatsAppChannel().send_text(str(instance_id), target, message)
        return {"status": "sent", "channel": channel, "target": target}


class MethodTaskExecutor:
    """Executes method-type tasks by invoking static methods directly."""

    @staticmethod
    async def execute(task: Task) -> dict[str, Any]:
        """
        Execute a method task.

        Dynamically imports and invokes a static method,
        passing the agent_id as a parameter.

        Args:
            task: Task with payload containing:
                - method_path: str - "module.path@ClassName.method_name"
                  Example: "src.agent.bulter@Bulter.review_ltm"

        Returns:
            {"success": True, "output": method_result}

        Raises:
            ValueError: If method_path is invalid or method not found
            Exception: If method execution fails
        """
        try:
            # 1. Get method path from payload
            if not task.payload:
                raise ValueError(_("任務 payload 為空"))

            method_path = task.payload.get("method_path")
            if not method_path:
                raise ValueError(_("method 類型任務缺少 method_path 字段"))

            if not task.agent_id:
                raise ValueError(_("任務缺少 agent_id"))

            logger.info(
                _(
                    "[MethodTaskExecutor] 正在執行 method 任務: task_id=%s, method_path=%s, agent_id=%s"
                ),
                task.id,
                method_path,
                task.agent_id,
            )

            # 2. Parse method_path: "src.agent.bulter@Bulter.review_ltm"
            if "@" not in method_path:
                raise ValueError(
                    _(
                        "method_path 格式無效: %s (期望: module.path@ClassName.method_name)"
                    )
                    % method_path
                )

            module_path_str, class_method_str = method_path.split("@", 1)

            if "." not in class_method_str:
                raise ValueError(
                    _("class_method 格式無效: %s (期望: ClassName.method_name)")
                    % class_method_str
                )

            class_name, method_name = class_method_str.rsplit(".", 1)

            logger.debug(
                _("[MethodTaskExecutor] 解析路徑: module=%s, class=%s, method=%s"),
                module_path_str,
                class_name,
                method_name,
            )

            # 3. Dynamic import
            try:
                module = importlib.import_module(module_path_str)
                logger.debug(
                    _("[MethodTaskExecutor] ✅ 模塊導入成功: %s"), module_path_str
                )
            except ImportError as e:
                raise ValueError(_("無法導入模塊: %s (%s)") % (module_path_str, str(e)))

            # 4. Get class
            try:
                cls = getattr(module, class_name)
                logger.debug(_("[MethodTaskExecutor] ✅ 類獲取成功: %s"), class_name)
            except AttributeError as e:
                raise ValueError(
                    _("模塊 %s 中不存在類: %s (%s)")
                    % (module_path_str, class_name, str(e))
                )

            # 5. Get method
            try:
                method = getattr(cls, method_name)
                logger.debug(_("[MethodTaskExecutor] ✅ 方法獲取成功: %s"), method_name)
            except AttributeError as e:
                raise ValueError(
                    _("類 %s 中不存在方法: %s (%s)") % (class_name, method_name, str(e))
                )

            # 6. Get the actual agent_id string from agent_instance
            from db.dao.agent_instance_dao import AgentInstanceDAO
            from uuid import UUID

            agent_instance_id = task.agent_id
            if not agent_instance_id:
                raise ValueError(_("任務缺少 agent_id"))

            # Look up agent instance to get the agent_id string
            agent_instance = await AgentInstanceDAO.get_by_id(UUID(str(agent_instance_id)))
            if not agent_instance or not agent_instance.agent_id:
                raise ValueError(
                    _("Agent instance 不存在或缺少 agent_id: %s")
                    % str(agent_instance_id)
                )

            agent_id_str = agent_instance.agent_id
            logger.debug(
                _("[MethodTaskExecutor] 正在調用方法，agent_id=%s (instance_id=%s)"),
                agent_id_str,
                agent_instance_id,
            )

            try:
                # Check if it's an async method
                import inspect

                if inspect.iscoroutinefunction(method):
                    result = await method(agent_id=agent_id_str)
                else:
                    result = method(agent_id=agent_id_str)

                logger.info(
                    _(
                        "[MethodTaskExecutor] ✅ method 任務執行成功: task_id=%s, method=%s, result_len=%d"
                    ),
                    task.id,
                    method_path,
                    len(str(result)) if result else 0,
                )

                return {
                    "success": True,
                    "output": str(result)[:500] if result else "",  # Summary
                    "method_path": method_path,
                    "agent_id": agent_id_str,
                }

            except TypeError as e:
                # Method doesn't accept agent_id parameter
                logger.warning(
                    _(
                        "[MethodTaskExecutor] ⚠️ 方法不接受 agent_id 參數，嘗試無參調用: %s"
                    ),
                    str(e),
                )
                try:
                    import inspect

                    if inspect.iscoroutinefunction(method):
                        result = await method()
                    else:
                        result = method()

                    logger.info(
                        _(
                            "[MethodTaskExecutor] ✅ method 任務執行成功（無參）: task_id=%s"
                        ),
                        task.id,
                    )

                    return {
                        "success": True,
                        "output": str(result)[:500] if result else "",
                        "method_path": method_path,
                        "note": "method called without agent_id parameter",
                    }
                except Exception as e2:
                    raise ValueError(_("方法調用失敗（嘗試無參調用）: %s") % str(e2))

        except Exception as e:
            logger.error(
                _("[MethodTaskExecutor] ❌ method 任務執行失敗: task_id=%s, error=%s"),
                task.id,
                str(e),
                exc_info=True,
            )
            raise
