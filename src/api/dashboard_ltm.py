"""LTM Dashboard Data Provider - Long-term memory from Qdrant vector store."""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List
from ltm.database.vector_store import QdrantVectorStore
from ltm.models.memory_entry import MemoryEntry
from db.dao.agent_instance_dao import AgentInstanceDAO
from api.dashboard import _agent_display_name


@dataclass(slots=True)
class LTMDataProvider:
    """Provide long-term memory entries from Qdrant vector store."""
    
    async def get_ltm(self, user_id=None, agent_ids=None) -> dict[str, Any]:
        """
        Get long-term memory entries from Qdrant.
        
        Args:
            user_id: Optional user ID for filtering
            agent_ids: Optional list of agent IDs to filter
            
        Returns:
            Dictionary with entries, hasMore, source
        """
        try:
            if agent_ids is None:
                agent_ids = await self._get_user_agent_ids(user_id)
            
            if not agent_ids:
                return {"entries": [], "hasMore": False, "source": "qdrant"}
            
            entries = await self._query_qdrant_multi_agent(agent_ids)
            return {"entries": entries, "hasMore": False, "source": "qdrant"}
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"LTM query failed: {e}", exc_info=True)
            return {"entries": [], "hasMore": False, "source": "error"}
    
    async def _get_user_agent_ids(self, user_id=None) -> list[str]:
        """Get list of agent instance IDs for user."""
        try:
            if user_id:
                agents = await AgentInstanceDAO.get_by_user_id(user_id, limit=100)
            else:
                agents = await AgentInstanceDAO.get_all(limit=100)
            return [str(agent.id) for agent in agents]
        except Exception:
            return []
    
    async def _query_qdrant_multi_agent(self, agent_ids: list[str]) -> list[dict]:
        """
        Query Qdrant for entries across multiple agents.
        
        Args:
            agent_ids: List of agent IDs to query (DB format without 'agent-' prefix)
            
        Returns:
            List of formatted entries
        """
        from ltm.database.vector_store import QdrantVectorStore
        from ltm import config as ltm_config
        from qdrant_client import QdrantClient
        
        try:
            client = QdrantClient(
                host=ltm_config.QDRANT_HOST,
                port=ltm_config.QDRANT_PORT,
            )
            
            # Add 'agent-' prefix to match Qdrant payload format
            qdrant_agent_ids = [f"agent-{aid}" if not aid.startswith("agent-") else aid for aid in agent_ids]
            
            entries = QdrantVectorStore.query_multi_agent(
                client=client,
                agent_ids=qdrant_agent_ids,
                collection_name=ltm_config.QDRANT_COLLECTION_NAME,
                limit=50
            )
            
            # Build agent name lookup
            agent_name_lookup = await self._get_agent_name_lookup(agent_ids)
            
            formatted_entries = []
            for entry in entries:
                # Map agent_id to name
                agent_id_raw = entry.agent_id.replace("agent-", "") if entry.agent_id else ""
                agent_name = agent_name_lookup.get(agent_id_raw, entry.agent_id or "Unknown")
                formatted_entries.append(self._format_entry(entry, agent_name))
            
            formatted_entries.sort(key=lambda x: x["timestamp"], reverse=True)
            return formatted_entries[:50]
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Qdrant multi-agent query failed: {e}", exc_info=True)
            return []
    
    async def _get_agent_name_lookup(self, agent_ids: list[str]) -> dict[str, str]:
        """
        Build lookup mapping agent ID to display name.
        
        Args:
            agent_ids: List of agent IDs (DB format without 'agent-' prefix)
            
        Returns:
            Dict mapping agent_id -> agent_name
        """
        try:
            from uuid import UUID
            lookup = {}
            for aid in agent_ids:
                try:
                    agent = await AgentInstanceDAO.get_by_id(UUID(aid))
                    lookup[aid] = _agent_display_name(agent) if agent else aid
                except Exception:
                    lookup[aid] = aid
            return lookup
        except Exception:
            return {}
    
    def _format_entry(self, entry: MemoryEntry, agent_id: str) -> dict:
        """
        Format MemoryEntry for API response.
        
        Args:
            entry: MemoryEntry from Qdrant
            agent_id: Agent ID
            
        Returns:
            Formatted dictionary
        """
        timestamp = entry.timestamp or datetime.now(timezone.utc).isoformat()
        
        return {
            "id": entry.entry_id,
            "kind": "ltm",
            "agent": agent_id,
            "timestamp": timestamp,
            "summary": entry.lossless_restatement,
            "keywords": entry.keywords,
            "persons": entry.persons,
            "entities": entry.entities,
            "topic": entry.topic,
            "location": entry.location,
            "status": "healthy",
        }