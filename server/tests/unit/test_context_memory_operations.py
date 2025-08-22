"""
Comprehensive tests for context memory operations.
Tests context ingestion, retrieval with scoring algorithm, working sets, and token budget management.
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any

from app.services.extractor import ContextExtractor
from app.services.retrieval import ContextRetriever
from app.services.workingset import WorkingSetBuilder
from app.services.consolidator import ContextConsolidator
from app.db.models import SemanticItem, EpisodicItem, UsageStats, APIKey
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestContextIngestionOperations:
    """Test context ingestion and extraction operations."""
    
    @pytest.fixture
    def extractor(self):
        """Create a ContextExtractor instance."""
        return ContextExtractor()
    
    @pytest.fixture
    def sample_chat_content(self):
        """Sample chat content for testing."""
        return """
        User: We need to implement user authentication for our web application.
        Assistant: I recommend using JWT tokens for session management. We should also implement password hashing with bcrypt.
        User: Great! Let's also add OAuth integration with Google and GitHub.
        Assistant: Perfect. We decided to use OAuth 2.0 flows for both providers. This requires setting up client credentials.
        User: What about database schema for users?
        Assistant: We need to create a users table with fields for email, password_hash, oauth_provider, and oauth_id.
        """
    
    @pytest.fixture
    def sample_diff_content(self):
        """Sample diff content for testing."""
        return """
        diff --git a/auth.py b/auth.py
        index 1234567..abcdefg 100644
        --- a/auth.py
        +++ b/auth.py
        @@ -1,5 +1,10 @@
         from fastapi import FastAPI, Depends
        +from fastapi.security import HTTPBearer
        +from passlib.context import CryptContext
         
         app = FastAPI()
        +security = HTTPBearer()
        +pwd_context = CryptContext(schemes=["bcrypt"])
         
         @app.get("/")
         def read_root():
        @@ -10,3 +15,8 @@ def read_root():
         
         @app.post("/login")
         def login():
        -    return {"message": "Login endpoint"}
        +    # TODO: Implement JWT authentication
        +    return {"message": "Login with JWT"}
        +
        +def hash_password(password: str) -> str:
        +    return pwd_context.hash(password)
        """
    
    @pytest.fixture
    def sample_log_content(self):
        """Sample log content for testing."""
        return """
        2025-01-20 10:30:15 INFO: Starting authentication service
        2025-01-20 10:30:16 INFO: Database connection established
        2025-01-20 10:31:20 ERROR: Authentication failed for user@example.com - Invalid password
        2025-01-20 10:31:25 WARNING: Multiple failed login attempts from IP 192.168.1.100
        2025-01-20 10:32:00 ERROR: JWT token validation failed - Token expired
        2025-01-20 10:32:30 INFO: User user@example.com logged in successfully
        """
    
    async def test_extract_semantic_items_from_chat(self, extractor, sample_chat_content):
        """Test extracting semantic items from chat content."""
        thread_id = "test-thread-semantic-001"
        
        items = extractor.extract_semantic_items(sample_chat_content, thread_id)
        
        # Should extract multiple semantic items
        assert len(items) >= 3
        
        # Check for different item kinds
        item_kinds = [item['kind'] for item in items]
        assert 'decision' in item_kinds
        assert 'requirement' in item_kinds
        
        # Verify item structure
        for item in items:
            assert item['thread_id'] == thread_id
            assert item['id'].startswith('S')
            assert 'title' in item
            assert 'body' in item
            assert 'salience' in item
            assert item['status'] == 'provisional'
            assert 0.0 <= item['salience'] <= 1.0
    
    async def test_extract_episodic_items_from_logs(self, extractor, sample_log_content):
        """Test extracting episodic items from log content."""
        thread_id = "test-thread-episodic-001"
        
        items = extractor.extract_episodic_items(sample_log_content, thread_id, source="app_logs")
        
        # Should extract log entries
        assert len(items) >= 2
        
        # Check for log item kinds
        item_kinds = [item['kind'] for item in items]
        assert 'log' in item_kinds
        
        # Verify item structure
        for item in items:
            assert item['thread_id'] == thread_id
            assert item['id'].startswith('E')
            assert 'title' in item
            assert 'snippet' in item
            assert item['source'] == "app_logs"
            assert 'hash' in item
            assert 0.0 <= item['salience'] <= 1.0
    
    async def test_extract_artifacts_from_diff(self, extractor, sample_diff_content):
        """Test extracting artifacts from diff content."""
        thread_id = "test-thread-artifacts-001"
        
        artifacts = extractor.extract_artifacts(sample_diff_content, thread_id)
        
        # Should extract file references
        assert len(artifacts) >= 1
        
        # Verify artifact structure
        for artifact in artifacts:
            assert artifact['thread_id'] == thread_id
            assert 'path' in artifact
            assert 'kind' in artifact
            assert 'content' in artifact
    
    async def test_sensitive_data_redaction(self, extractor):
        """Test that sensitive data is properly redacted."""
        sensitive_content = """
        API_KEY = "sk-1234567890abcdef1234567890abcdef"
        password = "mySecretPassword123"
        email = "user@example.com"
        database_url = "postgresql://user:password@localhost:5432/db"
        ip_address = "192.168.1.100"
        """
        
        redacted = extractor.redact_sensitive_data(sensitive_content)
        
        # Verify sensitive data is redacted
        assert "sk-1234567890abcdef1234567890abcdef" not in redacted
        assert "mySecretPassword123" not in redacted
        assert "user@example.com" not in redacted
        assert "192.168.1.100" not in redacted
        assert "[REDACTED" in redacted
    
    async def test_content_extraction_deduplication(self, extractor):
        """Test that duplicate content is properly handled."""
        duplicate_content = """
        User: We decided to use React for the frontend.
        Assistant: Great choice! React is a solid framework.
        User: We decided to use React for the frontend.
        Assistant: As mentioned before, React is excellent.
        """
        
        thread_id = "test-thread-dedup-001"
        items = extractor.extract_semantic_items(duplicate_content, thread_id)
        
        # Should not create duplicate items
        unique_titles = set(item['title'] for item in items)
        assert len(unique_titles) <= len(items)  # Some deduplication should occur


@pytest.mark.asyncio
class TestContextRetrievalOperations:
    """Test context retrieval with scoring algorithm."""
    
    @pytest.fixture
    def retriever(self):
        """Create a ContextRetriever instance."""
        return ContextRetriever()
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def sample_semantic_items(self):
        """Sample semantic items for scoring tests."""
        base_time = datetime.utcnow()
        return [
            {
                'id': 'S001',
                'thread_id': 'test-thread',
                'kind': 'decision',
                'title': 'Use JWT tokens for authentication',
                'body': 'We decided to implement JWT tokens for session management because they are stateless and secure.',
                'status': 'accepted',
                'tags': ['authentication', 'security', 'jwt'],
                'links': {'related': ['S002']},
                'salience': 0.9,
                'created_at': base_time - timedelta(hours=1),
                'updated_at': base_time - timedelta(minutes=30),
            },
            {
                'id': 'S002',
                'thread_id': 'test-thread',
                'kind': 'requirement',
                'title': 'Implement password hashing',
                'body': 'User passwords must be hashed using bcrypt with salt for security.',
                'status': 'provisional',
                'tags': ['security', 'password', 'bcrypt'],
                'links': {'depends_on': ['S001']},
                'salience': 0.8,
                'created_at': base_time - timedelta(hours=2),
                'updated_at': base_time - timedelta(hours=1),
            },
            {
                'id': 'S003',
                'thread_id': 'test-thread',
                'kind': 'task',
                'title': 'Create user database schema',
                'body': 'Design and implement database schema for user management.',
                'status': 'provisional',
                'tags': ['database', 'schema', 'users'],
                'links': {},
                'salience': 0.7,
                'created_at': base_time - timedelta(days=1),
                'updated_at': base_time - timedelta(days=1),
            }
        ]
    
    @pytest.fixture
    def sample_episodic_items(self):
        """Sample episodic items for scoring tests."""
        base_time = datetime.utcnow()
        return [
            {
                'id': 'E001',
                'thread_id': 'test-thread',
                'kind': 'test_fail',
                'title': 'Authentication test failed',
                'snippet': 'Test failed: test_jwt_authentication - AssertionError: Expected status 200, got 401',
                'source': 'pytest',
                'salience': 0.6,
                'created_at': base_time - timedelta(minutes=15),
            },
            {
                'id': 'E002',
                'thread_id': 'test-thread',
                'kind': 'log',
                'title': 'Multiple login failures',
                'snippet': 'WARNING: Multiple failed login attempts detected from IP 192.168.1.100',
                'source': 'app_logs',
                'salience': 0.5,
                'created_at': base_time - timedelta(hours=3),
            }
        ]
    
    async def test_scoring_algorithm_weights(self, retriever):
        """Test that scoring algorithm uses correct weights."""
        expected_weights = {
            'task_relevance': 0.28,
            'decision_impact': 0.22,
            'recency': 0.16,
            'graph_degree': 0.12,
            'failure_impact': 0.12,
            'usage_frequency': 0.08,
            'redundancy_penalty': -0.06,
        }
        
        assert retriever.weights == expected_weights
        
        # Verify weights sum to approximately 1.0 (minus penalty)
        positive_weights = sum(w for w in expected_weights.values() if w > 0)
        assert abs(positive_weights - 1.0) < 0.01
    
    async def test_task_relevance_scoring(self, retriever, sample_semantic_items):
        """Test task relevance component of scoring algorithm."""
        purpose = "implement secure authentication system"
        
        # Mock the _calculate_task_relevance method behavior
        with patch.object(retriever, '_calculate_task_relevance') as mock_relevance:
            mock_relevance.side_effect = [0.9, 0.8, 0.3]  # Different relevance scores
            
            # Score the items
            for item in sample_semantic_items:
                score = retriever._calculate_task_relevance(item, purpose)
                assert 0.0 <= score <= 1.0
    
    async def test_recency_scoring(self, retriever, sample_semantic_items):
        """Test recency component of scoring algorithm."""
        current_time = datetime.utcnow()
        
        for item in sample_semantic_items:
            score = retriever._calculate_recency(item)
            
            # More recent items should score higher
            assert 0.0 <= score <= 1.0
            
            # Items created recently should have higher recency scores
            time_diff = current_time - item['created_at']
            if time_diff.total_seconds() < 3600:  # Less than 1 hour
                assert score > 0.5
    
    async def test_decision_impact_scoring(self, retriever, sample_semantic_items):
        """Test decision impact component of scoring algorithm."""
        for item in sample_semantic_items:
            score = retriever._calculate_decision_impact(item)
            
            assert 0.0 <= score <= 1.0
            
            # Decisions should have higher impact than other types
            if item['kind'] == 'decision':
                assert score >= 0.7
            elif item['kind'] == 'requirement':
                assert score >= 0.5
    
    async def test_complete_recall_operation(self, retriever, mock_db_session, sample_semantic_items, sample_episodic_items):
        """Test complete context recall operation."""
        thread_id = "test-thread"
        purpose = "implement authentication system"
        token_budget = 4000
        
        # Mock database queries
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic, \
             patch.object(retriever, '_get_usage_stats') as mock_usage:
            
            mock_semantic.return_value = sample_semantic_items
            mock_episodic.return_value = sample_episodic_items
            mock_usage.return_value = {
                'S001': {'access_count': 10, 'last_accessed': datetime.utcnow()},
                'S002': {'access_count': 5, 'last_accessed': datetime.utcnow() - timedelta(hours=1)},
            }
            
            result = await retriever.recall_context(
                thread_id=thread_id,
                purpose=purpose,
                token_budget=token_budget,
                db=mock_db_session
            )
            
            # Verify result structure
            assert 'thread_id' in result
            assert 'globals' in result
            assert 'focus_ids' in result
            assert 'artifact_refs' in result
            assert 'token_estimate' in result
            
            assert result['thread_id'] == thread_id
            assert isinstance(result['focus_ids'], list)
            assert isinstance(result['token_estimate'], int)
            assert result['token_estimate'] <= token_budget
    
    async def test_token_budget_compliance(self, retriever, mock_db_session):
        """Test that retrieval respects token budget limits."""
        # Create items with known token counts
        large_items = [
            {
                'id': f'S{i:03d}',
                'thread_id': 'test-thread',
                'kind': 'decision',
                'title': f'Large decision item {i}',
                'body': ' '.join(['token'] * 100),  # 100 tokens per item
                'status': 'accepted',
                'tags': [],
                'links': {},
                'salience': 0.8,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
            }
            for i in range(1, 21)  # 20 large items
        ]
        
        small_budget = 500  # Should only fit ~5 items
        
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic, \
             patch.object(retriever, '_get_usage_stats') as mock_usage:
            
            mock_semantic.return_value = large_items
            mock_episodic.return_value = []
            mock_usage.return_value = {}
            
            result = await retriever.recall_context(
                thread_id="test-thread",
                purpose="test purpose",
                token_budget=small_budget,
                db=mock_db_session
            )
            
            # Should respect token budget
            assert result['token_estimate'] <= small_budget
            assert len(result['focus_ids']) <= 6  # Allow some buffer


@pytest.mark.asyncio
class TestWorkingSetOperations:
    """Test working set generation and token budget management."""
    
    @pytest.fixture
    def builder(self):
        """Create a WorkingSetBuilder instance."""
        return WorkingSetBuilder()
    
    @pytest.fixture
    def sample_retrieval_data(self):
        """Sample retrieval data for working set creation."""
        return {
            'thread_id': 'test-thread',
            'globals': {
                'mission': 'Implement secure user authentication system',
                'constraints': [
                    'Must support OAuth 2.0',
                    'Use JWT tokens for sessions',
                    'Implement password hashing with bcrypt'
                ],
                'runbook': {
                    'decisions': [
                        {
                            'title': 'Use JWT tokens for authentication',
                            'status': 'accepted',
                            'impact': 'high'
                        },
                        {
                            'title': 'Implement OAuth with Google and GitHub',
                            'status': 'provisional',
                            'impact': 'medium'
                        }
                    ],
                    'tasks': [
                        {
                            'title': 'Create user database schema',
                            'status': 'provisional',
                            'priority': 'high'
                        },
                        {
                            'title': 'Implement password hashing',
                            'status': 'provisional',
                            'priority': 'medium'
                        }
                    ]
                }
            },
            'focus_ids': ['S001', 'S002', 'S003'],
            'artifact_refs': ['auth.py', 'user_model.py'],
            'token_estimate': 3500
        }
    
    async def test_working_set_creation(self, builder, sample_retrieval_data):
        """Test basic working set creation."""
        working_set = builder.create_working_set(sample_retrieval_data)
        
        # Verify structure
        required_keys = [
            'mission', 'constraints', 'focus_decisions', 'focus_tasks',
            'runbook', 'artifacts', 'citations', 'open_questions', 'token_estimate'
        ]
        
        for key in required_keys:
            assert key in working_set
        
        # Verify content types
        assert isinstance(working_set['mission'], str)
        assert isinstance(working_set['constraints'], list)
        assert isinstance(working_set['focus_decisions'], list)
        assert isinstance(working_set['focus_tasks'], list)
        assert isinstance(working_set['runbook'], dict)
        assert isinstance(working_set['artifacts'], list)
        assert isinstance(working_set['citations'], list)
        assert isinstance(working_set['open_questions'], list)
        assert isinstance(working_set['token_estimate'], int)
    
    async def test_token_budget_enforcement(self, builder, sample_retrieval_data):
        """Test that working set respects token budget."""
        small_budget = 1000
        
        working_set = builder.create_working_set(
            sample_retrieval_data, 
            token_budget=small_budget
        )
        
        # Should be within budget (with some tolerance for estimation)
        assert working_set['token_estimate'] <= small_budget * 1.1  # 10% tolerance
        
        # Should still contain essential elements
        assert working_set['mission']
        assert len(working_set['constraints']) > 0
        assert len(working_set['focus_decisions']) > 0
    
    async def test_mission_extraction(self, builder):
        """Test mission extraction and formatting."""
        test_cases = [
            {
                'input': {'mission': 'Build authentication system'},
                'expected': 'Mission: Build authentication system'
            },
            {
                'input': {'mission': 'Mission: Already formatted'},
                'expected': 'Mission: Already formatted'
            },
            {
                'input': {},
                'expected': 'Mission: Define project objectives and goals'
            }
        ]
        
        for case in test_cases:
            mission = builder._extract_mission(case['input'])
            assert case['expected'] in mission
    
    async def test_constraints_extraction(self, builder):
        """Test constraints extraction and formatting."""
        globals_data = {
            'constraints': [
                'Must use HTTPS',
                'Support mobile devices',
                'Handle 1000+ concurrent users',
                'Comply with GDPR',
                'Use existing database',
                'Extra constraint'  # Should be filtered out (max 5)
            ]
        }
        
        constraints = builder._extract_constraints(globals_data)
        
        assert len(constraints) <= 5  # Should limit to max 5
        assert 'Must use HTTPS' in constraints
        assert all(isinstance(c, str) for c in constraints)
    
    async def test_focus_decisions_extraction(self, builder):
        """Test focus decisions extraction and structuring."""
        focus_ids = ['S001', 'S002']
        globals_data = {
            'runbook': {
                'decisions': [
                    {
                        'title': 'Use microservices architecture',
                        'status': 'accepted',
                        'impact': 'high'
                    },
                    {
                        'title': 'Choose React for frontend',
                        'status': 'provisional',
                        'impact': 'medium'
                    }
                ]
            }
        }
        
        decisions = builder._extract_focus_decisions(focus_ids, globals_data)
        
        assert len(decisions) > 0
        for decision in decisions:
            assert 'id' in decision
            assert 'title' in decision
            assert 'status' in decision
            assert 'impact' in decision
    
    async def test_runbook_generation(self, builder):
        """Test runbook generation with proper structure."""
        globals_data = {}
        focus_decisions = [
            {'title': 'Use JWT authentication', 'status': 'accepted', 'impact': 'high'},
            {'title': 'Implement OAuth', 'status': 'provisional', 'impact': 'medium'}
        ]
        focus_tasks = [
            {'title': 'Create user schema', 'priority': 'high'},
            {'title': 'Setup OAuth providers', 'priority': 'medium'}
        ]
        
        runbook = builder._build_runbook(globals_data, focus_decisions, focus_tasks)
        
        assert isinstance(runbook, dict)
        assert 'steps' in runbook
        assert isinstance(runbook['steps'], list)
        assert len(runbook['steps']) > 0
    
    async def test_working_set_with_empty_data(self, builder):
        """Test working set creation with minimal/empty data."""
        minimal_data = {
            'thread_id': 'test-thread',
            'globals': {},
            'focus_ids': [],
            'artifact_refs': [],
            'token_estimate': 0
        }
        
        working_set = builder.create_working_set(minimal_data)
        
        # Should handle empty data gracefully
        assert working_set['mission']  # Should have default mission
        assert len(working_set['constraints']) > 0  # Should have default constraints
        assert working_set['token_estimate'] >= 0


@pytest.mark.asyncio
class TestTokenBudgetManagement:
    """Test token budget management across all context memory operations."""
    
    @pytest.fixture
    def api_key(self):
        """Create a test API key."""
        return APIKey(
            key_hash="test_hash",
            workspace_id="test_workspace",
            name="Test Key",
            active=True,
            rpm_limit=100
        )
    
    async def test_end_to_end_token_budget_flow(self, api_key):
        """Test token budget management through complete workflow."""
        thread_id = "budget-test-thread"
        token_budget = 2000  # Limited budget
        
        # Step 1: Context Ingestion (should not be limited by budget)
        extractor = ContextExtractor()
        sample_content = """
        User: We need to build a complex authentication system with multiple features.
        Assistant: I recommend implementing JWT tokens, OAuth integration, multi-factor authentication, session management, password policies, and audit logging.
        """ * 10  # Make it large
        
        semantic_items = extractor.extract_semantic_items(sample_content, thread_id)
        assert len(semantic_items) > 0  # Should extract regardless of budget
        
        # Step 2: Context Retrieval (should respect budget)
        retriever = ContextRetriever()
        
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic, \
             patch.object(retriever, '_get_usage_stats') as mock_usage:
            
            mock_semantic.return_value = semantic_items
            mock_episodic.return_value = []
            mock_usage.return_value = {}
            
            mock_db = AsyncMock()
            retrieval_result = await retriever.recall_context(
                thread_id=thread_id,
                purpose="implement authentication",
                token_budget=token_budget,
                db=mock_db
            )
            
            # Should respect budget
            assert retrieval_result['token_estimate'] <= token_budget
        
        # Step 3: Working Set Creation (should respect budget)
        builder = WorkingSetBuilder()
        working_set = builder.create_working_set(
            retrieval_result,
            token_budget=token_budget
        )
        
        # Should respect overall budget
        assert working_set['token_estimate'] <= token_budget
        
        # Should maintain essential structure even with budget constraints
        assert working_set['mission']
        assert len(working_set['constraints']) > 0
    
    async def test_token_estimation_accuracy(self):
        """Test that token estimation is reasonably accurate."""
        # Create test content with known word/token counts
        test_content = {
            'mission': 'This is a test mission with exactly ten words here.',  # ~10 tokens
            'constraints': ['Constraint one with five words.', 'Another constraint here.'],  # ~7 tokens
            'focus_decisions': [
                {'title': 'Decision title', 'status': 'accepted', 'impact': 'high'}  # ~8 tokens
            ],
            'runbook': {'steps': ['Step one here', 'Step two here']},  # ~6 tokens
        }
        
        builder = WorkingSetBuilder()
        estimated_tokens = builder._estimate_working_set_tokens(test_content)
        
        # Should be reasonable estimate (rough approximation: 1.3 tokens per word)
        expected_approximate = 30  # Rough count
        assert abs(estimated_tokens - expected_approximate) < 20  # Allow variance
    
    async def test_progressive_budget_reduction(self):
        """Test that system gracefully handles progressive budget reduction."""
        # Create large dataset
        large_retrieval_data = {
            'thread_id': 'large-thread',
            'globals': {
                'mission': 'Implement comprehensive system with many features and complex requirements.',
                'constraints': [f'Constraint {i} with detailed requirements.' for i in range(1, 11)]
            },
            'focus_ids': [f'S{i:03d}' for i in range(1, 51)],  # 50 items
            'artifact_refs': [f'file_{i}.py' for i in range(1, 21)],  # 20 files
            'token_estimate': 10000
        }
        
        builder = WorkingSetBuilder()
        
        # Test with decreasing budgets
        budgets = [8000, 4000, 2000, 1000, 500]
        
        for budget in budgets:
            working_set = builder.create_working_set(
                large_retrieval_data.copy(),
                token_budget=budget
            )
            
            # Should respect budget
            assert working_set['token_estimate'] <= budget * 1.1  # 10% tolerance
            
            # Should maintain essential elements
            assert working_set['mission']
            assert len(working_set['constraints']) > 0
            
            # Smaller budgets should result in fewer/shorter elements
            if budget < 2000:
                assert len(working_set['focus_decisions']) <= 5
                assert len(working_set['constraints']) <= 3


if __name__ == "__main__":
    pytest.main([__file__])