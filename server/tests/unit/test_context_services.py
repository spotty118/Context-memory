"""
Unit tests for context memory services.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from app.services.extractor import ContextExtractor
from app.services.consolidator import ContextConsolidator
from app.services.retrieval import ContextRetriever
from app.services.workingset import WorkingSetBuilder


class TestContextExtractor:
    """Test the ContextExtractor service."""
    
    @pytest.fixture
    def extractor(self):
        """Create a ContextExtractor instance."""
        return ContextExtractor()
    
    def test_extract_from_chat_content(self, extractor):
        """Test extracting context from chat content."""
        content = """
        User: We need to implement user authentication for the web app.
        Assistant: I recommend using JWT tokens for authentication. We should also implement password hashing with bcrypt.
        User: Great! Let's also add OAuth integration with Google and GitHub.
        """
        
        result = extractor.extract_from_chat(content, "test-thread-123")
        
        assert "semantic_items" in result
        assert "episodic_items" in result
        assert len(result["semantic_items"]) > 0
        
        # Check that decisions and requirements are extracted
        semantic_items = result["semantic_items"]
        decision_items = [item for item in semantic_items if item["item_type"] == "decision"]
        requirement_items = [item for item in semantic_items if item["item_type"] == "requirement"]
        
        assert len(decision_items) > 0 or len(requirement_items) > 0
    
    def test_extract_from_diff_content(self, extractor):
        """Test extracting context from diff content."""
        diff_content = """
        diff --git a/src/auth.py b/src/auth.py
        index 1234567..abcdefg 100644
        --- a/src/auth.py
        +++ b/src/auth.py
        @@ -10,6 +10,12 @@ def authenticate_user(username, password):
             if not user:
                 return None
         
        +    # Add password hashing verification
        +    if not verify_password(password, user.password_hash):
        +        return None
        +
             return user
        """
        
        result = extractor.extract_from_diff(diff_content, "test-thread-123")
        
        assert "semantic_items" in result
        assert "artifacts" in result
        
        # Should extract the code change as an artifact
        artifacts = result["artifacts"]
        assert len(artifacts) > 0
        assert any("auth.py" in artifact["title"] for artifact in artifacts)
    
    def test_extract_from_logs_content(self, extractor):
        """Test extracting context from log content."""
        log_content = """
        2025-01-20 10:00:00 ERROR [auth.py:25] Authentication failed for user john_doe
        2025-01-20 10:00:01 INFO [auth.py:30] Password reset requested for user jane_smith
        2025-01-20 10:00:02 ERROR [database.py:15] Connection timeout to PostgreSQL database
        2025-01-20 10:00:03 WARN [api.py:45] Rate limit exceeded for IP 192.168.1.100
        """
        
        result = extractor.extract_from_logs(log_content, "test-thread-123")
        
        assert "episodic_items" in result
        
        # Should extract errors and warnings as episodic items
        episodic_items = result["episodic_items"]
        error_items = [item for item in episodic_items if item["item_type"] == "error"]
        
        assert len(error_items) > 0
    
    def test_redact_sensitive_data(self, extractor):
        """Test that sensitive data is redacted."""
        content = """
        The database password is 'super_secret_123' and the API key is 'sk-1234567890abcdef'.
        User email: john.doe@example.com
        Credit card: 4532-1234-5678-9012
        """
        
        redacted = extractor._redact_sensitive_data(content)
        
        assert "super_secret_123" not in redacted
        assert "sk-1234567890abcdef" not in redacted
        assert "john.doe@example.com" not in redacted
        assert "4532-1234-5678-9012" not in redacted
        assert "[REDACTED]" in redacted
    
    def test_extract_semantic_items(self, extractor):
        """Test semantic item extraction."""
        content = "We decided to use React for the frontend and Node.js for the backend."
        
        items = extractor._extract_semantic_items(content, "test-thread")
        
        assert len(items) > 0
        assert any(item["item_type"] == "decision" for item in items)
    
    def test_extract_episodic_items(self, extractor):
        """Test episodic item extraction."""
        content = "Test failed: AssertionError in test_user_login at line 45"
        
        items = extractor._extract_episodic_items(content, "test-thread")
        
        assert len(items) > 0
        assert any(item["item_type"] == "test_failure" for item in items)


class TestContextConsolidator:
    """Test the ContextConsolidator service."""
    
    @pytest.fixture
    def consolidator(self):
        """Create a ContextConsolidator instance."""
        return ContextConsolidator()
    
    @pytest.fixture
    def sample_semantic_items(self):
        """Sample semantic items for testing."""
        return [
            {
                "id": "S001",
                "thread_id": "test-thread",
                "item_type": "decision",
                "content": "We decided to use React for the frontend",
                "salience": 0.8
            },
            {
                "id": "S002", 
                "thread_id": "test-thread",
                "item_type": "decision",
                "content": "We chose React as our frontend framework",
                "salience": 0.7
            },
            {
                "id": "S003",
                "thread_id": "test-thread", 
                "item_type": "requirement",
                "content": "The app must support user authentication",
                "salience": 0.9
            }
        ]
    
    def test_consolidate_duplicates(self, consolidator, sample_semantic_items):
        """Test consolidation of duplicate items."""
        result = consolidator.consolidate_semantic_items(sample_semantic_items)
        
        # Should merge the two similar React decisions
        assert len(result) < len(sample_semantic_items)
        
        # The merged item should have higher salience
        react_items = [item for item in result if "React" in item["content"]]
        assert len(react_items) == 1
        assert react_items[0]["salience"] > 0.8
    
    def test_calculate_similarity(self, consolidator):
        """Test similarity calculation between items."""
        item1 = "We decided to use React for the frontend"
        item2 = "We chose React as our frontend framework"
        item3 = "The app must support user authentication"
        
        similarity_high = consolidator._calculate_similarity(item1, item2)
        similarity_low = consolidator._calculate_similarity(item1, item3)
        
        assert similarity_high > similarity_low
        assert similarity_high > 0.7  # Should be considered similar
        assert similarity_low < 0.5   # Should not be considered similar
    
    def test_merge_similar_items(self, consolidator):
        """Test merging of similar items."""
        item1 = {
            "content": "We decided to use React for the frontend",
            "salience": 0.8,
            "usage_count": 3
        }
        item2 = {
            "content": "We chose React as our frontend framework", 
            "salience": 0.7,
            "usage_count": 2
        }
        
        merged = consolidator._merge_items(item1, item2)
        
        assert merged["salience"] > max(item1["salience"], item2["salience"])
        assert merged["usage_count"] == item1["usage_count"] + item2["usage_count"]
        assert len(merged["content"]) > len(item1["content"])  # Should combine content


class TestContextRetriever:
    """Test the ContextRetriever service."""
    
    @pytest.fixture
    def retriever(self):
        """Create a ContextRetriever instance."""
        return ContextRetriever()
    
    @pytest.fixture
    def mock_db_session(self):
        """Mock database session."""
        return MagicMock()
    
    def test_calculate_scoring_weights(self, retriever):
        """Test the scoring weight calculation."""
        weights = retriever._get_scoring_weights()
        
        # Verify the exact weights from requirements
        assert weights["task_relevance"] == 0.28
        assert weights["decision_weight"] == 0.22
        assert weights["recency"] == 0.16
        assert weights["graph_degree"] == 0.12
        assert weights["failure_impact"] == 0.12
        assert weights["usage_frequency"] == 0.08
        assert weights["redundancy_penalty"] == -0.06
        
        # Weights should sum to approximately 1.0 (excluding penalty)
        positive_weights = sum(w for w in weights.values() if w > 0)
        assert abs(positive_weights - 1.0) < 0.01
    
    def test_calculate_item_score(self, retriever):
        """Test individual item scoring."""
        item = {
            "item_type": "decision",
            "content": "We decided to use React for the frontend",
            "salience": 0.8,
            "usage_count": 5,
            "created_at": datetime.utcnow(),
            "last_accessed_at": datetime.utcnow()
        }
        purpose = "Continue discussion about frontend framework choice"
        
        score = retriever._calculate_item_score(item, purpose, [])
        
        assert isinstance(score, float)
        assert score > 0
        assert score <= 1.0
    
    def test_token_budget_management(self, retriever):
        """Test that items are selected within token budget."""
        items = [
            {"content": "Short item", "score": 0.9},
            {"content": "Medium length item with more content", "score": 0.8},
            {"content": "Very long item with lots of content that takes up many tokens and exceeds the budget", "score": 0.7}
        ]
        
        selected = retriever._select_items_within_budget(items, token_budget=50)
        
        # Should select items that fit within budget
        total_tokens = sum(len(item["content"].split()) for item in selected)
        assert total_tokens <= 50
        
        # Should prioritize higher scoring items
        if len(selected) > 1:
            scores = [item["score"] for item in selected]
            assert scores == sorted(scores, reverse=True)


class TestWorkingSetBuilder:
    """Test the WorkingSetBuilder service."""
    
    @pytest.fixture
    def builder(self):
        """Create a WorkingSetBuilder instance."""
        return WorkingSetBuilder()
    
    @pytest.fixture
    def sample_context_items(self):
        """Sample context items for building working sets."""
        return {
            "semantic_items": [
                {
                    "id": "S001",
                    "item_type": "decision",
                    "content": "We decided to use React for the frontend framework",
                    "salience": 0.9
                },
                {
                    "id": "S002",
                    "item_type": "requirement", 
                    "content": "The application must support user authentication",
                    "salience": 0.8
                },
                {
                    "id": "S003",
                    "item_type": "constraint",
                    "content": "Must be completed within 2 weeks",
                    "salience": 0.7
                }
            ],
            "episodic_items": [
                {
                    "id": "E001",
                    "item_type": "test_failure",
                    "content": "Authentication test failed: invalid token error",
                    "salience": 0.6
                }
            ],
            "artifacts": [
                {
                    "id": "CODE001",
                    "title": "Authentication Component",
                    "content": "React authentication component code",
                    "file_path": "/src/components/Auth.jsx"
                }
            ]
        }
    
    def test_build_working_set_structure(self, builder, sample_context_items):
        """Test that working set has correct structure."""
        purpose = "Implement user authentication feature"
        
        working_set = builder.build_working_set(
            context_items=sample_context_items,
            purpose=purpose,
            token_budget=4000
        )
        
        # Check required structure
        assert "mission" in working_set
        assert "constraints" in working_set
        assert "focus_decisions" in working_set
        assert "focus_tasks" in working_set
        assert "runbook" in working_set
        assert "artifacts" in working_set
        assert "citations" in working_set
        assert "open_questions" in working_set
        
        # Check content
        assert purpose in working_set["mission"]
        assert len(working_set["focus_decisions"]) > 0
        assert len(working_set["artifacts"]) > 0
    
    def test_token_budget_compliance(self, builder, sample_context_items):
        """Test that working set respects token budget."""
        working_set = builder.build_working_set(
            context_items=sample_context_items,
            purpose="Test purpose",
            token_budget=500  # Small budget
        )
        
        # Estimate token count (rough approximation)
        total_text = str(working_set)
        estimated_tokens = len(total_text.split())
        
        # Should be approximately within budget (allowing some overhead)
        assert estimated_tokens <= 600  # 20% buffer
    
    def test_focus_area_filtering(self, builder, sample_context_items):
        """Test filtering by focus areas."""
        working_set = builder.build_working_set(
            context_items=sample_context_items,
            purpose="Authentication work",
            token_budget=4000,
            focus_areas=["authentication", "security"]
        )
        
        # Should prioritize authentication-related content
        focus_decisions = working_set["focus_decisions"]
        auth_related = any("authentication" in decision.lower() for decision in focus_decisions)
        assert auth_related
    
    def test_generate_runbook(self, builder, sample_context_items):
        """Test runbook generation."""
        runbook = builder._generate_runbook(
            sample_context_items,
            "Implement authentication",
            ["authentication", "frontend"]
        )
        
        assert isinstance(runbook, list)
        assert len(runbook) > 0
        assert all(isinstance(step, str) for step in runbook)
    
    def test_identify_open_questions(self, builder, sample_context_items):
        """Test open questions identification."""
        questions = builder._identify_open_questions(
            sample_context_items,
            "Implement authentication"
        )
        
        assert isinstance(questions, list)
        assert len(questions) > 0
        assert all(isinstance(q, str) for q in questions)
        assert all(q.endswith("?") for q in questions)
    
    def test_format_citations(self, builder, sample_context_items):
        """Test citation formatting."""
        citations = builder._format_citations(sample_context_items)
        
        assert isinstance(citations, dict)
        assert "semantic" in citations
        assert "episodic" in citations  
        assert "artifacts" in citations
        
        # Check citation format
        semantic_citations = citations["semantic"]
        assert len(semantic_citations) > 0
        assert all("S" in citation for citation in semantic_citations)
    
    def test_trim_to_budget(self, builder):
        """Test content trimming to fit budget."""
        long_content = " ".join(["word"] * 1000)  # 1000 words
        
        trimmed = builder._trim_to_budget(long_content, token_budget=100)
        
        estimated_tokens = len(trimmed.split())
        assert estimated_tokens <= 100

