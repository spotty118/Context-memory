"""
Working set service for creating compact, structured context from retrieval data.
"""
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class WorkingSetBuilder:
    """Builds compact working sets from retrieval data."""
    
    def __init__(self):
        self.max_focus_items = 10
        self.max_artifacts = 15
        self.max_citations = 20
    
    def create_working_set(
        self,
        retrieval_data: Dict[str, Any],
        token_budget: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Create a compact working set from retrieval data.
        
        Args:
            retrieval_data: Data from context recall
            token_budget: Optional token budget for working set
            
        Returns:
            Dict with structured working set data
        """
        logger.info("working_set_creation_started",
                   focus_items_count=len(retrieval_data.get('focus_ids', [])),
                   artifacts_count=len(retrieval_data.get('artifact_refs', [])),
                   token_budget=token_budget)
        
        # Extract and structure the data
        globals_data = retrieval_data.get('globals', {})
        focus_ids = retrieval_data.get('focus_ids', [])
        artifact_refs = retrieval_data.get('artifact_refs', [])
        
        # Build structured components
        mission = self._extract_mission(globals_data)
        constraints = self._extract_constraints(globals_data)
        focus_decisions = self._extract_focus_decisions(focus_ids, globals_data)
        focus_tasks = self._extract_focus_tasks(focus_ids, globals_data)
        runbook = self._build_runbook(globals_data, focus_decisions, focus_tasks)
        artifacts = self._process_artifacts(artifact_refs)
        citations = self._build_citations(focus_ids)
        open_questions = self._identify_open_questions(focus_decisions, focus_tasks)
        
        # Estimate token usage
        working_set = {
            'mission': mission,
            'constraints': constraints,
            'focus_decisions': focus_decisions,
            'focus_tasks': focus_tasks,
            'runbook': runbook,
            'artifacts': artifacts,
            'citations': citations,
            'open_questions': open_questions,
        }
        
        token_estimate = self._estimate_working_set_tokens(working_set)
        working_set['token_estimate'] = token_estimate
        
        # Apply token budget if specified
        if token_budget and token_estimate > token_budget:
            working_set = self._apply_token_budget(working_set, token_budget)
            working_set['token_estimate'] = self._estimate_working_set_tokens(working_set)
        
        logger.info("working_set_creation_completed",
                   mission_length=len(mission),
                   constraints_count=len(constraints),
                   focus_decisions_count=len(focus_decisions),
                   focus_tasks_count=len(focus_tasks),
                   artifacts_count=len(artifacts),
                   token_estimate=working_set['token_estimate'])
        
        return working_set
    
    def _extract_mission(self, globals_data: Dict[str, Any]) -> str:
        """Extract and format mission statement."""
        mission = globals_data.get('mission', 'No mission defined')
        
        # Clean up and format mission
        if isinstance(mission, str):
            mission = mission.strip()
            if not mission or mission == 'No mission defined':
                return "Mission: Define project objectives and goals"
            
            # Ensure it starts with "Mission:" if not already
            if not mission.lower().startswith('mission'):
                mission = f"Mission: {mission}"
        
        return mission
    
    def _extract_constraints(self, globals_data: Dict[str, Any]) -> List[str]:
        """Extract and format constraints."""
        constraints = globals_data.get('constraints', [])
        
        if not constraints:
            return ["No specific constraints identified"]
        
        # Clean and format constraints
        formatted_constraints = []
        for constraint in constraints[:5]:  # Limit to top 5
            if isinstance(constraint, str) and constraint.strip():
                formatted_constraints.append(constraint.strip())
        
        return formatted_constraints or ["No specific constraints identified"]
    
    def _extract_focus_decisions(
        self, 
        focus_ids: List[str], 
        globals_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract focus decisions from runbook data."""
        runbook = globals_data.get('runbook', {})
        decisions = runbook.get('decisions', [])
        
        focus_decisions = []
        
        # Generate real decision IDs using hash of content
        import hashlib
        
        for decision in decisions[:self.max_focus_items]:
            if isinstance(decision, dict):
                # Generate stable ID based on decision content
                decision_content = f"{decision.get('title', '')}{decision.get('description', '')}"
                decision_id = hashlib.md5(decision_content.encode()).hexdigest()[:8]
                
                focus_decisions.append({
                    'id': f"D_{decision_id}",
                    'title': decision.get('title', 'Untitled Decision'),
                    'status': decision.get('status', 'provisional'),
                    'impact': self._assess_decision_impact(decision),
                    'description': decision.get('description', ''),
                    'rationale': decision.get('rationale', ''),
                    'alternatives': decision.get('alternatives', []),
                })
        
        # Extract decisions from other content if runbook is empty
        if not focus_decisions:
            # Try to extract decisions from semantic items
            semantic_items = globals_data.get('semantic_items', [])
            for item in semantic_items[:3]:  # Limit to top 3
                if any(keyword in item.get('content', '').lower() 
                       for keyword in ['decide', 'decision', 'choose', 'option', 'alternative']):
                    item_id = item.get('id', hashlib.md5(str(item).encode()).hexdigest()[:8])
                    focus_decisions.append({
                        'id': f"D_{item_id}",
                        'title': f"Decision from: {item.get('title', 'Context Item')[:50]}",
                        'status': 'extracted',
                        'impact': 'medium',
                        'description': item.get('content', '')[:200] + '...',
                        'source': 'extracted_from_context'
                    })
            
            # Fallback if still no decisions
            if not focus_decisions:
                focus_decisions.append({
                    'id': 'D_default',
                    'title': 'Analyze context for key decisions',
                    'status': 'pending',
                    'impact': 'medium',
                    'description': 'Review the provided context to identify and document key decisions that need to be made.',
                    'source': 'generated'
                })
        
        return focus_decisions
    
    def _extract_focus_tasks(
        self, 
        focus_ids: List[str], 
        globals_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract focus tasks from runbook data."""
        runbook = globals_data.get('runbook', {})
        tasks = runbook.get('tasks', [])
        
        focus_tasks = []
        
        # Generate real task IDs using hash of content
        import hashlib
        
        for task in tasks[:self.max_focus_items]:
            if isinstance(task, dict):
                # Generate stable ID based on task content
                task_content = f"{task.get('title', '')}{task.get('description', '')}"
                task_id = hashlib.md5(task_content.encode()).hexdigest()[:8]
                
                focus_tasks.append({
                    'id': f"T_{task_id}",
                    'title': task.get('title', 'Untitled Task'),
                    'status': task.get('status', 'pending'),
                    'priority': self._assess_task_priority(task),
                    'description': task.get('description', ''),
                    'assignee': task.get('assignee', ''),
                    'due_date': task.get('due_date', ''),
                    'dependencies': task.get('dependencies', []),
                })
        
        # Extract tasks from other content if runbook is empty
        if not focus_tasks:
            # Try to extract tasks from semantic items
            semantic_items = globals_data.get('semantic_items', [])
            for item in semantic_items[:3]:  # Limit to top 3
                if any(keyword in item.get('content', '').lower() 
                       for keyword in ['todo', 'task', 'action', 'implement', 'create', 'fix', 'build']):
                    item_id = item.get('id', hashlib.md5(str(item).encode()).hexdigest()[:8])
                    
                    # Extract action verbs to create task titles
                    content = item.get('content', '')
                    title = f"Task from: {item.get('title', 'Context Item')[:50]}"
                    
                    focus_tasks.append({
                        'id': f"T_{item_id}",
                        'title': title,
                        'status': 'extracted',
                        'priority': 'medium',
                        'description': content[:200] + '...',
                        'source': 'extracted_from_context'
                    })
            
            # Fallback if still no tasks
            if not focus_tasks:
                focus_tasks.append({
                    'id': 'T_default',
                    'title': 'Review context and identify action items',
                    'status': 'pending',
                    'priority': 'medium',
                    'description': 'Analyze the provided context to identify specific action items and tasks that need to be completed.',
                    'source': 'generated'
                })
        
        return focus_tasks
    
    def _build_runbook(
        self,
        globals_data: Dict[str, Any],
        focus_decisions: List[Dict[str, Any]],
        focus_tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Build structured runbook from decisions and tasks."""
        # Organize by status and priority
        accepted_decisions = [d for d in focus_decisions if d['status'] == 'accepted']
        provisional_decisions = [d for d in focus_decisions if d['status'] == 'provisional']
        
        high_priority_tasks = [t for t in focus_tasks if t.get('priority') == 'high']
        medium_priority_tasks = [t for t in focus_tasks if t.get('priority') == 'medium']
        
        # Create structured steps
        steps = []
        
        # Add accepted decisions as foundation
        if accepted_decisions:
            steps.append("Foundation Decisions:")
            for decision in accepted_decisions[:3]:
                steps.append(f"  • {decision['title']}")
        
        # Add high priority tasks
        if high_priority_tasks:
            steps.append("High Priority Tasks:")
            for task in high_priority_tasks[:5]:
                steps.append(f"  • {task['title']}")
        
        # Add provisional decisions that need resolution
        if provisional_decisions:
            steps.append("Pending Decisions:")
            for decision in provisional_decisions[:3]:
                steps.append(f"  • {decision['title']} (needs resolution)")
        
        # Add medium priority tasks
        if medium_priority_tasks:
            steps.append("Additional Tasks:")
            for task in medium_priority_tasks[:3]:
                steps.append(f"  • {task['title']}")
        
        if not steps:
            steps = ["No structured runbook available - define tasks and decisions"]
        
        return {
            'steps': steps,
            'summary': f"Runbook with {len(focus_decisions)} decisions and {len(focus_tasks)} tasks",
        }
    
    def _process_artifacts(self, artifact_refs: List[str]) -> List[str]:
        """Process and format artifact references."""
        if not artifact_refs:
            return ["No code artifacts referenced"]
        
        # Clean and format artifact references
        processed_artifacts = []
        for ref in artifact_refs[:self.max_artifacts]:
            if isinstance(ref, str) and ref.startswith('CODE:'):
                # Format the reference for readability
                clean_ref = ref[5:]  # Remove 'CODE:' prefix
                processed_artifacts.append(clean_ref)
        
        return processed_artifacts or ["No code artifacts referenced"]
    
    def _build_citations(self, focus_ids: List[str]) -> List[str]:
        """Build citation list from focus item IDs."""
        if not focus_ids:
            return ["No citations available"]
        
        # Format citations
        citations = []
        for item_id in focus_ids[:self.max_citations]:
            if isinstance(item_id, str):
                citations.append(item_id)
        
        return citations or ["No citations available"]
    
    def _identify_open_questions(
        self,
        focus_decisions: List[Dict[str, Any]],
        focus_tasks: List[Dict[str, Any]]
    ) -> List[str]:
        """Identify open questions from decisions and tasks."""
        open_questions = []
        
        # Questions from provisional decisions
        provisional_decisions = [d for d in focus_decisions if d['status'] == 'provisional']
        for decision in provisional_decisions[:3]:
            title = decision['title']
            if not title.endswith('?'):
                title += '?'
            open_questions.append(f"Should we proceed with: {title}")
        
        # Questions from high-priority tasks without clear status
        high_priority_tasks = [t for t in focus_tasks if t.get('priority') == 'high']
        for task in high_priority_tasks[:2]:
            open_questions.append(f"How should we implement: {task['title']}?")
        
        # Add generic questions if none found
        if not open_questions:
            open_questions = [
                "What are the next immediate priorities?",
                "Are there any blockers or dependencies?",
                "What resources or information are needed?",
            ]
        
        return open_questions[:5]  # Limit to 5 questions
    
    def _assess_decision_impact(self, decision: Dict[str, Any]) -> str:
        """Assess the impact level of a decision."""
        title = decision.get('title', '').lower()
        
        # High impact keywords
        high_impact_keywords = [
            'architecture', 'framework', 'database', 'security', 'api',
            'critical', 'major', 'breaking', 'infrastructure'
        ]
        
        # Medium impact keywords
        medium_impact_keywords = [
            'feature', 'component', 'module', 'service', 'endpoint',
            'design', 'implementation', 'approach'
        ]
        
        if any(keyword in title for keyword in high_impact_keywords):
            return 'high'
        elif any(keyword in title for keyword in medium_impact_keywords):
            return 'medium'
        else:
            return 'low'
    
    def _assess_task_priority(self, task: Dict[str, Any]) -> str:
        """Assess the priority level of a task."""
        title = task.get('title', '').lower()
        status = task.get('status', 'provisional')
        
        # High priority keywords
        high_priority_keywords = [
            'urgent', 'critical', 'blocker', 'fix', 'bug', 'error',
            'security', 'deploy', 'release', 'launch'
        ]
        
        # Low priority keywords
        low_priority_keywords = [
            'cleanup', 'refactor', 'optimize', 'documentation', 'comment',
            'minor', 'nice to have', 'future', 'enhancement'
        ]
        
        if any(keyword in title for keyword in high_priority_keywords):
            return 'high'
        elif any(keyword in title for keyword in low_priority_keywords):
            return 'low'
        elif status == 'accepted':
            return 'high'
        else:
            return 'medium'
    
    def _estimate_working_set_tokens(self, working_set: Dict[str, Any]) -> int:
        """Estimate token count for the working set."""
        # Rough estimation: 1 token per 4 characters
        total_chars = 0
        
        # Mission
        mission = working_set.get('mission', '')
        total_chars += len(mission)
        
        # Constraints
        constraints = working_set.get('constraints', [])
        total_chars += sum(len(str(c)) for c in constraints)
        
        # Focus items
        focus_decisions = working_set.get('focus_decisions', [])
        focus_tasks = working_set.get('focus_tasks', [])
        
        for item in focus_decisions + focus_tasks:
            total_chars += len(str(item.get('title', '')))
        
        # Runbook
        runbook = working_set.get('runbook', {})
        steps = runbook.get('steps', [])
        total_chars += sum(len(str(step)) for step in steps)
        
        # Artifacts
        artifacts = working_set.get('artifacts', [])
        total_chars += sum(len(str(artifact)) for artifact in artifacts)
        
        # Citations (minimal impact)
        citations = working_set.get('citations', [])
        total_chars += len(citations) * 5  # Rough estimate for IDs
        
        # Open questions
        open_questions = working_set.get('open_questions', [])
        total_chars += sum(len(str(q)) for q in open_questions)
        
        return max(100, total_chars // 4)  # Minimum 100 tokens
    
    def _apply_token_budget(
        self, 
        working_set: Dict[str, Any], 
        token_budget: int
    ) -> Dict[str, Any]:
        """Apply token budget by trimming less important content."""
        # Priority order for trimming
        trim_order = [
            ('open_questions', 0.7),  # Keep 70% of open questions
            ('artifacts', 0.8),       # Keep 80% of artifacts
            ('focus_tasks', 0.8),     # Keep 80% of tasks
            ('constraints', 0.9),     # Keep 90% of constraints
            ('focus_decisions', 0.9), # Keep 90% of decisions
        ]
        
        current_tokens = working_set.get('token_estimate', 0)
        
        for field, keep_ratio in trim_order:
            if current_tokens <= token_budget:
                break
            
            if field in working_set and isinstance(working_set[field], list):
                original_count = len(working_set[field])
                keep_count = max(1, int(original_count * keep_ratio))
                
                working_set[field] = working_set[field][:keep_count]
                
                # Recalculate tokens
                current_tokens = self._estimate_working_set_tokens(working_set)
        
        # If still over budget, trim runbook steps
        if current_tokens > token_budget:
            runbook = working_set.get('runbook', {})
            steps = runbook.get('steps', [])
            if len(steps) > 5:
                runbook['steps'] = steps[:5]
                working_set['runbook'] = runbook
        
        return working_set

