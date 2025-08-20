"""Seed initial data

Revision ID: 002
Revises: 001
Create Date: 2025-01-20 12:01:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
from sqlalchemy import String, JSON, Text, Integer, Numeric, Boolean, DateTime
from datetime import datetime

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Define table structures for bulk insert
    settings_table = table('settings',
        column('key', String),
        column('value', JSON),
        column('created_at', DateTime),
        column('updated_at', DateTime)
    )
    
    model_catalog_table = table('model_catalog',
        column('model_id', Text),
        column('provider', Text),
        column('display_name', Text),
        column('context_window', Integer),
        column('input_price_per_1k', Numeric),
        column('output_price_per_1k', Numeric),
        column('supports_tools', Boolean),
        column('supports_vision', Boolean),
        column('supports_json_mode', Boolean),
        column('embeddings', Boolean),
        column('status', Text),
        column('last_seen_at', DateTime),
        column('created_at', DateTime),
        column('updated_at', DateTime)
    )
    
    now = datetime.utcnow()
    
    # Insert global settings
    op.bulk_insert(settings_table, [
        {
            'key': 'global_default_model',
            'value': {'model_id': 'openai/gpt-4o-mini'},
            'created_at': now,
            'updated_at': now
        },
        {
            'key': 'global_embed_model',
            'value': {'model_id': 'openai/text-embedding-3-large'},
            'created_at': now,
            'updated_at': now
        },
        {
            'key': 'model_allowlist_global',
            'value': [
                'openai/gpt-4o-mini',
                'openai/gpt-4o',
                'anthropic/claude-3.5-sonnet',
                'anthropic/claude-3.5-haiku',
                'google/gemini-1.5-pro',
                'google/gemini-1.5-flash',
                'meta-llama/llama-3.1-405b-instruct',
                'meta-llama/llama-3.1-70b-instruct',
                'meta-llama/llama-3.1-8b-instruct',
                'cohere/command-r-plus',
                'qwen/qwen-2.5-72b-instruct',
                'mistralai/mistral-large-2',
                'openai/text-embedding-3-large',
                'openai/text-embedding-3-small'
            ],
            'created_at': now,
            'updated_at': now
        },
        {
            'key': 'model_blocklist_global',
            'value': [],
            'created_at': now,
            'updated_at': now
        }
    ])
    
    # Insert initial model catalog (August 2025 snapshot)
    op.bulk_insert(model_catalog_table, [
        # OpenAI Models
        {
            'model_id': 'openai/gpt-4o-mini',
            'provider': 'openai',
            'display_name': 'GPT-4o Mini',
            'context_window': 128000,
            'input_price_per_1k': 0.000150,
            'output_price_per_1k': 0.000600,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'openai/gpt-4o',
            'provider': 'openai',
            'display_name': 'GPT-4o',
            'context_window': 128000,
            'input_price_per_1k': 0.005000,
            'output_price_per_1k': 0.015000,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'openai/text-embedding-3-large',
            'provider': 'openai',
            'display_name': 'Text Embedding 3 Large',
            'context_window': 8192,
            'input_price_per_1k': 0.000130,
            'output_price_per_1k': 0.000000,
            'supports_tools': False,
            'supports_vision': False,
            'supports_json_mode': False,
            'embeddings': True,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'openai/text-embedding-3-small',
            'provider': 'openai',
            'display_name': 'Text Embedding 3 Small',
            'context_window': 8192,
            'input_price_per_1k': 0.000020,
            'output_price_per_1k': 0.000000,
            'supports_tools': False,
            'supports_vision': False,
            'supports_json_mode': False,
            'embeddings': True,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Anthropic Models
        {
            'model_id': 'anthropic/claude-3.5-sonnet',
            'provider': 'anthropic',
            'display_name': 'Claude 3.5 Sonnet',
            'context_window': 200000,
            'input_price_per_1k': 0.003000,
            'output_price_per_1k': 0.015000,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': False,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'anthropic/claude-3.5-haiku',
            'provider': 'anthropic',
            'display_name': 'Claude 3.5 Haiku',
            'context_window': 200000,
            'input_price_per_1k': 0.000800,
            'output_price_per_1k': 0.004000,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': False,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Google Models
        {
            'model_id': 'google/gemini-1.5-pro',
            'provider': 'google',
            'display_name': 'Gemini 1.5 Pro',
            'context_window': 2000000,
            'input_price_per_1k': 0.001250,
            'output_price_per_1k': 0.005000,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'google/gemini-1.5-flash',
            'provider': 'google',
            'display_name': 'Gemini 1.5 Flash',
            'context_window': 1000000,
            'input_price_per_1k': 0.000075,
            'output_price_per_1k': 0.000300,
            'supports_tools': True,
            'supports_vision': True,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Meta Llama Models
        {
            'model_id': 'meta-llama/llama-3.1-405b-instruct',
            'provider': 'meta-llama',
            'display_name': 'Llama 3.1 405B Instruct',
            'context_window': 131072,
            'input_price_per_1k': 0.002700,
            'output_price_per_1k': 0.002700,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'meta-llama/llama-3.1-70b-instruct',
            'provider': 'meta-llama',
            'display_name': 'Llama 3.1 70B Instruct',
            'context_window': 131072,
            'input_price_per_1k': 0.000520,
            'output_price_per_1k': 0.000520,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        {
            'model_id': 'meta-llama/llama-3.1-8b-instruct',
            'provider': 'meta-llama',
            'display_name': 'Llama 3.1 8B Instruct',
            'context_window': 131072,
            'input_price_per_1k': 0.000055,
            'output_price_per_1k': 0.000055,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Cohere Models
        {
            'model_id': 'cohere/command-r-plus',
            'provider': 'cohere',
            'display_name': 'Command R+',
            'context_window': 128000,
            'input_price_per_1k': 0.002500,
            'output_price_per_1k': 0.010000,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Qwen Models
        {
            'model_id': 'qwen/qwen-2.5-72b-instruct',
            'provider': 'qwen',
            'display_name': 'Qwen 2.5 72B Instruct',
            'context_window': 131072,
            'input_price_per_1k': 0.000560,
            'output_price_per_1k': 0.000560,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        },
        
        # Mistral Models
        {
            'model_id': 'mistralai/mistral-large-2',
            'provider': 'mistralai',
            'display_name': 'Mistral Large 2',
            'context_window': 131072,
            'input_price_per_1k': 0.002000,
            'output_price_per_1k': 0.006000,
            'supports_tools': True,
            'supports_vision': False,
            'supports_json_mode': True,
            'embeddings': False,
            'status': 'active',
            'last_seen_at': now,
            'created_at': now,
            'updated_at': now
        }
    ])


def downgrade() -> None:
    # Remove seed data
    op.execute("DELETE FROM model_catalog WHERE model_id IN ('openai/gpt-4o-mini', 'openai/gpt-4o', 'openai/text-embedding-3-large', 'openai/text-embedding-3-small', 'anthropic/claude-3.5-sonnet', 'anthropic/claude-3.5-haiku', 'google/gemini-1.5-pro', 'google/gemini-1.5-flash', 'meta-llama/llama-3.1-405b-instruct', 'meta-llama/llama-3.1-70b-instruct', 'meta-llama/llama-3.1-8b-instruct', 'cohere/command-r-plus', 'qwen/qwen-2.5-72b-instruct', 'mistralai/mistral-large-2')")
    op.execute("DELETE FROM settings WHERE key IN ('global_default_model', 'global_embed_model', 'model_allowlist_global', 'model_blocklist_global')")

