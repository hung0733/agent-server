"""STM Dashboard Data Provider - Short-term memory from LangGraph checkpoints."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, List, Dict
from utils.timezone import to_server_tz, now_server
from graph.graph_store import GraphStore
from db.dao.agent_instance_dao import AgentInstanceDAO
from api.dashboard import _agent_display_name


@dataclass(slots=True)
class STMDataProvider:
    """Provide short-term memory summaries from LangGraph checkpoints."""
    
    async def get_stm(self, user_id=None) -> dict[str, Any]:
        """
        Get short-term memory summaries from LangGraph checkpoints.
        
        Returns:
            List of bullet point entries from current-day summaries.
        """
        try:
            agent_ids = await self._get_user_agent_ids(user_id)
            if not agent_ids:
                return {"entries": [], "hasMore": False, "source": "langgraph"}
            
            entries = await self._query_checkpoints(agent_ids)
            return {"entries": entries, "hasMore": False, "source": "langgraph"}
        
        except Exception as e:
            # Log error and return empty
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"STM query failed: {e}", exc_info=True)
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
    
    async def _query_checkpoints(self, agent_ids: list[str]) -> list[dict]:
        """
        Query langgraph.checkpoints table for current-day summaries.
        
        Args:
            agent_ids: List of agent IDs to filter
            
        Returns:
            List of bullet point entries.
        """
        if not GraphStore.pool:
            return []
        
        # Get current date in server timezone
        now_server_tz = now_server()
        start_of_today_server = now_server_tz.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        
        entries = []
        
        async with GraphStore.pool.connection() as conn:
            # Query checkpoints with summary
            # Note: LangGraph checkpoint timestamp is in checkpoint.ts field (JSONB)
            result = await conn.execute(
                """
                SELECT 
                    thread_id,
                    checkpoint_id,
                    checkpoint->'channel_values'->>'summary' as summary,
                    checkpoint->>'ts' as checkpoint_ts
                FROM langgraph.checkpoints
                WHERE 
                    (thread_id LIKE 'default-%' OR thread_id LIKE 'session-%')
                    AND checkpoint->'channel_values'->>'summary' IS NOT NULL
                    AND checkpoint->'channel_values'->>'summary' != ''
                ORDER BY checkpoint_id DESC
                LIMIT 50
                """
            )
            rows = await result.fetchall()
            
            # Parse bullet points and filter by current date
            for row in rows:
                thread_id = row[0]
                checkpoint_id = row[1]
                summary = row[2]
                checkpoint_ts_str = row[3]
                
                # Parse timestamp
                checkpoint_ts_server = None
                if checkpoint_ts_str:
                    try:
                        checkpoint_ts = datetime.fromisoformat(checkpoint_ts_str.replace('Z', '+00:00'))
                        checkpoint_ts_server = to_server_tz(checkpoint_ts)
                        
                        # Filter: only current day
                        if checkpoint_ts_server.date() != start_of_today_server.date():
                            continue
                    except Exception:
                        continue
                
                # Parse bullet points
                bullet_points = self._parse_summary_bullet_points(summary)
                
                # Create entry for each bullet point
                for idx, bullet in enumerate(bullet_points):
                    if not bullet.strip():
                        continue
                    
                    entry_id = f"{checkpoint_id}-bullet-{idx}"
                    
                    entries.append({
                        "id": entry_id,
                        "kind": "stm",
                        "agent": self._extract_agent_from_thread_id(thread_id),
                        "timestamp": checkpoint_ts_server.isoformat() if checkpoint_ts_server else datetime.now(timezone.utc).isoformat(),
                        "summary": bullet.strip(),
                        "sessionId": thread_id,
                        "sessionName": thread_id,
                        "status": "healthy"
                    })
        
        return entries
    
    def _parse_summary_bullet_points(self, summary: str) -> list[str]:
        """
        Split summary into bullet points.
        
        Args:
            summary: Summary text with bullet points
            
        Returns:
            List of bullet point strings.
        """
        # Split by common bullet point markers
        lines = summary.split('\n')
        bullet_points = []
        
        for line in lines:
            line = line.strip()
            # Check for bullet point markers: "- " or "• "
            if line.startswith('- ') or line.startswith('• '):
                bullet_points.append(line[2:])  # Remove marker
            elif line.startswith('-') or line.startswith('•'):
                bullet_points.append(line[1:])  # Remove marker
        
        return bullet_points
    
    def _extract_agent_from_thread_id(self, thread_id: str) -> str:
        """
        Extract agent name from thread_id.
        
        For now, just return thread_id as session name.
        Future: map session_id to agent_name.
        """
        return thread_id