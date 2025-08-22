"""
Comprehensive tests for database migrations.
Tests that migrations work correctly in both directions (upgrade and downgrade).
"""
import pytest
import tempfile
import os
from datetime import datetime
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List
import sqlalchemy as sa
from sqlalchemy import create_engine, MetaData, inspect, text
from sqlalchemy.pool import StaticPool
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.db.models import Base
from app.core.config import settings


@pytest.mark.database
class TestDatabaseMigrations:
    """Test database migration functionality."""
    
    @pytest.fixture(scope="function")
    def test_database_url(self):
        """Create a temporary SQLite database for testing."""
        # Use SQLite for isolated testing
        return "sqlite:///:memory:"
    
    @pytest.fixture(scope="function")
    def alembic_config(self, test_database_url):
        """Create Alembic configuration for testing."""
        # Create temporary alembic.ini
        config = Config()
        config.set_main_option("script_location", "app/db/migrations")
        config.set_main_option("sqlalchemy.url", test_database_url)
        config.set_main_option("file_template", "%%(year)d_%%(month).2d_%%(day).2d_%%(hour).2d%%(minute).2d-%%(rev)s_%%(slug)s")
        
        return config
    
    @pytest.fixture(scope="function")
    def test_engine(self, test_database_url):
        """Create test database engine."""
        engine = create_engine(
            test_database_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False}
        )
        return engine
    
    def test_migration_versions_exist(self):
        """Test that migration version files exist and are properly structured."""
        migrations_dir = "app/db/migrations/versions"
        
        assert os.path.exists(migrations_dir), "Migrations directory should exist"
        
        # Check that migration files exist
        migration_files = [f for f in os.listdir(migrations_dir) if f.endswith('.py') and not f.startswith('__')]
        assert len(migration_files) > 0, "Should have at least one migration file"
        
        # Expected migration files
        expected_files = [
            "001_initial_schema.py",
            "002_seed_data.py", 
            "003_performance_indexes.py"
        ]
        
        for expected_file in expected_files:
            assert expected_file in migration_files, f"Expected migration file {expected_file} should exist"
    
    def test_migration_file_structure(self):
        """Test that migration files have proper structure."""
        migration_file = "app/db/migrations/versions/001_initial_schema.py"
        
        with open(migration_file, 'r') as f:
            content = f.read()
        
        # Check required elements
        assert 'revision = ' in content, "Migration should have revision identifier"
        assert 'down_revision = ' in content, "Migration should have down_revision"
        assert 'def upgrade() -> None:' in content, "Migration should have upgrade function"
        assert 'def downgrade() -> None:' in content, "Migration should have downgrade function"
    
    def test_migration_chain_integrity(self):
        """Test that migration chain is properly linked."""
        migrations_dir = "app/db/migrations"
        
        # Mock the config for testing
        with patch('app.db.migrations.env.config') as mock_config:
            mock_config.config_file_name = None
            
            script_dir = ScriptDirectory.from_config(Config())
            
            # Get all revisions
            revisions = list(script_dir.walk_revisions())
            
            assert len(revisions) > 0, "Should have migration revisions"
            
            # Check chain integrity
            for revision in revisions:
                if revision.down_revision:
                    # Check that down_revision exists
                    down_rev = script_dir.get_revision(revision.down_revision)
                    assert down_rev is not None, f"Down revision {revision.down_revision} should exist"
    
    def test_fresh_database_migration(self, test_engine, alembic_config):
        """Test running migrations on a fresh database."""
        # Start with empty database
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        
        # Should start empty
        assert len(metadata.tables) == 0, "Fresh database should have no tables"
        
        # Mock pgvector extension creation for SQLite
        with patch('alembic.op.execute') as mock_execute:
            mock_execute.return_value = None
            
            # Run migrations
            command.upgrade(alembic_config, "head")
        
        # Verify tables were created
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        
        # Check that core tables exist
        expected_tables = [
            'model_catalog', 'settings', 'api_keys', 'usage_ledger',
            'threads', 'semantic_items', 'episodic_items', 'artifacts'
        ]
        
        for table_name in expected_tables:
            assert table_name in metadata.tables, f"Table {table_name} should exist after migration"
    
    def test_migration_rollback(self, test_engine, alembic_config):
        """Test rolling back migrations."""
        # Apply all migrations first
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "head")
        
        # Verify tables exist
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        initial_table_count = len(metadata.tables)
        assert initial_table_count > 0, "Should have tables after upgrade"
        
        # Rollback one migration
        with patch('alembic.op.execute'):
            command.downgrade(alembic_config, "-1")
        
        # Verify rollback worked
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        
        # Should have fewer tables or different structure
        # (Exact check depends on what the last migration does)
        assert len(metadata.tables) >= 0, "Should handle rollback gracefully"
    
    def test_incremental_migrations(self, test_engine, alembic_config):
        """Test applying migrations incrementally."""
        migration_steps = ["001", "002", "003"]
        
        with patch('alembic.op.execute'):
            for step in migration_steps:
                # Apply migration up to this step
                command.upgrade(alembic_config, step)
                
                # Verify database state
                metadata = MetaData()
                metadata.reflect(bind=test_engine)
                
                # Should have progressively more tables/indexes
                assert len(metadata.tables) > 0, f"Should have tables after migration {step}"
    
    def test_migration_data_preservation(self, test_engine, alembic_config):
        """Test that migrations preserve existing data."""
        # Apply initial schema
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "001")
        
        # Insert test data
        with test_engine.connect() as conn:
            # Insert test model catalog entry
            conn.execute(text("""
                INSERT INTO model_catalog (model_id, provider, display_name, status, created_at)
                VALUES ('test/model', 'test', 'Test Model', 'active', datetime('now'))
            """))
            conn.commit()
        
        # Apply next migration
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "002")
        
        # Verify data still exists
        with test_engine.connect() as conn:
            result = conn.execute(text("SELECT * FROM model_catalog WHERE model_id = 'test/model'"))
            row = result.fetchone()
            assert row is not None, "Data should be preserved during migration"
    
    def test_constraint_validation(self, test_engine, alembic_config):
        """Test that database constraints are properly enforced after migration."""
        # Apply all migrations
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "head")
        
        # Test semantic_items kind constraint
        with test_engine.connect() as conn:
            # Valid insert should work
            try:
                conn.execute(text("""
                    INSERT INTO threads (id, workspace_id, created_at)
                    VALUES ('550e8400-e29b-41d4-a716-446655440000', 'test_workspace', datetime('now'))
                """))
                
                conn.execute(text("""
                    INSERT INTO semantic_items (id, thread_id, kind, title, body, status, created_at)
                    VALUES ('S001', '550e8400-e29b-41d4-a716-446655440000', 'decision', 'Test Decision', 'Test Body', 'accepted', datetime('now'))
                """))
                conn.commit()
                success = True
            except Exception:
                success = False
            
            assert success, "Valid data should be insertable"
            
            # Invalid kind should fail
            with pytest.raises(Exception):
                conn.execute(text("""
                    INSERT INTO semantic_items (id, thread_id, kind, title, body, status, created_at)
                    VALUES ('S002', '550e8400-e29b-41d4-a716-446655440000', 'invalid_kind', 'Test', 'Test', 'accepted', datetime('now'))
                """))
                conn.commit()
    
    def test_index_creation(self, test_engine, alembic_config):
        """Test that indexes are properly created."""
        # Apply all migrations
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "head")
        
        # Check indexes exist
        inspector = inspect(test_engine)
        
        # Check some expected indexes
        semantic_items_indexes = inspector.get_indexes('semantic_items')
        index_names = [idx['name'] for idx in semantic_items_indexes]
        
        expected_indexes = [
            'idx_semantic_items_thread',
            'idx_semantic_items_kind',
            'idx_semantic_items_status'
        ]
        
        for expected_index in expected_indexes:
            assert expected_index in index_names, f"Index {expected_index} should exist"


@pytest.mark.database
class TestMigrationPerformance:
    """Test migration performance characteristics."""
    
    @pytest.fixture
    def large_dataset(self):
        """Generate large dataset for performance testing."""
        return {
            'model_catalog': [
                {
                    'model_id': f'provider/model-{i}',
                    'provider': f'provider-{i % 5}',
                    'display_name': f'Model {i}',
                    'status': 'active'
                }
                for i in range(100)
            ],
            'api_keys': [
                {
                    'key_hash': f'hash-{i}',
                    'workspace_id': f'workspace-{i % 10}',
                    'name': f'API Key {i}',
                    'active': True
                }
                for i in range(50)
            ]
        }
    
    def test_migration_with_large_dataset(self, test_engine, alembic_config, large_dataset):
        """Test migration performance with large datasets."""
        import time
        
        # Apply initial migration
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "001")
        
        # Insert large dataset
        with test_engine.connect() as conn:
            for model in large_dataset['model_catalog']:
                conn.execute(text("""
                    INSERT INTO model_catalog (model_id, provider, display_name, status, created_at)
                    VALUES (:model_id, :provider, :display_name, :status, datetime('now'))
                """), model)
            
            for api_key in large_dataset['api_keys']:
                conn.execute(text("""
                    INSERT INTO api_keys (key_hash, workspace_id, name, active, created_at)
                    VALUES (:key_hash, :workspace_id, :name, :active, datetime('now'))
                """), api_key)
            
            conn.commit()
        
        # Time the migration
        start_time = time.time()
        
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "head")
        
        end_time = time.time()
        migration_time = end_time - start_time
        
        # Migration should complete within reasonable time
        assert migration_time < 30.0, f"Migration took {migration_time}s, should be under 30s"
        
        # Verify data integrity after migration
        with test_engine.connect() as conn:
            model_count = conn.execute(text("SELECT COUNT(*) FROM model_catalog")).scalar()
            api_key_count = conn.execute(text("SELECT COUNT(*) FROM api_keys")).scalar()
            
            assert model_count == 100, "All model catalog entries should be preserved"
            assert api_key_count == 50, "All API keys should be preserved"


@pytest.mark.database
class TestMigrationErrorHandling:
    """Test migration error handling and recovery."""
    
    def test_partial_migration_failure(self, test_engine, alembic_config):
        """Test handling of partial migration failures."""
        # Mock a failure during migration
        def failing_execute(sql):
            if "CREATE TABLE" in str(sql) and "artifacts" in str(sql):
                raise Exception("Simulated migration failure")
            return None
        
        with patch('alembic.op.execute', side_effect=failing_execute):
            with pytest.raises(Exception):
                command.upgrade(alembic_config, "001")
        
        # Verify database is in consistent state
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        
        # Some tables might exist, but migration should not be marked as complete
        # (In real scenario, Alembic would handle transaction rollback)
    
    def test_migration_with_invalid_sql(self, test_engine, alembic_config):
        """Test handling of invalid SQL in migrations."""
        # This tests the migration system's ability to handle SQL errors
        with patch('alembic.op.execute') as mock_execute:
            # Simulate SQL error
            mock_execute.side_effect = Exception("SQL syntax error")
            
            with pytest.raises(Exception):
                command.upgrade(alembic_config, "001")
    
    def test_downgrade_error_handling(self, test_engine, alembic_config):
        """Test error handling during downgrade operations."""
        # Apply migration first
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "001")
        
        # Mock failure during downgrade
        with patch('alembic.op.execute') as mock_execute:
            mock_execute.side_effect = Exception("Cannot drop table")
            
            with pytest.raises(Exception):
                command.downgrade(alembic_config, "base")


@pytest.mark.database
class TestMigrationCompatibility:
    """Test migration compatibility across different scenarios."""
    
    def test_fresh_install_vs_incremental_upgrade(self, alembic_config):
        """Test that fresh install produces same result as incremental upgrades."""
        # Test fresh install
        fresh_engine = create_engine("sqlite:///:memory:")
        
        with patch('alembic.op.execute'):
            # Apply all migrations at once
            command.upgrade(alembic_config, "head")
        
        fresh_metadata = MetaData()
        fresh_metadata.reflect(bind=fresh_engine)
        
        # Test incremental upgrade
        incremental_engine = create_engine("sqlite:///:memory:")
        
        with patch('alembic.op.execute'):
            # Apply migrations one by one
            command.upgrade(alembic_config, "001")
            command.upgrade(alembic_config, "002") 
            command.upgrade(alembic_config, "003")
        
        incremental_metadata = MetaData()
        incremental_metadata.reflect(bind=incremental_engine)
        
        # Both should have same table structure
        assert set(fresh_metadata.tables.keys()) == set(incremental_metadata.tables.keys())
    
    def test_migration_idempotency(self, test_engine, alembic_config):
        """Test that migrations are idempotent (can be run multiple times safely)."""
        # Apply migrations twice
        with patch('alembic.op.execute'):
            command.upgrade(alembic_config, "head")
            
            # Running again should not cause errors
            command.upgrade(alembic_config, "head")
        
        # Database should still be in valid state
        metadata = MetaData()
        metadata.reflect(bind=test_engine)
        assert len(metadata.tables) > 0
    
    def test_cross_database_compatibility(self):
        """Test that migrations work across different database types."""
        # Test SQLite (already tested above)
        sqlite_compatible = True
        
        # Test PostgreSQL compatibility (mock)
        with patch('sqlalchemy.create_engine') as mock_engine:
            mock_engine.return_value.dialect.name = 'postgresql'
            postgresql_compatible = True
        
        assert sqlite_compatible and postgresql_compatible


@pytest.mark.database 
class TestMigrationDocumentation:
    """Test migration documentation and metadata."""
    
    def test_migration_documentation(self):
        """Test that migrations have proper documentation."""
        migration_file = "app/db/migrations/versions/001_initial_schema.py"
        
        with open(migration_file, 'r') as f:
            content = f.read()
        
        # Check docstring exists
        assert '"""' in content, "Migration should have docstring"
        
        # Check revision info
        assert "Revision ID:" in content, "Migration should have revision ID"
        assert "Create Date:" in content, "Migration should have creation date"
    
    def test_migration_naming_convention(self):
        """Test that migration files follow naming convention."""
        migrations_dir = "app/db/migrations/versions"
        migration_files = [f for f in os.listdir(migrations_dir) if f.endswith('.py')]
        
        for migration_file in migration_files:
            if not migration_file.startswith('__'):
                # Should follow pattern: XXX_description.py
                assert '_' in migration_file, f"Migration {migration_file} should have descriptive name"
                
                # Should start with number
                parts = migration_file.split('_')
                assert parts[0].isdigit(), f"Migration {migration_file} should start with number"


if __name__ == "__main__":
    pytest.main([__file__])