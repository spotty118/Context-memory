-- Context Memory Gateway - Supabase Initial Schema Migration
-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Model Catalog Table
CREATE TABLE model_catalog (
    model_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    display_name TEXT,
    context_window INTEGER,
    input_price_per_1k DECIMAL(10,6),
    output_price_per_1k DECIMAL(10,6),
    supports_tools BOOLEAN DEFAULT FALSE,
    supports_vision BOOLEAN DEFAULT FALSE,
    supports_json_mode BOOLEAN DEFAULT FALSE,
    embeddings BOOLEAN DEFAULT FALSE,
    status TEXT DEFAULT 'active' CHECK (status IN ('active','deprecated','unavailable')),
    last_seen_at TIMESTAMPTZ,
    model_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Settings Table
CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- API Keys Table
CREATE TABLE api_keys (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    key_hash TEXT UNIQUE NOT NULL,
    key_name TEXT NOT NULL,
    description TEXT,
    workspace_id TEXT NOT NULL DEFAULT 'default',
    is_active BOOLEAN DEFAULT TRUE,
    daily_quota_tokens INTEGER,
    rpm_limit INTEGER,
    model_allowlist TEXT[],
    model_blocklist TEXT[],
    default_model TEXT,
    default_embed_model TEXT,
    created_by TEXT DEFAULT 'admin',
    last_used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Usage Ledger Table
CREATE TABLE usage_ledger (
    id BIGSERIAL PRIMARY KEY,
    api_key_hash TEXT REFERENCES api_keys(key_hash) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    request_tokens INTEGER DEFAULT 0,
    response_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER GENERATED ALWAYS AS (request_tokens + response_tokens) STORED,
    cost_usd DECIMAL(12,8),
    latency_ms INTEGER,
    request_timestamp TIMESTAMPTZ DEFAULT NOW(),
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT,
    request_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Contexts Table
CREATE TABLE contexts (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    context_name TEXT NOT NULL,
    description TEXT,
    metadata JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Context Items Table  
CREATE TABLE context_items (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    context_id UUID REFERENCES contexts(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    metadata JSONB DEFAULT '{}',
    chunk_index INTEGER DEFAULT 0,
    total_chunks INTEGER DEFAULT 1,
    token_count INTEGER,
    embedding VECTOR(1536),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Embeddings Table
CREATE TABLE embeddings (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    item_type TEXT NOT NULL,
    item_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    model_id TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    content_hash TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(item_type, item_id, model_id)
);

-- Users Table
CREATE TABLE users (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    is_admin BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}',
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Threads Table
CREATE TABLE threads (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    title TEXT,
    metadata JSONB DEFAULT '{}',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Feedback Table
CREATE TABLE feedback (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    request_id TEXT,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    feedback_text TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Working Sets Table
CREATE TABLE working_sets (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    context_items UUID[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_by TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cache Entries Table
CREATE TABLE cache_entries (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    cache_key TEXT UNIQUE NOT NULL,
    workspace_id TEXT NOT NULL,
    data JSONB NOT NULL,
    expires_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_model_catalog_provider ON model_catalog(provider);
CREATE INDEX idx_model_catalog_status ON model_catalog(status);
CREATE INDEX idx_model_catalog_embeddings ON model_catalog(embeddings);

CREATE INDEX idx_api_keys_workspace ON api_keys(workspace_id);
CREATE INDEX idx_api_keys_active ON api_keys(is_active);
CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);

CREATE INDEX idx_usage_ledger_api_key ON usage_ledger(api_key_hash);
CREATE INDEX idx_usage_ledger_workspace ON usage_ledger(workspace_id);
CREATE INDEX idx_usage_ledger_model ON usage_ledger(model_id);
CREATE INDEX idx_usage_ledger_timestamp ON usage_ledger(request_timestamp);
CREATE INDEX idx_usage_ledger_endpoint ON usage_ledger(endpoint);

CREATE INDEX idx_contexts_workspace ON contexts(workspace_id);
CREATE INDEX idx_contexts_active ON contexts(is_active);

CREATE INDEX idx_context_items_context ON context_items(context_id);
CREATE INDEX idx_context_items_workspace ON context_items(workspace_id);
CREATE INDEX idx_context_items_embedding ON context_items USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX idx_embeddings_item ON embeddings(item_type, item_id);
CREATE INDEX idx_embeddings_workspace ON embeddings(workspace_id);
CREATE INDEX idx_embeddings_model ON embeddings(model_id);
CREATE INDEX idx_embeddings_vector ON embeddings USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active);

CREATE INDEX idx_threads_workspace ON threads(workspace_id);

CREATE INDEX idx_feedback_workspace ON feedback(workspace_id);
CREATE INDEX idx_feedback_request ON feedback(request_id);

CREATE INDEX idx_working_sets_workspace ON working_sets(workspace_id);

CREATE INDEX idx_cache_entries_key ON cache_entries(cache_key);
CREATE INDEX idx_cache_entries_workspace ON cache_entries(workspace_id);
CREATE INDEX idx_cache_entries_expires ON cache_entries(expires_at);

-- Enable Row Level Security
ALTER TABLE model_catalog ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE context_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE working_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE cache_entries ENABLE ROW LEVEL SECURITY;

-- Create policies (basic - can be refined later)
-- Service role can access everything, authenticated users limited access

-- Model catalog - public read access
CREATE POLICY "Allow public read access on model_catalog" ON model_catalog FOR SELECT USING (true);
CREATE POLICY "Allow service role full access on model_catalog" ON model_catalog FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Settings - admin only
CREATE POLICY "Allow service role full access on settings" ON settings FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- API Keys - service role only
CREATE POLICY "Allow service role full access on api_keys" ON api_keys FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Usage ledger - service role only
CREATE POLICY "Allow service role full access on usage_ledger" ON usage_ledger FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Contexts - workspace-based access
CREATE POLICY "Allow service role full access on contexts" ON contexts FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Context items - workspace-based access
CREATE POLICY "Allow service role full access on context_items" ON context_items FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Embeddings - service role only
CREATE POLICY "Allow service role full access on embeddings" ON embeddings FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Users - service role only
CREATE POLICY "Allow service role full access on users" ON users FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Threads - workspace-based access
CREATE POLICY "Allow service role full access on threads" ON threads FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Feedback - workspace-based access
CREATE POLICY "Allow service role full access on feedback" ON feedback FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Working sets - workspace-based access
CREATE POLICY "Allow service role full access on working_sets" ON working_sets FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Cache entries - service role only
CREATE POLICY "Allow service role full access on cache_entries" ON cache_entries FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Create updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Add updated_at triggers
CREATE TRIGGER update_model_catalog_updated_at BEFORE UPDATE ON model_catalog FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_settings_updated_at BEFORE UPDATE ON settings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_api_keys_updated_at BEFORE UPDATE ON api_keys FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_contexts_updated_at BEFORE UPDATE ON contexts FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_context_items_updated_at BEFORE UPDATE ON context_items FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_threads_updated_at BEFORE UPDATE ON threads FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER update_working_sets_updated_at BEFORE UPDATE ON working_sets FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
