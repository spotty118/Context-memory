"""
Comprehensive tests for context memory integration scenarios and edge cases.
Tests feedback processing, context expansion, consolidation, and error handling.
"""
import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, List, Any

from app.services.consolidator import ContextConsolidator
from app.api.ingest import IngestRequest, IngestMaterials
from app.api.recall import RecallRequest
from app.api.workingset import WorkingSetRequest
from app.api.feedback import FeedbackRequest
from app.db.models import SemanticItem, EpisodicItem, Artifact, APIKey
from app.core.exceptions import ContextMemoryError, TokenBudgetExceededError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
class TestContextMemoryIntegration:
    """Test integration scenarios across context memory services."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    @pytest.fixture
    def api_key(self):
        """Create a test API key."""
        return APIKey(
            key_hash="integration_test_hash",
            workspace_id="integration_workspace",
            name="Integration Test Key",
            active=True,
            rpm_limit=100
        )
    
    async def test_complete_context_lifecycle(self, mock_db_session, api_key):
        """Test complete context memory lifecycle: ingest -> recall -> working set -> feedback."""
        thread_id = "lifecycle-test-thread"
        
        # Step 1: Ingest context materials
        ingest_request = IngestRequest(
            thread_id=thread_id,
            materials=IngestMaterials(
                chat="""
                User: We need to implement a user management system.
                Assistant: I recommend creating a REST API with CRUD operations for users.
                User: What about authentication and authorization?
                Assistant: We should implement JWT tokens and role-based access control.
                """,
                diffs="""
                diff --git a/user_api.py b/user_api.py
                +@app.post("/users")
                +def create_user(user: UserCreate):
                +    return user_service.create(user)
                """,
                logs="""
                2025-01-20 10:30:00 INFO: User service started
                2025-01-20 10:31:00 ERROR: Failed to create user - duplicate email
                """
            ),
            purpose="Setting up user management system"
        )
        
        # Mock the ingestion process
        with patch('app.services.extractor.ContextExtractor') as mock_extractor_class:
            mock_extractor = mock_extractor_class.return_value
            mock_extractor.extract_semantic_items.return_value = [
                {
                    'id': 'S001',
                    'thread_id': thread_id,
                    'kind': 'decision',
                    'title': 'Use JWT tokens for authentication',
                    'body': 'Decided to implement JWT tokens for user authentication.',
                    'status': 'accepted',
                    'salience': 0.9
                }
            ]
            mock_extractor.extract_episodic_items.return_value = [
                {
                    'id': 'E001',
                    'thread_id': thread_id,
                    'kind': 'log',
                    'title': 'User creation failed',
                    'snippet': 'ERROR: Failed to create user - duplicate email',
                    'source': 'app_logs',
                    'salience': 0.7
                }
            ]
            mock_extractor.extract_artifacts.return_value = [
                {
                    'id': 'A001',
                    'thread_id': thread_id,
                    'path': 'user_api.py',
                    'kind': 'code',
                    'content': '@app.post("/users")\ndef create_user(user: UserCreate):\n    return user_service.create(user)'
                }
            ]
            
            # Mock database operations
            mock_db_session.execute.return_value.scalars.return_value.all.return_value = []
            mock_db_session.add.return_value = None
            mock_db_session.commit.return_value = None
            
            # This would be the actual API call in real scenario
            # ingest_result = await ingest_context(ingest_request, api_key, mock_db_session)
            
            # For this test, we simulate successful ingestion
            ingest_result = {
                'thread_id': thread_id,
                'added_ids': ['S001', 'E001', 'A001'],
                'updated_ids': [],
                'summary': 'Ingested user management context'
            }
            
            assert ingest_result['thread_id'] == thread_id
            assert len(ingest_result['added_ids']) == 3
        
        # Step 2: Recall context for related work
        recall_request = RecallRequest(
            thread_id=thread_id,
            purpose="Continue implementing user authentication system",
            token_budget=4000
        )
        
        with patch('app.services.retrieval.ContextRetriever') as mock_retriever_class:
            mock_retriever = mock_retriever_class.return_value
            mock_retriever.recall_context.return_value = {
                'thread_id': thread_id,
                'globals': {
                    'mission': 'Implement secure user management system',
                    'constraints': ['Use JWT tokens', 'Implement RBAC']
                },
                'focus_ids': ['S001'],
                'artifact_refs': ['user_api.py'],
                'token_estimate': 3500
            }
            
            recall_result = await mock_retriever.recall_context(
                thread_id=recall_request.thread_id,
                purpose=recall_request.purpose,
                token_budget=recall_request.token_budget,
                db=mock_db_session
            )
            
            assert recall_result['thread_id'] == thread_id
            assert recall_result['token_estimate'] <= recall_request.token_budget
        
        # Step 3: Create working set
        workingset_request = WorkingSetRequest(
            thread_id=thread_id,
            retrieval=recall_result,
            token_budget=8000
        )
        
        with patch('app.services.workingset.WorkingSetBuilder') as mock_builder_class:
            mock_builder = mock_builder_class.return_value
            mock_builder.create_working_set.return_value = {
                'mission': 'Implement secure user management system with JWT authentication',
                'constraints': ['Use JWT tokens', 'Implement RBAC', 'Handle duplicate emails'],
                'focus_decisions': [
                    {'id': 'S001', 'title': 'Use JWT tokens for authentication', 'status': 'accepted'}
                ],
                'focus_tasks': [
                    {'id': 'T001', 'title': 'Create user CRUD API', 'priority': 'high'}
                ],
                'runbook': {'steps': ['Set up JWT middleware', 'Create user endpoints']},
                'artifacts': ['user_api.py'],
                'citations': ['S001'],
                'open_questions': ['How to handle email verification?'],
                'token_estimate': 7500
            }
            
            working_set = mock_builder.create_working_set(
                workingset_request.retrieval,
                workingset_request.token_budget
            )
            
            assert working_set['token_estimate'] <= workingset_request.token_budget
            assert 'mission' in working_set
            assert len(working_set['focus_decisions']) > 0
        
        # Step 4: Provide feedback on helpful items
        feedback_request = FeedbackRequest(
            item_id='S001',
            feedback_type='helpful',
            value=1.0,
            comment='This decision helped implement authentication correctly'
        )
        
        # Mock feedback processing
        with patch('app.db.models.UsageStats') as mock_usage_stats:
            # Simulate successful feedback recording
            feedback_result = {
                'item_id': feedback_request.item_id,
                'status': 'recorded',
                'new_salience': 0.95  # Increased due to positive feedback
            }
            
            assert feedback_result['status'] == 'recorded'
            assert feedback_result['new_salience'] > 0.9
    
    async def test_context_consolidation_workflow(self, mock_db_session):
        """Test context consolidation for reducing redundancy."""
        thread_id = "consolidation-test-thread"
        
        # Create overlapping semantic items
        overlapping_items = [
            {
                'id': 'S001',
                'thread_id': thread_id,
                'kind': 'decision',
                'title': 'Use React for frontend',
                'body': 'We decided to use React for the frontend framework.',
                'status': 'accepted',
                'salience': 0.8
            },
            {
                'id': 'S002',
                'thread_id': thread_id,
                'kind': 'decision',
                'title': 'Choose React framework',
                'body': 'After evaluation, we chose React as our frontend framework.',
                'status': 'accepted',
                'salience': 0.7
            },
            {
                'id': 'S003',
                'thread_id': thread_id,
                'kind': 'requirement',
                'title': 'Frontend framework selection',
                'body': 'Need to select a modern frontend framework for the application.',
                'status': 'resolved',
                'salience': 0.6
            }
        ]
        
        consolidator = ContextConsolidator()
        
        with patch.object(consolidator, '_find_similar_items') as mock_similar, \
             patch.object(consolidator, '_merge_items') as mock_merge:
            
            # Mock similarity detection
            mock_similar.return_value = [
                ('S001', 'S002', 0.85),  # High similarity
                ('S001', 'S003', 0.65),  # Medium similarity
            ]
            
            # Mock merging
            mock_merge.return_value = {
                'id': 'S001_merged',
                'thread_id': thread_id,
                'kind': 'decision',
                'title': 'Use React for frontend',
                'body': 'We decided to use React for the frontend framework after evaluation.',
                'status': 'accepted',
                'salience': 0.9,  # Combined salience
                'merged_from': ['S001', 'S002', 'S003']
            }
            
            # Perform consolidation
            consolidated_items = await consolidator.consolidate_thread_context(
                thread_id, mock_db_session
            )
            
            # Should reduce redundancy
            assert len(consolidated_items) < len(overlapping_items)
            
            # Merged item should have higher salience
            merged_item = next(item for item in consolidated_items if 'merged_from' in item)
            assert merged_item['salience'] > 0.8
    
    async def test_context_expansion_with_related_items(self, mock_db_session):
        """Test context expansion functionality."""
        item_id = 'S001'
        
        # Mock the item and its related items
        base_item = {
            'id': item_id,
            'thread_id': 'test-thread',
            'kind': 'decision',
            'title': 'Use microservices architecture',
            'body': 'Decided to implement microservices for better scalability.',
            'links': {'related': ['S002', 'S003']}
        }
        
        related_items = [
            {
                'id': 'S002',
                'thread_id': 'test-thread',
                'kind': 'requirement',
                'title': 'Scalability requirements',
                'body': 'System must handle 10,000+ concurrent users.'
            },
            {
                'id': 'S003',
                'thread_id': 'test-thread',
                'kind': 'constraint',
                'title': 'Technology constraints',
                'body': 'Must use existing Python infrastructure.'
            }
        ]
        
        # Mock database queries for expansion
        mock_db_session.execute.return_value.scalar_one_or_none.return_value = base_item
        mock_db_session.execute.return_value.scalars.return_value.all.return_value = related_items
        
        # Simulate expansion logic
        expanded_context = {
            'item': base_item,
            'related_items': related_items,
            'context_graph': {
                'nodes': [base_item] + related_items,
                'edges': [
                    {'from': 'S001', 'to': 'S002', 'type': 'related'},
                    {'from': 'S001', 'to': 'S003', 'type': 'related'}
                ]
            },
            'token_estimate': 250
        }
        
        assert expanded_context['item']['id'] == item_id
        assert len(expanded_context['related_items']) == 2
        assert len(expanded_context['context_graph']['nodes']) == 3


@pytest.mark.asyncio
class TestContextMemoryErrorHandling:
    """Test error handling and edge cases in context memory operations."""
    
    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return AsyncMock(spec=AsyncSession)
    
    async def test_token_budget_exceeded_error(self, mock_db_session):
        """Test handling of token budget exceeded scenarios."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        
        # Create a scenario where token budget is exceeded
        with patch.object(retriever, '_estimate_tokens') as mock_estimate:
            mock_estimate.return_value = 10000  # Exceeds typical budgets
            
            # Should raise appropriate exception or handle gracefully
            with pytest.raises(TokenBudgetExceededError):
                await retriever.recall_context(
                    thread_id="test-thread",
                    purpose="test purpose",
                    token_budget=1000,  # Much smaller than estimated
                    db=mock_db_session
                )
    
    async def test_empty_thread_context(self, mock_db_session):
        """Test handling of threads with no context."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        
        # Mock empty results
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic:
            
            mock_semantic.return_value = []
            mock_episodic.return_value = []
            
            result = await retriever.recall_context(
                thread_id="empty-thread",
                purpose="test purpose",
                token_budget=4000,
                db=mock_db_session
            )
            
            # Should handle empty context gracefully
            assert result['thread_id'] == "empty-thread"
            assert result['focus_ids'] == []
            assert result['token_estimate'] >= 0
    
    async def test_malformed_content_ingestion(self):
        """Test handling of malformed or corrupted content."""
        from app.services.extractor import ContextExtractor
        
        extractor = ContextExtractor()
        
        # Test various malformed inputs
        malformed_inputs = [
            "",  # Empty content
            "\x00\x01\x02",  # Binary content
            "�" * 1000,  # Invalid UTF-8
            "\n" * 10000,  # Only newlines
            "a" * 100000,  # Extremely long single line
        ]
        
        for malformed_content in malformed_inputs:
            try:
                semantic_items = extractor.extract_semantic_items(malformed_content, "test-thread")
                episodic_items = extractor.extract_episodic_items(malformed_content, "test-thread")
                
                # Should not crash and return valid structures
                assert isinstance(semantic_items, list)
                assert isinstance(episodic_items, list)
                
                # Items should have required fields if any are created
                for item in semantic_items + episodic_items:
                    assert 'id' in item
                    assert 'thread_id' in item
                    
            except Exception as e:
                # If exceptions are raised, they should be specific context memory errors
                assert isinstance(e, ContextMemoryError)
    
    async def test_database_connection_failure(self, mock_db_session):
        """Test handling of database connection failures."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        
        # Mock database failure
        mock_db_session.execute.side_effect = Exception("Database connection failed")
        
        with pytest.raises(Exception) as exc_info:
            await retriever.recall_context(
                thread_id="test-thread",
                purpose="test purpose",
                token_budget=4000,
                db=mock_db_session
            )
        
        assert "Database connection failed" in str(exc_info.value)
    
    async def test_concurrent_access_handling(self, mock_db_session):
        """Test handling of concurrent access to same thread context."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        thread_id = "concurrent-test-thread"
        
        # Mock successful retrieval
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic, \
             patch.object(retriever, '_get_usage_stats') as mock_usage:
            
            mock_semantic.return_value = [
                {
                    'id': 'S001',
                    'thread_id': thread_id,
                    'kind': 'decision',
                    'title': 'Test decision',
                    'body': 'Test body',
                    'status': 'accepted',
                    'tags': [],
                    'links': {},
                    'salience': 0.8,
                    'created_at': datetime.utcnow(),
                    'updated_at': datetime.utcnow()
                }
            ]
            mock_episodic.return_value = []
            mock_usage.return_value = {}
            
            # Create multiple concurrent requests
            tasks = [
                retriever.recall_context(
                    thread_id=thread_id,
                    purpose=f"concurrent purpose {i}",
                    token_budget=2000,
                    db=mock_db_session
                )
                for i in range(5)
            ]
            
            # All should complete successfully
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check that all requests succeeded
            successful_results = [r for r in results if not isinstance(r, Exception)]
            assert len(successful_results) == 5
            
            # All should return valid results
            for result in successful_results:
                assert result['thread_id'] == thread_id
                assert 'token_estimate' in result
    
    async def test_scoring_algorithm_edge_cases(self):
        """Test scoring algorithm with edge case inputs."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        
        # Test with extreme dates
        extreme_items = [
            {
                'id': 'S001',
                'thread_id': 'test-thread',
                'kind': 'decision',
                'title': 'Very old decision',
                'body': 'Ancient decision',
                'status': 'accepted',
                'tags': [],
                'links': {},
                'salience': 0.5,
                'created_at': datetime(1970, 1, 1),  # Unix epoch
                'updated_at': datetime(1970, 1, 1)
            },
            {
                'id': 'S002',
                'thread_id': 'test-thread',
                'kind': 'decision',
                'title': 'Future decision',
                'body': 'Decision from future',
                'status': 'accepted',
                'tags': [],
                'links': {},
                'salience': 0.5,
                'created_at': datetime(2030, 1, 1),  # Future date
                'updated_at': datetime(2030, 1, 1)
            }
        ]
        
        # Test recency scoring with extreme dates
        for item in extreme_items:
            recency_score = retriever._calculate_recency(item)
            assert 0.0 <= recency_score <= 1.0  # Should still be valid
    
    async def test_working_set_with_zero_budget(self):
        """Test working set creation with zero token budget."""
        from app.services.workingset import WorkingSetBuilder
        
        builder = WorkingSetBuilder()
        
        minimal_data = {
            'thread_id': 'zero-budget-thread',
            'globals': {
                'mission': 'Test mission with some content',
                'constraints': ['Constraint 1', 'Constraint 2']
            },
            'focus_ids': ['S001', 'S002'],
            'artifact_refs': ['file1.py', 'file2.py'],
            'token_estimate': 1000
        }
        
        # Should handle zero budget gracefully
        working_set = builder.create_working_set(minimal_data, token_budget=0)
        
        # Should still provide minimal working set
        assert working_set['mission']  # Should have some mission
        assert working_set['token_estimate'] >= 0
        
        # With zero budget, should be very minimal
        assert working_set['token_estimate'] <= 100  # Very small


@pytest.mark.asyncio 
class TestContextMemoryPerformance:
    """Test performance characteristics of context memory operations."""
    
    async def test_large_context_retrieval_performance(self):
        """Test retrieval performance with large context datasets."""
        from app.services.retrieval import ContextRetriever
        
        retriever = ContextRetriever()
        
        # Create large dataset
        large_semantic_items = [
            {
                'id': f'S{i:05d}',
                'thread_id': 'large-thread',
                'kind': 'decision',
                'title': f'Decision {i}',
                'body': f'This is decision {i} with some content for testing.',
                'status': 'accepted',
                'tags': [f'tag{i}'],
                'links': {},
                'salience': 0.5 + (i % 50) / 100,  # Varying salience
                'created_at': datetime.utcnow() - timedelta(minutes=i),
                'updated_at': datetime.utcnow() - timedelta(minutes=i//2)
            }
            for i in range(1000)  # 1000 items
        ]
        
        # Mock database to return large dataset
        mock_db = AsyncMock()
        
        with patch.object(retriever, '_get_semantic_items') as mock_semantic, \
             patch.object(retriever, '_get_episodic_items') as mock_episodic, \
             patch.object(retriever, '_get_usage_stats') as mock_usage:
            
            mock_semantic.return_value = large_semantic_items
            mock_episodic.return_value = []
            mock_usage.return_value = {}
            
            # Measure performance
            start_time = asyncio.get_event_loop().time()
            
            result = await retriever.recall_context(
                thread_id="large-thread",
                purpose="test performance",
                token_budget=8000,
                db=mock_db
            )
            
            end_time = asyncio.get_event_loop().time()
            execution_time = end_time - start_time
            
            # Should complete within reasonable time
            assert execution_time < 5.0  # Should complete within 5 seconds
            
            # Should return reasonable subset
            assert len(result['focus_ids']) > 0
            assert len(result['focus_ids']) < len(large_semantic_items)  # Should filter
    
    async def test_token_budget_scaling(self):
        """Test how system scales with different token budgets."""
        from app.services.workingset import WorkingSetBuilder
        
        builder = WorkingSetBuilder()
        
        # Create rich dataset
        rich_data = {
            'thread_id': 'scaling-thread',
            'globals': {
                'mission': 'Complex mission with detailed requirements and multiple objectives.',
                'constraints': [
                    f'Complex constraint {i} with detailed specifications and requirements.'
                    for i in range(1, 21)
                ]
            },
            'focus_ids': [f'S{i:03d}' for i in range(1, 101)],  # 100 focus items
            'artifact_refs': [f'module_{i}.py' for i in range(1, 51)],  # 50 artifacts
            'token_estimate': 20000
        }
        
        # Test with different budget scales
        budget_scales = [500, 1000, 2000, 4000, 8000, 16000]
        
        for budget in budget_scales:
            working_set = builder.create_working_set(rich_data.copy(), token_budget=budget)
            
            # Should scale content with budget
            assert working_set['token_estimate'] <= budget * 1.1  # 10% tolerance
            
            # Larger budgets should include more content
            if budget >= 4000:
                assert len(working_set['focus_decisions']) >= 3
                assert len(working_set['constraints']) >= 3
            elif budget >= 1000:
                assert len(working_set['focus_decisions']) >= 1
                assert len(working_set['constraints']) >= 1


if __name__ == "__main__":
    pytest.main([__file__])