"""Backward-compat shim — use msg_queue.manager.QueueManager instead."""

# This file is kept so existing imports don't break while whatsapp.py
# transitions to QueueManager.  New code should import from:
#   msg_queue.manager  — QueueManager, get_queue_manager
#   msg_queue.task     — QueueTask
#   msg_queue.models   — StreamChunk, QueueTaskPriority, …

from msg_queue.manager import QueueManager as MessageQueue  # noqa: F401
