import json
import logging
from typing import Any, Sequence

from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langgraph.prebuilt import ToolRuntime

from backend.i18n import t

logger = logging.getLogger(__name__)
