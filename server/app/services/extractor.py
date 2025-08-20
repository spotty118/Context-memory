"""
Context extraction service for processing raw materials into semantic and episodic items.
"""
import re
import hashlib
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class ContextExtractor:
    """Extracts semantic and episodic items from raw context materials."""
    
    def __init__(self):
        self.semantic_patterns = {
            'decision': [
                r'(?i)(?:decided|decision|choose|chose|selected)\s+(?:to|that)',
                r'(?i)(?:we will|we should|let\'s|going to)\s+',
                r'(?i)(?:conclusion|final decision|verdict)',
            ],
            'requirement': [
                r'(?i)(?:must|should|need to|required|requirement)',
                r'(?i)(?:spec|specification|criteria)',
                r'(?i)(?:user story|acceptance criteria)',
            ],
            'constraint': [
                r'(?i)(?:constraint|limitation|restriction)',
                r'(?i)(?:cannot|can\'t|won\'t|shouldn\'t)',
                r'(?i)(?:blocked by|depends on|requires)',
            ],
            'task': [
                r'(?i)(?:todo|task|action item|next step)',
                r'(?i)(?:implement|create|build|develop)',
                r'(?i)(?:fix|resolve|address|handle)',
            ],
        }
        
        self.episodic_patterns = {
            'test_fail': [
                r'(?i)(?:test failed|assertion error|test error)',
                r'(?i)(?:expected.*got|assert.*failed)',
                r'(?i)(?:failure|failed.*test)',
            ],
            'stack': [
                r'(?i)(?:traceback|stack trace|exception)',
                r'(?i)(?:error.*line|at.*line)',
                r'(?i)(?:raised.*exception|threw.*error)',
            ],
            'log': [
                r'(?i)(?:error|warning|info|debug)',
                r'(?i)(?:logged|log entry|timestamp)',
                r'\d{4}-\d{2}-\d{2}.*\d{2}:\d{2}:\d{2}',
            ],
            'diff': [
                r'(?:^\+|\-)',
                r'(?i)(?:added|removed|changed|modified)',
                r'(?:@@.*@@|diff --git)',
            ],
        }
    
    def redact_sensitive_data(self, content: str) -> str:
        """Redact sensitive information from content."""
        # API keys and tokens
        content = re.sub(r'(?i)(?:api[_-]?key|token|secret)["\s]*[:=]["\s]*[a-zA-Z0-9_-]{20,}', 
                        '[REDACTED_API_KEY]', content)
        
        # Passwords
        content = re.sub(r'(?i)password["\s]*[:=]["\s]*[^\s"\']+', 
                        'password=[REDACTED]', content)
        
        # Email addresses
        content = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', 
                        '[REDACTED_EMAIL]', content)
        
        # IP addresses
        content = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', 
                        '[REDACTED_IP]', content)
        
        # URLs with credentials
        content = re.sub(r'(?i)(?:https?://)([^:]+):([^@]+)@', 
                        r'\1:[REDACTED]@', content)
        
        return content
    
    def extract_semantic_items(self, content: str, thread_id: str) -> List[Dict[str, Any]]:
        """Extract semantic items (decisions, requirements, etc.) from content."""
        items = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 10:  # Skip short lines
                continue
            
            # Determine item kind based on patterns
            item_kind = None
            for kind, patterns in self.semantic_patterns.items():
                if any(re.search(pattern, line) for pattern in patterns):
                    item_kind = kind
                    break
            
            if item_kind:
                # Extract title (first sentence or up to 100 chars)
                title = line.split('.')[0][:100].strip()
                if not title.endswith('.'):
                    title += '...'
                
                # Extract body (current line + context)
                context_lines = []
                start_idx = max(0, i - 2)
                end_idx = min(len(lines), i + 3)
                
                for j in range(start_idx, end_idx):
                    if j < len(lines):
                        context_lines.append(lines[j].strip())
                
                body = '\n'.join(filter(None, context_lines))
                
                # Generate unique ID
                content_hash = hashlib.md5(f"{thread_id}:{title}:{body}".encode()).hexdigest()[:8]
                item_id = f"S{len(items) + 1}_{content_hash}"
                
                items.append({
                    'id': item_id,
                    'thread_id': thread_id,
                    'kind': item_kind,
                    'title': title,
                    'body': body,
                    'tags': self._extract_tags(line),
                    'links': self._extract_links(body),
                    'status': 'provisional',
                    'salience': self._calculate_initial_salience(item_kind, body),
                })
        
        logger.info("semantic_items_extracted", 
                   thread_id=thread_id, 
                   count=len(items),
                   kinds=[item['kind'] for item in items])
        
        return items
    
    def extract_episodic_items(self, content: str, thread_id: str, source: str = None) -> List[Dict[str, Any]]:
        """Extract episodic items (events, logs, etc.) from content."""
        items = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) < 15:  # Skip short lines
                continue
            
            # Determine item kind based on patterns
            item_kind = None
            for kind, patterns in self.episodic_patterns.items():
                if any(re.search(pattern, line) for pattern in patterns):
                    item_kind = kind
                    break
            
            if item_kind:
                # Extract title (first part of line)
                title = line[:80].strip()
                if len(line) > 80:
                    title += '...'
                
                # Extract snippet (current line + limited context)
                snippet_lines = [line]
                if i + 1 < len(lines) and len(lines[i + 1].strip()) > 0:
                    snippet_lines.append(lines[i + 1].strip())
                
                snippet = '\n'.join(snippet_lines)[:500]  # Limit snippet size
                
                # Generate content hash for deduplication
                content_hash = hashlib.md5(snippet.encode()).hexdigest()
                
                # Generate unique ID
                item_id = f"E{len(items) + 1}_{content_hash[:8]}"
                
                items.append({
                    'id': item_id,
                    'thread_id': thread_id,
                    'kind': item_kind,
                    'title': title,
                    'snippet': snippet,
                    'source': source,
                    'hash': content_hash,
                    'salience': self._calculate_initial_salience(item_kind, snippet),
                })
        
        logger.info("episodic_items_extracted", 
                   thread_id=thread_id, 
                   count=len(items),
                   kinds=[item['kind'] for item in items])
        
        return items
    
    def extract_artifacts(self, content: str, thread_id: str) -> List[Dict[str, Any]]:
        """Extract code artifacts and file references from content."""
        artifacts = []
        
        # Pattern for code blocks or file references
        code_patterns = [
            r'```(\w+)?\n(.*?)\n```',  # Markdown code blocks
            r'`([^`]+)`',  # Inline code
            r'(?:file|path|src):\s*([^\s]+)',  # File references
            r'([a-zA-Z_][a-zA-Z0-9_]*\.[a-zA-Z]+)(?:#L(\d+)(?:-L?(\d+))?)?',  # File with line numbers
        ]
        
        for pattern in code_patterns:
            matches = re.finditer(pattern, content, re.DOTALL | re.IGNORECASE)
            for match in matches:
                if pattern.startswith('```'):
                    # Code block
                    language = match.group(1) or 'text'
                    code_content = match.group(2).strip()
                    if len(code_content) > 20:  # Skip very short snippets
                        ref = f"CODE:snippet_{hashlib.md5(code_content.encode()).hexdigest()[:8]}"
                        artifacts.append({
                            'ref': ref,
                            'thread_id': thread_id,
                            'role': f'{language}_code',
                            'hash': hashlib.md5(code_content.encode()).hexdigest(),
                            'neighbors': [],
                        })
                elif pattern.startswith('`'):
                    # Inline code
                    code_content = match.group(1).strip()
                    if len(code_content) > 5 and '/' in code_content:  # Likely a path
                        ref = f"CODE:{code_content}"
                        artifacts.append({
                            'ref': ref,
                            'thread_id': thread_id,
                            'role': 'file_reference',
                            'hash': hashlib.md5(code_content.encode()).hexdigest(),
                            'neighbors': [],
                        })
                else:
                    # File reference with possible line numbers
                    if len(match.groups()) >= 3 and match.group(2):
                        # Has line numbers
                        filename = match.group(1)
                        start_line = match.group(2)
                        end_line = match.group(3) or start_line
                        ref = f"CODE:{filename}#L{start_line}-L{end_line}"
                    else:
                        # Just filename
                        filename = match.group(1) if match.group(1) else match.group(0)
                        ref = f"CODE:{filename}"
                    
                    artifacts.append({
                        'ref': ref,
                        'thread_id': thread_id,
                        'role': 'file_reference',
                        'hash': hashlib.md5(ref.encode()).hexdigest(),
                        'neighbors': [],
                    })
        
        # Deduplicate artifacts by ref
        unique_artifacts = {}
        for artifact in artifacts:
            unique_artifacts[artifact['ref']] = artifact
        
        result = list(unique_artifacts.values())
        
        logger.info("artifacts_extracted", 
                   thread_id=thread_id, 
                   count=len(result))
        
        return result
    
    def _extract_tags(self, content: str) -> List[str]:
        """Extract tags from content."""
        tags = []
        
        # Common technical tags
        tech_terms = [
            'api', 'database', 'frontend', 'backend', 'auth', 'security',
            'performance', 'bug', 'feature', 'test', 'deploy', 'config'
        ]
        
        content_lower = content.lower()
        for term in tech_terms:
            if term in content_lower:
                tags.append(term)
        
        return tags[:5]  # Limit to 5 tags
    
    def _extract_links(self, content: str) -> Dict[str, List[str]]:
        """Extract links to other items from content."""
        links = {'references': [], 'mentions': []}
        
        # Look for explicit references
        ref_patterns = [
            r'(?:see|ref|reference)\s+([SE]\d+)',
            r'(?:relates to|depends on|blocks)\s+([SE]\d+)',
            r'([SE]\d+)',  # Direct item references
        ]
        
        for pattern in ref_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                if match not in links['references']:
                    links['references'].append(match)
        
        return links
    
    def _calculate_initial_salience(self, kind: str, content: str) -> float:
        """Calculate initial salience score for an item."""
        base_scores = {
            'decision': 0.8,
            'requirement': 0.7,
            'constraint': 0.6,
            'task': 0.5,
            'test_fail': 0.9,
            'stack': 0.8,
            'log': 0.3,
            'diff': 0.4,
        }
        
        base_score = base_scores.get(kind, 0.5)
        
        # Adjust based on content characteristics
        content_lower = content.lower()
        
        # Boost for urgent/important keywords
        if any(word in content_lower for word in ['critical', 'urgent', 'important', 'blocker']):
            base_score += 0.2
        
        # Boost for error/failure keywords
        if any(word in content_lower for word in ['error', 'failed', 'broken', 'issue']):
            base_score += 0.1
        
        # Reduce for common/routine items
        if any(word in content_lower for word in ['routine', 'minor', 'cleanup', 'refactor']):
            base_score -= 0.1
        
        return min(1.0, max(0.1, base_score))  # Clamp between 0.1 and 1.0

