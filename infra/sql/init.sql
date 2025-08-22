-- Context Memory Gateway - PostgreSQL Initialization Script
-- This script sets up the database with required extensions and initial configuration

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Create additional schemas if needed
CREATE SCHEMA IF NOT EXISTS context_memory;
CREATE SCHEMA IF NOT EXISTS analytics;

-- Set default permissions
GRANT USAGE ON SCHEMA public TO cmg_user;
GRANT USAGE ON SCHEMA context_memory TO cmg_user;
GRANT USAGE ON SCHEMA analytics TO cmg_user;

GRANT CREATE ON SCHEMA public TO cmg_user;
GRANT CREATE ON SCHEMA context_memory TO cmg_user;
GRANT CREATE ON SCHEMA analytics TO cmg_user;

-- Create indexes for better performance (will be created by migrations, but good to have)
-- These will be created by Alembic migrations, but we can prepare the database

-- Set timezone
SET timezone = 'UTC';

-- Configure logging
SET log_statement = 'all';
SET log_min_duration_statement = 1000; -- Log queries taking more than 1 second

-- Performance tuning for development
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';
ALTER SYSTEM SET track_activity_query_size = 2048;
ALTER SYSTEM SET track_io_timing = on;

-- Reload configuration
SELECT pg_reload_conf();

