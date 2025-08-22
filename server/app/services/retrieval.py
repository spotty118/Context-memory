"""
Context retrieval service implementing the scoring algorithm for context recall.
"""
import math
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime, timedelta
from sqlalchemy import and_, or_, func, text, select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.db.models import SemanticItem, EpisodicItem, UsageStats
from app.core.config import settings

logger = structlog.get_logger(__name__)


class ContextRetriever:
    """Retrieves relevant context using the weighted scoring algorithm."""
    
    def __init__(self) -> None:
        # Scoring weights from requirements
        self.weights = {
            'task_relevance': 0.28,
            'decision_impact': 0.22,
            'recency': 0.16,
            'graph_degree': 0.12,
            'failure_impact': 0.12,
            'usage_frequency': 0.08,
            'redundancy_penalty': -0.06,
        }
    
    async def recall_context(
        self,
        thread_id: str,
        purpose: str,
        token_budget: Optional[int] = None,
        db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        """
        Recall relevant context based on purpose and scoring algorithm.
        
        Args:
            thread_id: Thread ID for context scope
            purpose: Purpose/query for recall
            token_budget: Optional token budget for response
            db: Database session
            
        Returns:
            Dict containing globals, focus_ids, artifact_refs, and token_estimate
        """
        token_budget = token_budget or settings.DEFAULT_WORKING_SET_TOKEN_BUDGET
        
        logger.info("context_recall_started",
                   thread_id=thread_id,
                   purpose=purpose,
                   token_budget=token_budget)
        
        # Get all items for the thread
        semantic_items = await self._get_semantic_items(thread_id, db)
        episodic_items = await self._get_episodic_items(thread_id, db)
        
        # Score all items
        scored_semantic = await self._score_semantic_items(
            semantic_items, purpose, thread_id, db
        )
        scored_episodic = await self._score_episodic_items(
            episodic_items, purpose, thread_id, db
        )
        
        # Select top items within token budget
        selected_items = self._select_items_by_budget(
            scored_semantic + scored_episodic, token_budget
        )
        
        # Extract globals and focus items
        globals_data = self._extract_globals(selected_items)
        focus_ids = [item['id'] for item in selected_items]
        artifact_refs = self._extract_artifact_refs(selected_items)
        
        # Estimate token usage
        token_estimate = self._estimate_tokens(selected_items, globals_data, artifact_refs)
        
        logger.info("context_recall_completed",
                   thread_id=thread_id,
                   semantic_count=len([i for i in selected_items if i['id'].startswith('S')]),
                   episodic_count=len([i for i in selected_items if i['id'].startswith('E')]),
                   artifact_count=len(artifact_refs),
                   token_estimate=token_estimate)
        
        return {
            'thread_id': thread_id,
            'globals': globals_data,
            'focus_ids': focus_ids,
            'artifact_refs': artifact_refs,
            'token_estimate': token_estimate,
        }
    
    async def _get_semantic_items(self, thread_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get all semantic items for a thread."""
        result = await db.execute(
            select(SemanticItem).where(SemanticItem.thread_id == thread_id)
        )
        items = result.scalars().all()
        
        return [
            {
                'id': item.id,
                'thread_id': item.thread_id,
                'kind': item.kind,
                'title': item.title,
                'body': item.body,
                'status': item.status,
                'tags': item.tags or [],
                'links': item.links or {},
                'salience': item.salience,
                'created_at': item.created_at,
                'updated_at': item.updated_at,
            }
            for item in items
        ]
    
    async def _get_episodic_items(self, thread_id: str, db: AsyncSession) -> List[Dict[str, Any]]:
        """Get all episodic items for a thread."""
        result = await db.execute(
            select(EpisodicItem).where(EpisodicItem.thread_id == thread_id)
        )
        items = result.scalars().all()
        
        return [
            {
                'id': item.id,
                'thread_id': item.thread_id,
                'kind': item.kind,
                'title': item.title,
                'snippet': item.snippet,
                'source': item.source,
                'salience': item.salience,
                'created_at': item.created_at,
            }
            for item in items
        ]
    
    async def _score_semantic_items(
        self, 
        items: List[Dict[str, Any]], 
        purpose: str, 
        thread_id: str,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """Score semantic items using the weighted algorithm."""
        scored_items = []
        
        # Calculate graph degrees (reference counts)
        graph_degrees = self._calculate_graph_degrees(items)
        
        for item in items:
            score_components = {}
            
            # Task Relevance (0.28)
            score_components['task_relevance'] = self._calculate_task_relevance(
                item, purpose
            )
            
            # Decision Impact (0.22)
            score_components['decision_impact'] = self._calculate_decision_impact(item)
            
            # Recency (0.16)
            score_components['recency'] = self._calculate_recency(item)
            
            # Graph Degree (0.12)
            score_components['graph_degree'] = graph_degrees.get(item['id'], 0.0)
            
            # Failure Impact (0.12)
            score_components['failure_impact'] = self._calculate_failure_impact(item)
            
            # Usage Frequency (0.08)
            stats = await self._get_item_usage_stats(item['id'], db)
            score_components['usage_frequency'] = self._calculate_usage_frequency(stats)
            
            # Redundancy Penalty (-0.06)
            score_components['redundancy_penalty'] = self._calculate_redundancy_penalty(
                item, items
            )
            
            # Calculate final weighted score
            final_score = sum(
                self.weights[component] * score
                for component, score in score_components.items()
            )
            
            scored_item = item.copy()
            scored_item['score'] = final_score
            scored_item['score_components'] = score_components
            scored_items.append(scored_item)
        
        return scored_items
    
    async def _score_episodic_items(
        self, 
        items: List[Dict[str, Any]], 
        purpose: str, 
        thread_id: str,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """Score episodic items using adapted algorithm."""
        scored_items = []
        
        for item in items:
            score_components = {}
            
            # Task Relevance (adapted for episodic)
            score_components['task_relevance'] = self._calculate_episodic_relevance(
                item, purpose
            )
            
            # Decision Impact (based on kind and salience)
            score_components['decision_impact'] = item.get('salience', 0.5)
            
            # Recency (same as semantic)
            score_components['recency'] = self._calculate_recency(item)
            
            # Graph Degree (neighbors count)
            neighbors = item.get('neighbors', [])
            score_components['graph_degree'] = min(1.0, len(neighbors) / 10.0)
            
            # Failure Impact (higher for error-related items)
            score_components['failure_impact'] = self._calculate_episodic_failure_impact(item)
            
            # Usage Frequency
            stats = await self._get_item_usage_stats(item['id'], db)
            score_components['usage_frequency'] = self._calculate_usage_frequency(stats)
            
            # Redundancy Penalty (based on similar snippets)
            score_components['redundancy_penalty'] = self._calculate_episodic_redundancy(
                item, items
            )
            
            # Calculate final weighted score
            final_score = sum(
                self.weights[component] * score
                for component, score in score_components.items()
            )
            
            scored_item = item.copy()
            scored_item['score'] = final_score
            scored_item['score_components'] = score_components
            scored_items.append(scored_item)
        
        return scored_items
    
    def _calculate_task_relevance(self, item: Dict[str, Any], purpose: str) -> float:
        """Calculate task relevance score (0.0 to 1.0)."""
        # Simple keyword matching for now
        # In production, this would use embeddings/semantic similarity
        
        purpose_lower = purpose.lower()
        title_lower = item.get('title', '').lower()
        body_lower = item.get('body', '').lower()
        
        # Check for direct keyword matches
        purpose_words = set(purpose_lower.split())
        content_words = set(title_lower.split() + body_lower.split())
        
        if not purpose_words:
            return 0.5  # Default relevance
        
        # Calculate word overlap
        overlap = len(purpose_words & content_words)
        relevance = min(1.0, overlap / len(purpose_words))
        
        # Boost for exact phrase matches
        if purpose_lower in title_lower or purpose_lower in body_lower:
            relevance = min(1.0, relevance + 0.3)
        
        # Boost based on item kind relevance to purpose
        kind = item.get('kind', '')
        if 'task' in purpose_lower and kind == 'task':
            relevance = min(1.0, relevance + 0.2)
        elif 'decision' in purpose_lower and kind == 'decision':
            relevance = min(1.0, relevance + 0.2)
        elif 'requirement' in purpose_lower and kind == 'requirement':
            relevance = min(1.0, relevance + 0.2)
        
        return relevance
    
    def _calculate_decision_impact(self, item: Dict[str, Any]) -> float:
        """Calculate decision impact score."""
        kind = item.get('kind', '')
        status = item.get('status', 'provisional')
        
        # Base scores by kind
        kind_scores = {
            'decision': 1.0,
            'requirement': 0.8,
            'constraint': 0.7,
            'task': 0.5,
        }
        
        base_score = kind_scores.get(kind, 0.3)
        
        # Adjust by status
        status_multipliers = {
            'accepted': 1.0,
            'provisional': 0.7,
            'rejected': 0.2,
        }
        
        multiplier = status_multipliers.get(status, 0.7)
        
        return base_score * multiplier
    
    def _calculate_recency(self, item: Dict[str, Any]) -> float:
        """Calculate recency score with exponential decay."""
        created_at = item.get('created_at')
        if not created_at:
            return 0.5
        
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        
        now = datetime.utcnow().replace(tzinfo=created_at.tzinfo)
        age_hours = (now - created_at).total_seconds() / 3600
        
        # Exponential decay with half-life of 7 days (168 hours)
        half_life = 168
        decay_factor = math.exp(-math.log(2) * age_hours / half_life)
        
        return min(1.0, decay_factor)
    
    def _calculate_graph_degrees(self, items: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate graph degree scores for all items."""
        # Count incoming references
        reference_counts = {}
        item_ids = {item['id'] for item in items}
        
        for item in items:
            item_id = item['id']
            if item_id not in reference_counts:
                reference_counts[item_id] = 0
            
            # Count references to this item from other items
            for other_item in items:
                if other_item['id'] == item_id:
                    continue
                
                refs = other_item.get('links', {}).get('references', [])
                if item_id in refs:
                    reference_counts[item_id] += 1
        
        # Normalize to 0-1 scale
        max_refs = max(reference_counts.values()) if reference_counts else 1
        
        return {
            item_id: min(1.0, count / max_refs)
            for item_id, count in reference_counts.items()
        }
    
    def _calculate_failure_impact(self, item: Dict[str, Any]) -> float:
        """Calculate failure impact score."""
        title = item.get('title', '').lower()
        body = item.get('body', '').lower()
        kind = item.get('kind', '')
        
        # High impact keywords
        failure_keywords = [
            'error', 'failed', 'failure', 'broken', 'bug', 'issue',
            'critical', 'blocker', 'urgent', 'crash', 'exception'
        ]
        
        content = f"{title} {body}"
        failure_score = sum(1 for keyword in failure_keywords if keyword in content)
        
        # Normalize and boost for certain kinds
        base_score = min(1.0, failure_score / 3.0)
        
        if kind in ['constraint', 'requirement']:
            base_score = min(1.0, base_score + 0.2)
        
        return base_score
    
    def _calculate_usage_frequency(self, stats: Dict[str, Any]) -> float:
        """Calculate usage frequency score."""
        if not stats:
            return 0.0
        
        # Combine different usage metrics
        clicks = stats.get('clicks', 0)
        references = stats.get('references', 0)
        expansions = stats.get('expansions', 0)
        
        total_usage = clicks + references + expansions
        
        # Logarithmic scaling to prevent dominance
        if total_usage == 0:
            return 0.0
        
        return min(1.0, math.log(total_usage + 1) / math.log(100))
    
    def _calculate_redundancy_penalty(
        self, 
        item: Dict[str, Any], 
        all_items: List[Dict[str, Any]]
    ) -> float:
        """Calculate redundancy penalty."""
        # Simple implementation: penalize items with very similar titles
        item_title = item.get('title', '').lower()
        similar_count = 0
        
        for other_item in all_items:
            if other_item['id'] == item['id']:
                continue
            
            other_title = other_item.get('title', '').lower()
            
            # Simple similarity check
            if len(item_title) > 10 and len(other_title) > 10:
                common_words = set(item_title.split()) & set(other_title.split())
                if len(common_words) >= 3:  # At least 3 common words
                    similar_count += 1
        
        # Penalty increases with number of similar items
        return min(1.0, similar_count / 5.0)
    
    def _calculate_episodic_relevance(self, item: Dict[str, Any], purpose: str) -> float:
        """Calculate relevance for episodic items."""
        purpose_lower = purpose.lower()
        title_lower = item.get('title', '').lower()
        snippet_lower = item.get('snippet', '').lower()
        
        # Check for keyword matches
        purpose_words = set(purpose_lower.split())
        content_words = set(title_lower.split() + snippet_lower.split())
        
        if not purpose_words:
            return 0.3  # Lower default for episodic
        
        overlap = len(purpose_words & content_words)
        relevance = min(1.0, overlap / len(purpose_words))
        
        # Boost for error-related queries
        if any(word in purpose_lower for word in ['error', 'fail', 'bug', 'issue']):
            if item.get('kind') in ['test_fail', 'stack', 'log']:
                relevance = min(1.0, relevance + 0.3)
        
        return relevance
    
    def _calculate_episodic_failure_impact(self, item: Dict[str, Any]) -> float:
        """Calculate failure impact for episodic items."""
        kind = item.get('kind', '')
        
        # Higher scores for error-related kinds
        kind_scores = {
            'test_fail': 1.0,
            'stack': 0.9,
            'log': 0.3,
            'diff': 0.4,
        }
        
        return kind_scores.get(kind, 0.2)
    
    def _calculate_episodic_redundancy(
        self, 
        item: Dict[str, Any], 
        all_items: List[Dict[str, Any]]
    ) -> float:
        """Calculate redundancy penalty for episodic items."""
        item_snippet = item.get('snippet', '').lower()[:100]  # First 100 chars
        similar_count = 0
        
        for other_item in all_items:
            if other_item['id'] == item['id']:
                continue
            
            other_snippet = other_item.get('snippet', '').lower()[:100]
            
            # Check for similar snippets
            if len(item_snippet) > 20 and len(other_snippet) > 20:
                # Simple similarity check
                common_chars = sum(1 for a, b in zip(item_snippet, other_snippet) if a == b)
                similarity = common_chars / max(len(item_snippet), len(other_snippet))
                
                if similarity > 0.7:
                    similar_count += 1
        
        return min(1.0, similar_count / 3.0)
    
    async def _get_item_usage_stats(self, item_id: str, db: AsyncSession) -> Dict[str, Any]:
        """Get usage statistics for a single item."""
        if not item_id:
            return {}
        
        result = await db.execute(
            select(UsageStats).where(UsageStats.item_id == item_id)
        )
        stats = result.scalar_one_or_none()
        
        if not stats:
            return {}
            
        return {
            'clicks': stats.clicks,
            'references': stats.references,
            'expansions': 0, # This needs to be implemented
            'last_accessed': stats.last_used_at,
        }
    
    def _select_items_by_budget(
        self, 
        scored_items: List[Dict[str, Any]], 
        token_budget: int
    ) -> List[Dict[str, Any]]:
        """Select top-scoring items within token budget."""
        # Sort by score descending
        sorted_items = sorted(scored_items, key=lambda x: x['score'], reverse=True)
        
        selected_items = []
        estimated_tokens = 0
        
        for item in sorted_items:
            # Estimate tokens for this item
            item_tokens = self._estimate_item_tokens(item)
            
            if estimated_tokens + item_tokens <= token_budget:
                selected_items.append(item)
                estimated_tokens += item_tokens
            else:
                # Try to fit smaller items
                if item_tokens < token_budget * 0.1:  # Less than 10% of budget
                    selected_items.append(item)
                    estimated_tokens += item_tokens
        
        return selected_items
    
    def _estimate_item_tokens(self, item: Dict[str, Any]) -> int:
        """Estimate token count for an item."""
        # Rough estimation: 1 token per 4 characters
        title = item.get('title', '')
        body = item.get('body', '')
        snippet = item.get('snippet', '')
        
        content = f"{title} {body} {snippet}"
        return max(10, len(content) // 4)
    
    def _extract_globals(self, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract global information from selected items."""
        # Find mission/goal items
        mission_items = [
            item for item in items 
            if item.get('kind') == 'requirement' and 
            any(word in item.get('title', '').lower() for word in ['mission', 'goal', 'objective'])
        ]
        
        mission = mission_items[0].get('body', 'No mission defined') if mission_items else 'No mission defined'
        
        # Extract constraints
        constraint_items = [
            item for item in items 
            if item.get('kind') == 'constraint'
        ]
        constraints = [item.get('title', '') for item in constraint_items[:5]]
        
        # Build runbook from tasks and decisions
        task_items = [item for item in items if item.get('kind') == 'task']
        decision_items = [item for item in items if item.get('kind') == 'decision']
        
        runbook = {
            'tasks': [{'title': item.get('title', ''), 'status': item.get('status', 'provisional')} 
                     for item in task_items[:10]],
            'decisions': [{'title': item.get('title', ''), 'status': item.get('status', 'provisional')} 
                         for item in decision_items[:10]],
        }
        
        return {
            'mission': mission,
            'constraints': constraints,
            'runbook': runbook,
        }
    
    def _extract_artifact_refs(self, items: List[Dict[str, Any]]) -> List[str]:
        """Extract artifact references from selected items."""
        artifact_refs = []
        
        for item in items:
            # Look for code references in links
            links = item.get('links', {})
            refs = links.get('references', [])
            
            for ref in refs:
                if ref.startswith('CODE:'):
                    artifact_refs.append(ref)
        
        # Deduplicate
        return list(set(artifact_refs))
    
    def _estimate_tokens(
        self, 
        items: List[Dict[str, Any]], 
        globals_data: Dict[str, Any], 
        artifact_refs: List[str]
    ) -> int:
        """Estimate total token usage."""
        # Items tokens
        items_tokens = sum(self._estimate_item_tokens(item) for item in items)
        
        # Globals tokens
        globals_text = f"{globals_data.get('mission', '')} {' '.join(globals_data.get('constraints', []))}"
        globals_tokens = len(globals_text) // 4
        
        # Artifacts tokens (estimated)
        artifacts_tokens = len(artifact_refs) * 50  # Rough estimate per artifact
        
        return items_tokens + globals_tokens + artifacts_tokens

