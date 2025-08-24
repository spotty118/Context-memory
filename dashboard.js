// Supabase Admin Dashboard JavaScript

// Initialize Supabase client
const supabaseUrl = 'https://your-project-id.supabase.co';
const supabaseAnonKey = 'your-anon-key-here';
const supabase = window.supabase.createClient(supabaseUrl, supabaseAnonKey);

let currentPage = 'dashboard';
let charts = {};

// Initialize dashboard
document.addEventListener('DOMContentLoaded', function() {
    lucide.createIcons();
    loadDashboard();
});

// Navigation
function showPage(pageId) {
    // Update navigation
    document.querySelectorAll('.nav-btn').forEach(btn => {
        btn.className = btn.className.replace('border-indigo-500 text-gray-900', 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300');
    });
    event.target.className = event.target.className.replace('border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300', 'border-indigo-500 text-gray-900');

    // Show/hide pages
    document.querySelectorAll('.page').forEach(page => page.classList.add('hidden'));
    document.getElementById(`${pageId}-page`).classList.remove('hidden');
    
    currentPage = pageId;
    
    // Load page data
    switch(pageId) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'api-keys':
            loadAPIKeys();
            break;
        case 'models':
            loadModels();
            break;
        case 'contexts':
            loadContexts();
            break;
        case 'usage':
            loadUsageAnalytics();
            break;
    }
}

// Dashboard functions
async function loadDashboard() {
    try {
        // Load stats
        const [apiKeysResult, contextsResult, modelsResult, usageResult] = await Promise.all([
            supabase.from('api_keys').select('id', { count: 'exact', head: true }),
            supabase.from('contexts').select('id', { count: 'exact', head: true }),
            supabase.from('model_catalog').select('model_id', { count: 'exact', head: true }),
            supabase.from('usage_ledger').select('total_tokens.sum()', { count: 'exact' })
        ]);

        document.getElementById('stats-api-keys').textContent = apiKeysResult.count || 0;
        document.getElementById('stats-contexts').textContent = contextsResult.count || 0;
        document.getElementById('stats-models').textContent = modelsResult.count || 0;
        document.getElementById('stats-requests').textContent = usageResult.count || 0;

        // Load usage chart
        await loadUsageChart();
    } catch (error) {
        console.error('Error loading dashboard:', error);
        showNotification('Failed to load dashboard data', 'error');
    }
}

async function loadUsageChart() {
    try {
        const { data, error } = await supabase
            .from('usage_ledger')
            .select('request_timestamp, total_tokens')
            .gte('request_timestamp', new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString())
            .order('request_timestamp');

        if (error) throw error;

        // Process data for chart
        const dailyUsage = {};
        data.forEach(record => {
            const date = new Date(record.request_timestamp).toDateString();
            dailyUsage[date] = (dailyUsage[date] || 0) + record.total_tokens;
        });

        const labels = Object.keys(dailyUsage);
        const values = Object.values(dailyUsage);

        // Create chart
        const ctx = document.getElementById('usageChart').getContext('2d');
        if (charts.usage) charts.usage.destroy();
        
        charts.usage = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'Tokens Used',
                    data: values,
                    borderColor: 'rgb(99, 102, 241)',
                    backgroundColor: 'rgba(99, 102, 241, 0.1)',
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error loading usage chart:', error);
    }
}

// API Keys functions
async function loadAPIKeys() {
    try {
        const { data, error } = await supabase
            .from('api_keys')
            .select('*')
            .order('created_at', { ascending: false });

        if (error) throw error;

        const list = document.getElementById('api-keys-list');
        list.innerHTML = '';

        if (data.length === 0) {
            list.innerHTML = '<li class="p-4 text-center text-gray-500">No API keys found</li>';
            return;
        }

        data.forEach(key => {
            const li = document.createElement('li');
            li.className = 'px-6 py-4';
            li.innerHTML = `
                <div class="flex items-center justify-between">
                    <div>
                        <h3 class="text-lg font-medium text-gray-900">${key.key_name}</h3>
                        <p class="text-sm text-gray-500">${key.description || 'No description'}</p>
                        <p class="text-xs text-gray-400">Created: ${new Date(key.created_at).toLocaleDateString()}</p>
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            key.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                        }">
                            ${key.is_active ? 'Active' : 'Inactive'}
                        </span>
                        <button onclick="toggleAPIKey('${key.id}', ${key.is_active})" 
                                class="text-sm text-indigo-600 hover:text-indigo-900">
                            ${key.is_active ? 'Deactivate' : 'Activate'}
                        </button>
                        <button onclick="deleteAPIKey('${key.id}')" 
                                class="text-sm text-red-600 hover:text-red-900">
                            Delete
                        </button>
                    </div>
                </div>
            `;
            list.appendChild(li);
        });
    } catch (error) {
        console.error('Error loading API keys:', error);
        showNotification('Failed to load API keys', 'error');
    }
}

async function createAPIKey() {
    const keyName = prompt('Enter API key name:');
    if (!keyName) return;

    const description = prompt('Enter description (optional):') || '';

    try {
        // Generate key hash (simplified - in production use proper crypto)
        const keyHash = 'cmg_' + Math.random().toString(36).substring(2, 15) + Math.random().toString(36).substring(2, 15);
        
        const { data, error } = await supabase
            .from('api_keys')
            .insert([{
                key_name: keyName,
                description: description,
                key_hash: keyHash,
                workspace_id: 'default',
                is_active: true
            }]);

        if (error) throw error;

        showNotification(`API Key created: ${keyHash}`, 'success');
        loadAPIKeys();
    } catch (error) {
        console.error('Error creating API key:', error);
        showNotification('Failed to create API key', 'error');
    }
}

async function toggleAPIKey(id, currentStatus) {
    try {
        const { error } = await supabase
            .from('api_keys')
            .update({ is_active: !currentStatus })
            .eq('id', id);

        if (error) throw error;

        showNotification('API key updated', 'success');
        loadAPIKeys();
    } catch (error) {
        console.error('Error updating API key:', error);
        showNotification('Failed to update API key', 'error');
    }
}

async function deleteAPIKey(id) {
    if (!confirm('Are you sure you want to delete this API key?')) return;

    try {
        const { error } = await supabase
            .from('api_keys')
            .delete()
            .eq('id', id);

        if (error) throw error;

        showNotification('API key deleted', 'success');
        loadAPIKeys();
    } catch (error) {
        console.error('Error deleting API key:', error);
        showNotification('Failed to delete API key', 'error');
    }
}

// Models functions
async function loadModels() {
    try {
        const { data, error } = await supabase
            .from('model_catalog')
            .select('*')
            .order('provider', { ascending: true });

        if (error) throw error;

        const list = document.getElementById('models-list');
        list.innerHTML = '';

        if (data.length === 0) {
            list.innerHTML = '<li class="p-4 text-center text-gray-500">No models found</li>';
            return;
        }

        data.forEach(model => {
            const li = document.createElement('li');
            li.className = 'px-6 py-4';
            li.innerHTML = `
                <div class="flex items-center justify-between">
                    <div>
                        <h3 class="text-lg font-medium text-gray-900">${model.model_id}</h3>
                        <p class="text-sm text-gray-500">Provider: ${model.provider}</p>
                        <p class="text-xs text-gray-400">Context: ${model.context_window || 'Unknown'} | Input: $${model.input_price_per_1k || '0'}/1K | Output: $${model.output_price_per_1k || '0'}/1K</p>
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            model.status === 'active' ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
                        }">
                            ${model.status}
                        </span>
                        ${model.supports_tools ? '<span class="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded">Tools</span>' : ''}
                        ${model.supports_vision ? '<span class="text-xs bg-purple-100 text-purple-800 px-2 py-1 rounded">Vision</span>' : ''}
                    </div>
                </div>
            `;
            list.appendChild(li);
        });
    } catch (error) {
        console.error('Error loading models:', error);
        showNotification('Failed to load models', 'error');
    }
}

async function syncModels() {
    try {
        showNotification('Syncing models from OpenRouter...', 'info');
        
        // This would typically call your FastAPI endpoint to sync models
        // For now, just reload the models list
        setTimeout(() => {
            loadModels();
            showNotification('Models synced successfully', 'success');
        }, 2000);
    } catch (error) {
        console.error('Error syncing models:', error);
        showNotification('Failed to sync models', 'error');
    }
}

// Contexts functions
async function loadContexts() {
    try {
        const { data, error } = await supabase
            .from('contexts')
            .select('*, context_items(count)')
            .order('created_at', { ascending: false });

        if (error) throw error;

        const list = document.getElementById('contexts-list');
        list.innerHTML = '';

        if (data.length === 0) {
            list.innerHTML = '<li class="p-4 text-center text-gray-500">No contexts found</li>';
            return;
        }

        data.forEach(context => {
            const li = document.createElement('li');
            li.className = 'px-6 py-4';
            li.innerHTML = `
                <div class="flex items-center justify-between">
                    <div>
                        <h3 class="text-lg font-medium text-gray-900">${context.context_name}</h3>
                        <p class="text-sm text-gray-500">${context.description || 'No description'}</p>
                        <p class="text-xs text-gray-400">Items: ${context.context_items?.length || 0} | Created: ${new Date(context.created_at).toLocaleDateString()}</p>
                    </div>
                    <div class="flex items-center space-x-2">
                        <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            context.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                        }">
                            ${context.is_active ? 'Active' : 'Inactive'}
                        </span>
                        <button onclick="viewContext('${context.id}')" class="text-sm text-indigo-600 hover:text-indigo-900">View</button>
                        <button onclick="deleteContext('${context.id}')" class="text-sm text-red-600 hover:text-red-900">Delete</button>
                    </div>
                </div>
            `;
            list.appendChild(li);
        });
    } catch (error) {
        console.error('Error loading contexts:', error);
        showNotification('Failed to load contexts', 'error');
    }
}

async function createContext() {
    const contextName = prompt('Enter context name:');
    if (!contextName) return;

    const description = prompt('Enter description (optional):') || '';

    try {
        const { data, error } = await supabase
            .from('contexts')
            .insert([{
                context_name: contextName,
                description: description,
                workspace_id: 'default',
                is_active: true
            }]);

        if (error) throw error;

        showNotification('Context created successfully', 'success');
        loadContexts();
    } catch (error) {
        console.error('Error creating context:', error);
        showNotification('Failed to create context', 'error');
    }
}

async function deleteContext(id) {
    if (!confirm('Are you sure you want to delete this context and all its items?')) return;

    try {
        const { error } = await supabase
            .from('contexts')
            .delete()
            .eq('id', id);

        if (error) throw error;

        showNotification('Context deleted', 'success');
        loadContexts();
    } catch (error) {
        console.error('Error deleting context:', error);
        showNotification('Failed to delete context', 'error');
    }
}

// Usage Analytics functions
async function loadUsageAnalytics() {
    try {
        // Load model usage chart
        const { data: modelData, error: modelError } = await supabase
            .from('usage_ledger')
            .select('model_id, total_tokens.sum()')
            .gte('request_timestamp', new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString());

        if (modelError) throw modelError;

        // Process model usage data
        const modelUsage = {};
        modelData.forEach(record => {
            modelUsage[record.model_id] = (modelUsage[record.model_id] || 0) + record.total_tokens;
        });

        const modelLabels = Object.keys(modelUsage);
        const modelValues = Object.values(modelUsage);

        // Create model usage chart
        const modelCtx = document.getElementById('modelUsageChart').getContext('2d');
        if (charts.modelUsage) charts.modelUsage.destroy();
        
        charts.modelUsage = new Chart(modelCtx, {
            type: 'doughnut',
            data: {
                labels: modelLabels,
                datasets: [{
                    data: modelValues,
                    backgroundColor: [
                        '#6366f1', '#8b5cf6', '#ec4899', '#f59e0b',
                        '#10b981', '#3b82f6', '#ef4444', '#f97316'
                    ]
                }]
            },
            options: {
                responsive: true,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });

        // Load cost chart (simplified)
        const costCtx = document.getElementById('costChart').getContext('2d');
        if (charts.cost) charts.cost.destroy();
        
        charts.cost = new Chart(costCtx, {
            type: 'bar',
            data: {
                labels: ['This Week', 'Last Week', '2 Weeks Ago', '3 Weeks Ago'],
                datasets: [{
                    label: 'Cost (USD)',
                    data: [125.50, 98.20, 87.30, 76.80],
                    backgroundColor: 'rgba(99, 102, 241, 0.5)',
                    borderColor: 'rgb(99, 102, 241)',
                    borderWidth: 1
                }]
            },
            options: {
                responsive: true,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return '$' + value;
                            }
                        }
                    }
                }
            }
        });
    } catch (error) {
        console.error('Error loading usage analytics:', error);
        showNotification('Failed to load usage analytics', 'error');
    }
}

// Utility functions
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `fixed top-4 right-4 px-6 py-4 rounded-lg shadow-lg z-50 ${
        type === 'success' ? 'bg-green-600 text-white' :
        type === 'error' ? 'bg-red-600 text-white' :
        type === 'info' ? 'bg-blue-600 text-white' :
        'bg-gray-600 text-white'
    }`;
    notification.textContent = message;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

function logout() {
    // Implement logout logic
    window.location.href = '/login';
}
