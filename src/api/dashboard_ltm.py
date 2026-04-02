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
            agent_ids: List of agent IDs to query
            
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
            
            entries = []
            
            for agent_id in agent_ids:
                store = QdrantVectorStore(
                    client=client,
                    agent_id=agent_id,
                    collection_name=ltm_config.QDRANT_COLLECTION_NAME,
                )
                
                agent_entries = store.get_all_entries()
                
                for entry in agent_entries:
                    entries.append(self._format_entry(entry, agent_id))
            
            entries.sort(key=lambda x: x["timestamp"], reverse=True)
            return entries[:50]
        
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Qdrant multi-agent query failed: {e}", exc_info=True)
            return []
    
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