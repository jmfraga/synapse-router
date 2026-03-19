const API = '';

// --- Cached data ---
let cachedModels = [];          // flat list of all model names
let cachedModelsTyped = [];     // [{name, type}]
let cachedByProvider = [];      // [{provider, display_name, configured, models, models_typed, all_models_typed}]
let cachedProviders = [];       // from /api/providers

// --- Model type config ---
const MODEL_TYPE_LABELS = {
    language: 'LLM',
    image: 'Imagen',
    tts: 'TTS',
    audio: 'Audio',
    embedding: 'Embedding',
    moderation: 'Moderación',
    rerank: 'Rerank',
};
const MODEL_TYPE_COLORS = {
    language: '#4ecdc4',
    image: '#ff6b6b',
    tts: '#ffd93d',
    audio: '#6c5ce7',
    embedding: '#a29bfe',
    moderation: '#fd79a8',
    rerank: '#81ecec',
};

// --- Generic API helper ---
async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin' };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
    if (res.status === 401) {
        location.reload(); // Force browser to re-prompt for credentials
        return {};
    }
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = err.detail || `Error ${res.status}: ${res.statusText}`;
        alert(msg);
        throw new Error(msg);
    }
    return res.json();
}

// --- Multi-select checkbox component ---
function createMultiSelect(containerId, options, opts = {}) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const allValue = opts.allValue || '*';
    const allLabel = opts.allLabel || '* (todos)';
    const grouped = opts.grouped || false;

    container.classList.add('multi-select');
    container.innerHTML = '';

    // Display area
    const display = document.createElement('div');
    display.className = 'ms-display';
    display.textContent = allLabel;
    container.appendChild(display);

    // Dropdown
    const dropdown = document.createElement('div');
    dropdown.className = 'ms-dropdown';

    // "All" option
    const allItem = document.createElement('label');
    allItem.className = 'ms-item';
    allItem.innerHTML = `<input type="checkbox" value="${allValue}" checked /> ${allLabel}`;
    dropdown.appendChild(allItem);

    const allCheckbox = allItem.querySelector('input');

    if (grouped && opts.providerData) {
        for (const pg of opts.providerData) {
            if (pg.models.length === 0) continue;
            const header = document.createElement('div');
            header.className = 'ms-group-header';
            const status = pg.configured ? '' : ' (sin key)';
            header.textContent = `${pg.display_name}${status}`;
            dropdown.appendChild(header);

            for (const m of pg.models) {
                const item = document.createElement('label');
                item.className = 'ms-item';
                item.innerHTML = `<input type="checkbox" value="${m}" /> ${m}`;
                if (!pg.configured) item.classList.add('ms-disabled');
                dropdown.appendChild(item);
            }
        }
    } else {
        for (const m of options) {
            const item = document.createElement('label');
            item.className = 'ms-item';
            item.innerHTML = `<input type="checkbox" value="${m}" /> ${m}`;
            dropdown.appendChild(item);
        }
    }

    container.appendChild(dropdown);

    // Toggle dropdown
    display.addEventListener('click', (e) => {
        e.stopPropagation();
        container.classList.toggle('open');
    });

    // Handle "all" checkbox
    allCheckbox.addEventListener('change', () => {
        if (allCheckbox.checked) {
            dropdown.querySelectorAll('input:not([value="' + allValue + '"])').forEach(cb => {
                cb.checked = false;
            });
        }
        updateDisplay();
    });

    // Handle individual checkboxes
    dropdown.addEventListener('change', (e) => {
        if (e.target === allCheckbox) return;
        if (e.target.type !== 'checkbox') return;

        if (e.target.checked) {
            allCheckbox.checked = false;
        }

        // If nothing selected, re-check all
        const anyChecked = dropdown.querySelectorAll('input:checked:not([value="' + allValue + '"])').length > 0;
        if (!anyChecked) allCheckbox.checked = true;

        updateDisplay();
    });

    function updateDisplay() {
        if (allCheckbox.checked) {
            display.textContent = allLabel;
            return;
        }
        const selected = [];
        dropdown.querySelectorAll('input:checked:not([value="' + allValue + '"])').forEach(cb => {
            selected.push(cb.value);
        });
        display.textContent = selected.length > 2
            ? `${selected.length} modelos seleccionados`
            : selected.join(', ') || allLabel;
    }

    // Close on outside click
    document.addEventListener('click', () => container.classList.remove('open'));
    container.addEventListener('click', (e) => e.stopPropagation());

    // Method to get value
    container.getValue = () => {
        if (allCheckbox.checked) return allValue;
        const selected = [];
        dropdown.querySelectorAll('input:checked:not([value="' + allValue + '"])').forEach(cb => {
            selected.push(cb.value);
        });
        return selected.join(',') || allValue;
    };
}

// --- Populate selects with optgroups by provider ---
function populateModelSelect(selectId, byProvider, flat, filterType) {
    const el = document.getElementById(selectId);
    if (!el) return;

    // Keep the first default option
    while (el.options.length > 1) el.remove(1);

    if (byProvider && byProvider.length > 0) {
        for (const pg of byProvider) {
            // Use typed models if available and filter requested
            let models = pg.models;
            if (filterType && pg.models_typed) {
                models = pg.models_typed
                    .filter(m => m.type === filterType)
                    .map(m => m.name);
            }
            if (models.length === 0) continue;
            const group = document.createElement('optgroup');
            const status = pg.configured ? '' : ' (sin key)';
            group.label = `${pg.display_name}${status}`;
            for (const m of models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                if (!pg.configured) opt.disabled = true;
                group.appendChild(opt);
            }
            el.appendChild(group);
        }
    } else {
        const filteredFlat = filterType
            ? flat.filter(m => getModelType(m) === filterType)
            : flat;
        for (const m of filteredFlat) {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            el.appendChild(opt);
        }
    }
}

// Get model type from cached typed data
function getModelType(modelName) {
    const found = cachedModelsTyped.find(m => m.name === modelName);
    return found ? found.type : 'language';
}

// Get type badge HTML for a model
function modelTypeBadge(type) {
    if (type === 'language') return '';  // don't badge the default
    const label = MODEL_TYPE_LABELS[type] || type;
    const color = MODEL_TYPE_COLORS[type] || '#888';
    return `<span class="model-type-badge" style="background:${color}20;color:${color};border:1px solid ${color}40;padding:0 4px;border-radius:3px;font-size:0.7rem;margin-left:4px">${label}</span>`;
}

// --- Init: populate all dropdowns on page load ---
async function initDropdowns() {
    const [modelsData, servicesData, providersData] = await Promise.all([
        api('/admin/api/models'),
        api('/admin/api/services'),
        api('/admin/api/providers'),
    ]);

    cachedModels = modelsData.models || [];
    cachedModelsTyped = modelsData.models_typed || [];
    cachedByProvider = modelsData.by_provider || [];
    cachedProviders = providersData || [];

    // Populate model selects with optgroups (language-only for routes/playground)
    populateModelSelect('route-pattern-select', cachedByProvider, cachedModels, 'language');
    populateModelSelect('pg-model', cachedByProvider, cachedModels, 'language');

    // Multi-select for API key allowed models
    createMultiSelect('key-models-ms', cachedModels, {
        allValue: '*',
        allLabel: '* (todos)',
        grouped: true,
        providerData: cachedByProvider,
    });

    // Fetch smart routes for the multi-select
    const smartRoutesData = await api('/admin/api/smart-routes');
    window._smartRoutes = smartRoutesData || [];
    const srOptions = window._smartRoutes.filter(sr => sr.is_enabled).map(sr => sr.name);
    createMultiSelect('key-smart-routes-ms', srOptions, {
        allValue: '__none__',
        allLabel: '(ninguna)',
    });

    // Load keys table from API
    loadKeysTable();

    // Populate service select (insert before the "Nuevo" option)
    const serviceSelect = document.getElementById('key-service-select');
    if (serviceSelect) {
        const newOpt = serviceSelect.querySelector('option[value="__new__"]');
        const services = servicesData.services || [];
        for (const s of services) {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            serviceSelect.insertBefore(opt, newOpt);
        }

        // Show text input when "+ Nuevo servicio..." is selected
        const serviceInput = document.getElementById('key-service-input');
        serviceSelect.addEventListener('change', () => {
            if (serviceSelect.value === '__new__') {
                serviceInput.style.display = '';
                serviceInput.focus();
            } else {
                serviceInput.style.display = 'none';
                serviceInput.value = '';
            }
        });
    }

    // Populate chain-model selects in route builder
    populateChainModelSelects();

    // Render provider configuration cards
    renderProviderConfigCards();

    // Render key expiry alerts
    renderKeyExpiryAlerts();
}

function populateChainModelSelects() {
    document.querySelectorAll('.chain-model').forEach(sel => {
        const current = sel.value;
        while (sel.options.length > 1) sel.remove(1);

        if (cachedByProvider.length > 0) {
            for (const pg of cachedByProvider) {
                // Only show language models in chain selects
                let models = pg.models;
                if (pg.models_typed) {
                    models = pg.models_typed
                        .filter(m => m.type === 'language')
                        .map(m => m.name);
                }
                if (models.length === 0) continue;
                const group = document.createElement('optgroup');
                group.label = pg.display_name;
                for (const m of models) {
                    const opt = document.createElement('option');
                    opt.value = m;
                    opt.textContent = m;
                    group.appendChild(opt);
                }
                sel.appendChild(group);
            }
        } else {
            for (const m of cachedModels) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                sel.appendChild(opt);
            }
        }

        if (current) sel.value = current;
    });
}

// --- Providers ---
async function toggleProvider(id, enable) {
    await api(`/admin/api/providers/${id}`, 'PUT', { is_enabled: enable });
    location.reload();
}

// --- New Provider ---
function showNewProviderForm() {
    const form = document.getElementById('new-provider-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function createProvider() {
    const name = document.getElementById('np-name').value.trim().toLowerCase().replace(/\s+/g, '-');
    const displayName = document.getElementById('np-display').value.trim();
    const baseUrl = document.getElementById('np-base-url').value.trim();
    const priority = parseInt(document.getElementById('np-priority').value) || 10;
    const isLocal = document.getElementById('np-local').value === 'true';

    if (!name || !displayName) {
        alert('Nombre interno y nombre para mostrar son requeridos');
        return;
    }

    await api('/admin/api/providers', 'POST', {
        name, display_name: displayName, base_url: baseUrl,
        priority, is_local: isLocal,
    });
    location.reload();
}

async function deleteProvider(id, name) {
    if (!confirm(`¿Eliminar el proveedor "${name}"? Esto no se puede deshacer.`)) return;
    await api(`/admin/api/providers/${id}`, 'DELETE');
    location.reload();
}

async function updateProviderPriority(id, priority) {
    await api(`/admin/api/providers/${id}`, 'PUT', { priority: parseInt(priority) });
}

// --- Routes ---
function showRouteForm() {
    const form = document.getElementById('route-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

function toggleRoutePatternMode() {
    const sel = document.getElementById('route-pattern-select');
    const inp = document.getElementById('route-pattern-input');
    const link = sel.parentElement.querySelector('.toggle-link');

    if (sel.style.display === 'none') {
        sel.style.display = '';
        inp.style.display = 'none';
        inp.value = '';
        link.textContent = 'o escribir patrón';
    } else {
        sel.style.display = 'none';
        inp.style.display = '';
        link.textContent = 'o seleccionar modelo';
    }
}

function addChainStep() {
    const builder = document.getElementById('route-chain-builder');
    const index = builder.children.length;

    const providerOptions = cachedProviders
        .map(p => `<option value="${p.name}">${p.display_name}</option>`)
        .join('');

    const div = document.createElement('div');
    div.className = 'chain-step';
    div.dataset.index = index;
    div.innerHTML = `
        <select class="chain-provider" onchange="onChainProviderChange(this)">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeChainStep(this)">✕</button>
    `;
    builder.appendChild(div);
}

function populateSingleChainModel(sel, filterProvider = '') {
    // Clear existing options beyond the placeholder
    while (sel.options.length > 1) sel.remove(1);
    // Remove existing optgroups
    sel.querySelectorAll('optgroup').forEach(g => g.remove());

    if (cachedByProvider.length > 0) {
        for (const pg of cachedByProvider) {
            // Filter by provider if specified
            if (filterProvider && pg.provider !== filterProvider) continue;
            // Only show language models in chain selects
            let models = pg.models;
            if (pg.models_typed) {
                models = pg.models_typed
                    .filter(m => m.type === 'language')
                    .map(m => m.name);
            }
            if (models.length === 0) continue;
            const group = document.createElement('optgroup');
            group.label = pg.display_name;
            for (const m of models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                group.appendChild(opt);
            }
            sel.appendChild(group);
        }
    }
}

function onChainProviderChange(providerSel) {
    const modelSel = providerSel.closest('.chain-step').querySelector('.chain-model');
    populateSingleChainModel(modelSel, providerSel.value);
}

function removeChainStep(btn) {
    const builder = document.getElementById('route-chain-builder');
    if (builder.children.length > 1) {
        btn.closest('.chain-step').remove();
    }
}

function editRoute(id, name, pattern, priority) {
    // Show form and populate
    document.getElementById('route-form').style.display = 'block';
    document.getElementById('route-edit-id').value = id;
    document.getElementById('route-name').value = name;
    document.getElementById('route-priority').value = priority;

    // Set pattern — use input mode for existing routes
    document.getElementById('route-pattern-select').style.display = 'none';
    const inp = document.getElementById('route-pattern-input');
    inp.style.display = '';
    inp.value = pattern;
    const link = inp.parentElement.querySelector('.toggle-link');
    if (link) link.textContent = 'o seleccionar modelo';

    // Populate chain from the table row's data attribute
    const row = document.querySelector(`tr[data-route]`);
    // Find the correct row by matching the id in the edit button
    const rows = document.querySelectorAll('#routes-body tr');
    let chainData = [];
    rows.forEach(r => {
        const editBtn = r.querySelector('button');
        if (editBtn && editBtn.getAttribute('onclick')?.includes(`editRoute(${id},`)) {
            try { chainData = JSON.parse(r.dataset.route); } catch {}
        }
    });

    // Rebuild chain steps
    const builder = document.getElementById('route-chain-builder');
    builder.innerHTML = '';
    if (chainData.length > 0) {
        for (const step of chainData) {
            addChainStep();
            const lastStep = builder.lastElementChild;
            lastStep.querySelector('.chain-provider').value = step.provider;
            populateSingleChainModel(lastStep.querySelector('.chain-model'), step.provider);
            lastStep.querySelector('.chain-model').value = step.model;
        }
    } else {
        addChainStep();
    }

    // Update button
    document.getElementById('route-submit-btn').textContent = 'Guardar Ruta';
    document.getElementById('route-cancel-btn').style.display = '';

    // Scroll to form
    document.getElementById('route-form').scrollIntoView({ behavior: 'smooth' });
}

function cancelEditRoute() {
    document.getElementById('route-edit-id').value = '';
    document.getElementById('route-form').style.display = 'none';
    document.getElementById('route-submit-btn').textContent = 'Crear Ruta';
    document.getElementById('route-cancel-btn').style.display = 'none';
    // Reset fields
    document.getElementById('route-name').value = '';
    document.getElementById('route-priority').value = '10';
}

async function submitRoute() {
    const editId = document.getElementById('route-edit-id').value;
    const name = document.getElementById('route-name').value.trim();

    const sel = document.getElementById('route-pattern-select');
    const inp = document.getElementById('route-pattern-input');
    const pattern = sel.style.display === 'none' ? inp.value.trim() : sel.value;

    if (!name || !pattern) {
        alert('Nombre y modelo/patrón son requeridos');
        return;
    }

    const chain = readChainSteps(document.getElementById('route-chain-builder'));
    if (chain.length === 0) {
        alert('Agrega al menos un provider a la cadena');
        return;
    }

    const priority = parseInt(document.getElementById('route-priority').value) || 10;
    const body = { name, model_pattern: pattern, provider_chain: chain, priority };

    if (editId) {
        await api(`/admin/api/routes/${editId}`, 'PUT', body);
    } else {
        await api('/admin/api/routes', 'POST', body);
    }
    location.reload();
}

async function deleteRoute(id) {
    if (!confirm('¿Eliminar esta ruta?')) return;
    await api(`/admin/api/routes/${id}`, 'DELETE');
    location.reload();
}

// --- API Keys ---

function getSmartRouteIds(containerId) {
    const container = document.getElementById(containerId);
    if (!container || !container.getValue) return [];
    const val = container.getValue();
    if (val === '__none__') return [];
    return val.split(',').map(name => {
        const sr = (window._smartRoutes || []).find(s => s.name === name);
        return sr ? sr.id : null;
    }).filter(Boolean);
}

async function loadKeysTable() {
    const keys = await api('/admin/api/keys');
    const container = document.getElementById('keys-table-container');
    if (!container) return;

    const rows = keys.map(k => {
        const srBadges = (k.smart_routes || []).map(sr =>
            `<code class="badge active" style="margin:1px">${sr.name}</code>`
        ).join(' ') || '—';
        const actions = k.is_active
            ? `<button onclick="editKey(${k.id})">Editar</button> <button onclick="revokeKey(${k.id})">Revocar</button>`
            : '';
        return `<tr>
            <td>${k.name}</td>
            <td>${k.service}</td>
            <td><code>${k.key_prefix}...</code></td>
            <td>${k.allowed_models}</td>
            <td>${srBadges}</td>
            <td>${k.rate_limit_rpm}</td>
            <td><span class="badge ${k.is_active ? 'active' : 'inactive'}">${k.is_active ? 'Activa' : 'Revocada'}</span></td>
            <td>${actions}</td>
        </tr>`;
    }).join('');

    container.innerHTML = `<table>
        <thead><tr>
            <th>Nombre</th><th>Servicio</th><th>Prefijo</th>
            <th>Modelos</th><th>Smart Routes</th><th>RPM</th>
            <th>Estado</th><th>Acciones</th>
        </tr></thead>
        <tbody>${rows}</tbody>
    </table>`;

    // Store keys data for edit
    window._keysData = keys;
}

async function createKey() {
    const name = document.getElementById('key-name').value.trim();

    const sel = document.getElementById('key-service-select');
    const inp = document.getElementById('key-service-input');
    const service = sel.value === '__new__' ? inp.value.trim() : sel.value;

    const msContainer = document.getElementById('key-models-ms');
    const models = msContainer?.getValue ? msContainer.getValue() : '*';

    const smartRouteIds = getSmartRouteIds('key-smart-routes-ms');

    if (!name || !service) {
        alert('Nombre y servicio son requeridos');
        return;
    }

    const body = { name, service, allowed_models: models, smart_route_ids: smartRouteIds };

    const result = await api('/admin/api/keys', 'POST', body);

    document.getElementById('new-key-value').textContent = result.key;
    document.getElementById('new-key-display').style.display = 'block';
    loadKeysTable();
}

async function editKey(id) {
    const key = (window._keysData || []).find(k => k.id === id);
    if (!key) return;

    document.getElementById('edit-key-id').value = id;
    document.getElementById('edit-key-name').value = key.name;
    document.getElementById('edit-key-service').value = key.service;

    // Build smart routes multi-select for edit
    const srOptions = (window._smartRoutes || []).filter(sr => sr.is_enabled).map(sr => sr.name);
    createMultiSelect('edit-key-smart-routes-ms', srOptions, {
        allValue: '__none__',
        allLabel: '(ninguna)',
    });

    // Pre-select assigned routes
    const assignedNames = (key.smart_routes || []).map(sr => sr.name);
    if (assignedNames.length > 0) {
        const container = document.getElementById('edit-key-smart-routes-ms');
        const dropdown = container.querySelector('.ms-dropdown');
        if (dropdown) {
            const allCb = dropdown.querySelector('input[value="__none__"]');
            if (allCb) allCb.checked = false;
            dropdown.querySelectorAll('input:not([value="__none__"])').forEach(cb => {
                cb.checked = assignedNames.includes(cb.value);
            });
            // Update display
            const display = container.querySelector('.ms-display');
            if (display) {
                display.textContent = assignedNames.length > 2
                    ? `${assignedNames.length} rutas seleccionadas`
                    : assignedNames.join(', ');
            }
        }
    }

    document.getElementById('edit-key-modal').style.display = 'block';
}

async function saveKeyEdit() {
    const id = parseInt(document.getElementById('edit-key-id').value);
    const name = document.getElementById('edit-key-name').value.trim();
    const service = document.getElementById('edit-key-service').value.trim();
    const smartRouteIds = getSmartRouteIds('edit-key-smart-routes-ms');

    if (!name || !service) {
        alert('Nombre y servicio son requeridos');
        return;
    }

    await api(`/admin/api/keys/${id}`, 'PUT', {
        name, service, smart_route_ids: smartRouteIds
    });

    document.getElementById('edit-key-modal').style.display = 'none';
    loadKeysTable();
}

function cancelKeyEdit() {
    document.getElementById('edit-key-modal').style.display = 'none';
}

async function revokeKey(id) {
    if (!confirm('¿Revocar esta key? No se puede deshacer.')) return;
    await api(`/admin/api/keys/${id}`, 'DELETE');
    loadKeysTable();
}

// --- Analytics ---
let timelineChart = null;
let latencyTimelineChart = null;

async function loadAnalytics(days = 7) {
    // Update active button
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.classList.toggle('active', parseInt(btn.dataset.days) === days);
    });

    const data = await api(`/admin/api/analytics?days=${days}`);
    renderAnalyticsCards(data.summary);
    renderAnalyticsProviders(data.by_provider);
    renderAnalyticsModels(data.by_model);
    renderAnalyticsServices(data.by_service);
    renderTimeline(data.timeline);
    renderAnalyticsIntents(data.by_intent || []);
    renderAnalyticsFallbacks(data.fallback_paths || []);
    renderLatencyTimeline(data.latency_timeline || []);
    renderCostVsQuality(data.cost_vs_quality || []);
}

function renderAnalyticsCards(s) {
    const errorPct = s.total_requests ? (s.error_count / s.total_requests * 100).toFixed(1) : '0.0';
    const fallbackPct = s.total_requests ? (s.fallback_count / s.total_requests * 100).toFixed(1) : '0.0';
    document.getElementById('analytics-cards').innerHTML = `
        <div class="acard"><span class="acard-value">${s.total_requests.toLocaleString()}</span><span class="acard-label">Requests</span></div>
        <div class="acard"><span class="acard-value">$${s.total_cost.toFixed(4)}</span><span class="acard-label">Costo</span></div>
        <div class="acard"><span class="acard-value">${s.total_tokens.toLocaleString()}</span><span class="acard-label">Tokens</span></div>
        <div class="acard"><span class="acard-value">${s.avg_latency}ms</span><span class="acard-label">Latencia avg</span></div>
        <div class="acard ${parseFloat(errorPct) > 5 ? 'acard-warn' : ''}"><span class="acard-value">${errorPct}%</span><span class="acard-label">Errores</span></div>
        <div class="acard"><span class="acard-value">${fallbackPct}%</span><span class="acard-label">Fallbacks</span></div>
    `;
}

function renderAnalyticsProviders(providers) {
    const tbody = document.getElementById('analytics-provider-body');
    tbody.innerHTML = providers.map(p => `
        <tr>
            <td>${p.provider}</td><td>${p.requests}</td><td>${p.tokens.toLocaleString()}</td>
            <td>$${p.cost.toFixed(4)}</td><td>${p.avg_latency}ms</td>
            <td>${p.error_rate}%</td><td>${p.fallback_rate}%</td>
        </tr>
    `).join('');
}

function renderAnalyticsModels(models) {
    const tbody = document.getElementById('analytics-model-body');
    tbody.innerHTML = models.map(m => `
        <tr>
            <td><code>${m.model}</code></td><td>${m.provider}</td><td>${m.requests}</td>
            <td>${m.tokens.toLocaleString()}</td><td>$${m.cost.toFixed(4)}</td><td>${m.avg_latency}ms</td>
        </tr>
    `).join('');
}

function renderAnalyticsServices(services) {
    const tbody = document.getElementById('analytics-service-body');
    if (!services.length) {
        tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--text-dim)">Sin datos</td></tr>';
        return;
    }
    tbody.innerHTML = services.map(s => `
        <tr><td>${s.service}</td><td>${s.requests}</td><td>${s.tokens.toLocaleString()}</td><td>$${s.cost.toFixed(4)}</td></tr>
    `).join('');
}

function renderTimeline(timeline) {
    const ctx = document.getElementById('timeline-chart');
    if (!ctx) return;

    if (timelineChart) {
        timelineChart.destroy();
    }

    if (!timeline.length) {
        // Clear canvas if no data
        const context2d = ctx.getContext('2d');
        context2d.clearRect(0, 0, ctx.width, ctx.height);
        return;
    }

    const labels = timeline.map(t => t.date);
    timelineChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Requests',
                    data: timeline.map(t => t.requests),
                    borderColor: '#6c5ce7',
                    backgroundColor: 'rgba(108, 92, 231, 0.1)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y',
                },
                {
                    label: 'Costo ($)',
                    data: timeline.map(t => t.cost),
                    borderColor: '#00b894',
                    backgroundColor: 'rgba(0, 184, 148, 0.1)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y1',
                },
            ],
        },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { labels: { color: '#8b8fa3' } },
            },
            scales: {
                x: { ticks: { color: '#8b8fa3' }, grid: { color: '#2a2d3a' } },
                y: {
                    position: 'left',
                    title: { display: true, text: 'Requests', color: '#8b8fa3' },
                    ticks: { color: '#8b8fa3' },
                    grid: { color: '#2a2d3a' },
                },
                y1: {
                    position: 'right',
                    title: { display: true, text: 'Costo ($)', color: '#8b8fa3' },
                    ticks: { color: '#8b8fa3' },
                    grid: { drawOnChartArea: false },
                },
            },
        },
    });
}

function renderAnalyticsIntents(intents) {
    const tbody = document.getElementById('analytics-intent-body');
    if (!intents.length) {
        tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim)">Sin datos de Smart Routes</td></tr>';
        return;
    }
    tbody.innerHTML = intents.map(i => `
        <tr>
            <td><code>${i.smart_route}</code></td><td>${i.intent}</td><td>${i.requests}</td>
            <td>$${i.cost.toFixed(4)}</td><td>${i.avg_latency}ms</td>
            <td>${i.errors}</td><td>${i.fallbacks}</td>
        </tr>
    `).join('');
}

function renderAnalyticsFallbacks(paths) {
    const tbody = document.getElementById('analytics-fallback-body');
    if (!paths.length) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--text-dim)">Sin fallbacks</td></tr>';
        return;
    }
    tbody.innerHTML = paths.map(p => `
        <tr><td><code>${p.route_path}</code></td><td>${p.count}</td></tr>
    `).join('');
}

function renderLatencyTimeline(data) {
    const ctx = document.getElementById('latency-timeline-chart');
    if (!ctx) return;
    if (latencyTimelineChart) latencyTimelineChart.destroy();
    if (!data.length) {
        const c = ctx.getContext('2d');
        c.clearRect(0, 0, ctx.width, ctx.height);
        return;
    }

    // Group by provider
    const providers = [...new Set(data.map(d => d.provider))];
    const dates = [...new Set(data.map(d => d.date))].sort();
    const colors = ['#6c5ce7', '#00b894', '#e17055', '#0984e3', '#fdcb6e', '#e84393', '#00cec9'];

    const datasets = providers.map((prov, idx) => {
        const provData = data.filter(d => d.provider === prov);
        const byDate = Object.fromEntries(provData.map(d => [d.date, d.avg_latency]));
        return {
            label: prov,
            data: dates.map(d => byDate[d] || null),
            borderColor: colors[idx % colors.length],
            tension: 0.3,
            spanGaps: true,
        };
    });

    latencyTimelineChart = new Chart(ctx, {
        type: 'line',
        data: { labels: dates, datasets },
        options: {
            responsive: true,
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: { labels: { color: '#8b8fa3' } } },
            scales: {
                x: { ticks: { color: '#8b8fa3' }, grid: { color: '#2a2d3a' } },
                y: {
                    title: { display: true, text: 'Latencia (ms)', color: '#8b8fa3' },
                    ticks: { color: '#8b8fa3' },
                    grid: { color: '#2a2d3a' },
                },
            },
        },
    });
}

function renderCostVsQuality(data) {
    const tbody = document.getElementById('analytics-cvq-body');
    if (!data.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;color:var(--text-dim)">Sin datos</td></tr>';
        return;
    }
    tbody.innerHTML = data.map(d => {
        const rating = d.avg_rating !== null ? `${d.avg_rating} (${d.arena_battles})` : '<span style="color:var(--text-dim)">—</span>';
        const spd = d.score_per_dollar !== null ? d.score_per_dollar.toLocaleString() : '<span style="color:var(--text-dim)">—</span>';
        return `<tr>
            <td><code>${d.model}</code></td><td>${d.provider}</td><td>${d.requests}</td>
            <td>$${d.total_cost.toFixed(4)}</td><td>$${d.avg_cost_per_req.toFixed(6)}</td>
            <td>${d.avg_latency}ms</td><td>${rating}</td><td>${spd}</td>
        </tr>`;
    }).join('');
}

// --- Playground ---
async function sendPlayground() {
    const key = document.getElementById('pg-key-manual').value.trim();
    const model = document.getElementById('pg-model').value;
    const message = document.getElementById('pg-message').value.trim();
    const stream = document.getElementById('pg-stream').checked;
    const output = document.getElementById('pg-output');

    if (!key || !model || !message) {
        alert('Completa todos los campos (key, modelo, mensaje)');
        return;
    }

    output.textContent = 'Enviando...';

    if (stream) {
        const res = await fetch('/v1/chat/completions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${key}`
            },
            body: JSON.stringify({
                model, stream: true,
                messages: [{ role: 'user', content: message }]
            })
        });

        output.textContent = '';
        const reader = res.body.getReader();
        const decoder = new TextDecoder();

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            const text = decoder.decode(value);
            for (const line of text.split('\n')) {
                if (line.startsWith('data: ') && line !== 'data: [DONE]') {
                    try {
                        const chunk = JSON.parse(line.slice(6));
                        const content = chunk.choices?.[0]?.delta?.content || '';
                        output.textContent += content;
                    } catch {}
                }
            }
        }
    } else {
        try {
            const res = await fetch('/v1/chat/completions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${key}`
                },
                body: JSON.stringify({
                    model,
                    messages: [{ role: 'user', content: message }]
                })
            });
            const data = await res.json();
            output.textContent = data.choices?.[0]?.message?.content || JSON.stringify(data, null, 2);
        } catch (e) {
            output.textContent = 'Error: ' + e.message;
        }
    }
}

// --- Smart Routes ---
function showSmartRouteForm() {
    const form = document.getElementById('smart-route-form');
    form.style.display = form.style.display === 'none' ? 'block' : 'none';

    // Add initial classifier chain step if none exist
    if (document.getElementById('sr-classifier-chain').children.length === 0) {
        addClassifierChainStep();
    }

    // Add initial intent if none exist
    if (document.getElementById('sr-intents').children.length === 0) {
        addIntent();
    }
    // Add initial default chain step
    if (document.getElementById('sr-default-chain').children.length === 0) {
        addDefaultChainStep();
    }
}

function addIntent() {
    const container = document.getElementById('sr-intents');
    const index = container.children.length;

    const providerOptions = cachedProviders
        .map(p => `<option value="${p.name}">${p.display_name}</option>`)
        .join('');

    const div = document.createElement('div');
    div.className = 'intent-builder';
    div.innerHTML = `
        <div class="form-row">
            <div class="form-group" style="flex:0 0 150px">
                <label>Nombre</label>
                <input class="intent-name-input" placeholder="e.g. coding" />
            </div>
            <div class="form-group" style="flex:1">
                <label>Descripción (para el clasificador)</label>
                <input class="intent-desc-input" placeholder="e.g. Programación, debugging, revisión de código" />
            </div>
            <div class="form-group" style="flex:0 0 30px">
                <label>&nbsp;</label>
                <button type="button" class="btn-small btn-danger" onclick="this.closest('.intent-builder').remove()">✕</button>
            </div>
        </div>
        <div class="form-group">
            <label>Cadena de providers para esta intención</label>
            <div class="intent-chain-steps">
                <div class="chain-step">
                    <select class="chain-provider" onchange="onChainProviderChange(this)">
                        <option value="">-- Provider --</option>
                        ${providerOptions}
                    </select>
                    <select class="chain-model">
                        <option value="">-- Modelo --</option>
                    </select>
                    <button type="button" class="btn-small btn-danger" onclick="removeIntentChainStep(this)">✕</button>
                </div>
            </div>
            <button type="button" class="btn-small" onclick="addIntentChainStep(this)">+ Provider</button>
        </div>
    `;
    container.appendChild(div);

    // Populate model selects
    div.querySelectorAll('.chain-model').forEach(populateSingleChainModel);
}

function addIntentChainStep(btn) {
    const stepsContainer = btn.previousElementSibling;
    const providerOptions = cachedProviders
        .map(p => `<option value="${p.name}">${p.display_name}</option>`)
        .join('');

    const div = document.createElement('div');
    div.className = 'chain-step';
    div.innerHTML = `
        <select class="chain-provider" onchange="onChainProviderChange(this)">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeIntentChainStep(this)">✕</button>
    `;
    stepsContainer.appendChild(div);
}

function removeIntentChainStep(btn) {
    const steps = btn.closest('.intent-chain-steps');
    if (steps.children.length > 1) {
        btn.closest('.chain-step').remove();
    }
}

function addClassifierChainStep() {
    const container = document.getElementById('sr-classifier-chain');
    const providerOptions = cachedProviders
        .map(p => `<option value="${p.name}">${p.display_name}</option>`)
        .join('');

    const div = document.createElement('div');
    div.className = 'chain-step';
    div.innerHTML = `
        <select class="chain-provider" onchange="onChainProviderChange(this)">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeClassifierChainStep(this)">✕</button>
    `;
    container.appendChild(div);
}

function removeClassifierChainStep(btn) {
    const container = document.getElementById('sr-classifier-chain');
    if (container.children.length > 1) {
        btn.closest('.chain-step').remove();
    }
}

function addDefaultChainStep() {
    const container = document.getElementById('sr-default-chain');
    const providerOptions = cachedProviders
        .map(p => `<option value="${p.name}">${p.display_name}</option>`)
        .join('');

    const div = document.createElement('div');
    div.className = 'chain-step';
    div.innerHTML = `
        <select class="chain-provider" onchange="onChainProviderChange(this)">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeDefaultChainStep(this)">✕</button>
    `;
    container.appendChild(div);
}

function removeDefaultChainStep(btn) {
    const container = document.getElementById('sr-default-chain');
    if (container.children.length > 1) {
        btn.closest('.chain-step').remove();
    }
}

function readChainSteps(container) {
    const chain = [];
    container.querySelectorAll('.chain-step').forEach(step => {
        const provider = step.querySelector('.chain-provider').value;
        const model = step.querySelector('.chain-model').value;
        if (provider && model) chain.push({ provider, model });
    });
    return chain;
}

function editSmartRoute(id) {
    const card = document.querySelector(`.smart-route-card[data-id="${id}"]`);
    if (!card) return;
    const data = JSON.parse(card.dataset.sr);

    // Show form
    showSmartRouteForm();

    // Populate fields
    document.getElementById('sr-edit-id').value = id;
    document.getElementById('sr-name').value = data.name;
    document.getElementById('sr-trigger').value = data.trigger_model;
    // Clear and rebuild classifier chain
    const classifierContainer = document.getElementById('sr-classifier-chain');
    classifierContainer.innerHTML = '';
    const classifierChain = data.classifier_chain || [];
    for (const step of classifierChain) {
        addClassifierChainStep();
        const lastStep = classifierContainer.lastElementChild;
        lastStep.querySelector('.chain-provider').value = step.provider;
        populateSingleChainModel(lastStep.querySelector('.chain-model'), step.provider);
        lastStep.querySelector('.chain-model').value = step.model;
    }
    if (classifierChain.length === 0) addClassifierChainStep();

    // Clear and rebuild intents
    const intentsContainer = document.getElementById('sr-intents');
    intentsContainer.innerHTML = '';
    for (const intent of data.intents) {
        addIntent();
        const ib = intentsContainer.lastElementChild;
        ib.querySelector('.intent-name-input').value = intent.name;
        ib.querySelector('.intent-desc-input').value = intent.description;

        // Rebuild chain steps for this intent
        const stepsContainer = ib.querySelector('.intent-chain-steps');
        stepsContainer.innerHTML = '';
        for (const step of intent.provider_chain) {
            const addBtn = ib.querySelector('.intent-chain-steps + button');
            addIntentChainStep(addBtn);
            const lastStep = stepsContainer.lastElementChild;
            lastStep.querySelector('.chain-provider').value = step.provider;
            populateSingleChainModel(lastStep.querySelector('.chain-model'), step.provider);
            lastStep.querySelector('.chain-model').value = step.model;
        }
    }

    // Rebuild default chain
    const defaultContainer = document.getElementById('sr-default-chain');
    defaultContainer.innerHTML = '';
    const defaultChain = data.default_chain || [];
    for (const step of defaultChain) {
        addDefaultChainStep();
        const lastStep = defaultContainer.lastElementChild;
        lastStep.querySelector('.chain-provider').value = step.provider;
        populateSingleChainModel(lastStep.querySelector('.chain-model'), step.provider);
        lastStep.querySelector('.chain-model').value = step.model;
    }
    if (defaultChain.length === 0) addDefaultChainStep();

    // Update buttons
    document.getElementById('sr-submit-btn').textContent = 'Guardar Smart Route';
    document.getElementById('sr-cancel-btn').style.display = '';

    // Scroll to form
    document.getElementById('smart-route-form').scrollIntoView({ behavior: 'smooth' });
}

function cancelEditSmartRoute() {
    document.getElementById('sr-edit-id').value = '';
    document.getElementById('smart-route-form').style.display = 'none';
    document.getElementById('sr-submit-btn').textContent = 'Crear Smart Route';
    document.getElementById('sr-cancel-btn').style.display = 'none';
    // Reset fields
    document.getElementById('sr-name').value = '';
    document.getElementById('sr-trigger').value = 'auto';
    document.getElementById('sr-classifier-chain').innerHTML = '';
    document.getElementById('sr-intents').innerHTML = '';
    document.getElementById('sr-default-chain').innerHTML = '';
}

async function submitSmartRoute() {
    const editId = document.getElementById('sr-edit-id').value;
    const name = document.getElementById('sr-name').value.trim();
    const trigger = document.getElementById('sr-trigger').value.trim();
    const classifierChain = readChainSteps(document.getElementById('sr-classifier-chain'));

    if (!name || !trigger || classifierChain.length === 0) {
        alert('Nombre, modelo trigger, y al menos un clasificador son requeridos');
        return;
    }

    const intents = [];
    document.querySelectorAll('#sr-intents .intent-builder').forEach(ib => {
        const intentName = ib.querySelector('.intent-name-input').value.trim();
        const intentDesc = ib.querySelector('.intent-desc-input').value.trim();
        const chain = readChainSteps(ib.querySelector('.intent-chain-steps'));
        if (intentName && chain.length > 0) {
            intents.push({ name: intentName, description: intentDesc, provider_chain: chain });
        }
    });

    if (intents.length === 0) {
        alert('Agrega al menos una intención con su cadena de providers');
        return;
    }

    const defaultChain = readChainSteps(document.getElementById('sr-default-chain'));
    const classifier = classifierChain[0].model;
    const body = {
        name, trigger_model: trigger, classifier_model: classifier,
        classifier_chain: classifierChain,
        intents, default_chain: defaultChain,
    };

    if (editId) {
        await api(`/admin/api/smart-routes/${editId}`, 'PUT', body);
    } else {
        await api('/admin/api/smart-routes', 'POST', body);
    }
    location.reload();
}

async function toggleSmartRoute(id) {
    await api(`/admin/api/smart-routes/${id}/toggle`, 'PUT');
    location.reload();
}

async function deleteSmartRoute(id) {
    if (!confirm('¿Eliminar este smart route?')) return;
    await api(`/admin/api/smart-routes/${id}`, 'DELETE');
    location.reload();
}

// --- Key Expiry Alerts ---
function renderKeyExpiryAlerts() {
    const container = document.getElementById('key-alerts');
    if (!container) return;

    const alerts = [];
    for (const p of cachedProviders) {
        if (p.key_expired) {
            alerts.push(`<div class="key-expiry-alert expired">
                <strong>${p.display_name}</strong> — API key EXPIRADA.
                <a href="#provider-config">Renovar ahora</a>
            </div>`);
        } else if (p.key_expires_soon) {
            alerts.push(`<div class="key-expiry-alert warning">
                <strong>${p.display_name}</strong> — API key expira en <strong>${p.key_days_left} días</strong>
                (${p.api_key_expires_at?.split('T')[0]}).
                <a href="#provider-config">Configurar</a>
            </div>`);
        }
    }

    if (alerts.length > 0) {
        container.innerHTML = alerts.join('');
        container.style.display = 'block';
    }
}

// --- Provider Configuration ---
function renderProviderConfigCards() {
    const container = document.getElementById('provider-config-cards');
    if (!container) return;

    if (cachedProviders.length === 0) {
        container.innerHTML = '<p style="color:var(--text-dim)">No hay providers configurados.</p>';
        return;
    }

    container.innerHTML = '';
    for (const p of cachedProviders) {
        const hasKey = p.has_key;
        const isLocal = p.is_local;
        const card = document.createElement('div');
        card.className = `provider-card ${isLocal ? 'has-key' : (hasKey ? 'has-key' : 'no-key')}`;
        card.id = `pc-${p.id}`;

        const keySourceLabel = p.key_source === 'db' ? '(guardada en DB)'
            : p.key_source === 'env' ? '(variable de entorno)'
            : '';

        const keyStatusClass = hasKey ? 'configured' : 'not-configured';
        const keyStatusText = hasKey ? `Configurada ${keySourceLabel}` : 'Sin configurar';
        const keyPreview = p.key_preview || '';

        // Expiry info
        const expiresAt = p.api_key_expires_at ? p.api_key_expires_at.split('T')[0] : '';
        const daysLeft = p.key_days_left;
        let expiryBadge = '';
        if (p.key_expired) {
            expiryBadge = '<span class="pc-key-status" style="background:rgba(225,112,85,0.2);color:var(--danger)">EXPIRADA</span>';
        } else if (p.key_expires_soon) {
            expiryBadge = `<span class="pc-key-status" style="background:rgba(253,203,110,0.2);color:var(--warning)">${daysLeft} días restantes</span>`;
        } else if (daysLeft !== null) {
            expiryBadge = `<span style="font-size:0.8rem;color:var(--text-dim)">Expira en ${daysLeft} días</span>`;
        }

        // Find provider's model data from cachedByProvider
        const providerModels = cachedByProvider.find(bp => bp.provider === p.name);
        const allModels = providerModels?.all_models || providerModels?.models || [];
        const enabledModels = p.enabled_models || [];

        // Build model type lookup from all_models_typed
        const modelTypeMap = {};
        const providerAllTyped = providerModels?.all_models_typed || [];
        for (const mt of providerAllTyped) {
            modelTypeMap[mt.name] = mt.type;
        }

        // Count models by type
        const typeCounts = {};
        for (const m of allModels) {
            const t = modelTypeMap[m] || 'language';
            typeCounts[t] = (typeCounts[t] || 0) + 1;
        }

        const typeLabel = isLocal ? 'Local' : 'Cloud';
        const enabledBadge = p.is_enabled
            ? '<span class="badge active">Activo</span>'
            : '<span class="badge inactive">Inactivo</span>';

        // Type summary badges
        const typeSummary = Object.entries(typeCounts)
            .map(([t, count]) => {
                const label = MODEL_TYPE_LABELS[t] || t;
                const color = MODEL_TYPE_COLORS[t] || '#888';
                return `<span style="font-size:0.7rem;background:${color}20;color:${color};border:1px solid ${color}40;padding:0 4px;border-radius:3px">${count} ${label}</span>`;
            }).join(' ');

        card.innerHTML = `
            <div class="pc-header" onclick="this.parentElement.classList.toggle('open')">
                <h3>${p.display_name}</h3>
                <span style="font-size:0.75rem;color:var(--text-dim)">${typeLabel} · P${p.priority}</span>
                ${enabledBadge}
                ${!isLocal ? `<span class="pc-key-status ${keyStatusClass}">${keyStatusText}</span>` : ''}
                ${keyPreview && !isLocal ? `<code style="font-size:0.8rem;color:var(--text-dim)">${keyPreview}</code>` : ''}
                ${expiryBadge}
                <span style="display:flex;gap:3px;flex-wrap:wrap">${typeSummary}</span>
                <span class="pc-chevron">&#9660;</span>
            </div>
            <div class="pc-body">
                <div style="display:flex;gap:0.5rem;margin-bottom:0.8rem;flex-wrap:wrap;align-items:center">
                    <button class="btn-small ${p.is_enabled ? 'btn-danger' : ''}"
                            onclick="toggleProvider(${p.id}, ${!p.is_enabled})">
                        ${p.is_enabled ? 'Desactivar' : 'Activar'}
                    </button>
                    <button class="btn-small btn-danger" onclick="deleteProvider(${p.id}, '${p.display_name}')">Eliminar</button>
                    <label style="font-size:0.8rem;margin:0">Prioridad:</label>
                    <input type="number" value="${p.priority}" min="1" max="100" style="width:60px;font-size:0.8rem"
                           onchange="updateProviderPriority(${p.id}, this.value)" />
                </div>
                ${!isLocal ? `
                <div class="pc-key-row">
                    <input type="password" id="pc-key-${p.id}" placeholder="API Key del proveedor"
                           value="" autocomplete="off" />
                    <div style="display:flex;align-items:center;gap:0.3rem">
                        <label style="font-size:0.8rem;white-space:nowrap;margin:0">Expira:</label>
                        <input type="date" id="pc-expiry-${p.id}" value="${expiresAt}"
                               style="width:140px;font-size:0.8rem" />
                    </div>
                    <button onclick="saveProviderKey(${p.id})">Guardar Key</button>
                    ${hasKey ? `<button class="btn-danger btn-small" onclick="clearProviderKey(${p.id})">Borrar Key</button>` : ''}
                    <button class="btn-secondary btn-small pc-discover-btn" onclick="discoverModels(${p.id})">
                        Descubrir modelos
                    </button>
                    <span id="pc-msg-${p.id}" class="pc-msg"></span>
                </div>` : `
                <div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem">
                    <button class="btn-secondary btn-small pc-discover-btn" onclick="discoverModels(${p.id})">
                        Descubrir modelos
                    </button>
                    <span id="pc-msg-${p.id}" class="pc-msg"></span>
                </div>`}
                <div class="pc-test-section" style="margin-top:0.8rem;padding-top:0.8rem;border-top:1px solid var(--border)">
                    <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
                        <label style="font-size:0.85rem;font-weight:500;margin:0">Probar conexión:</label>
                        <select id="pc-test-model-${p.id}" style="min-width:200px">
                            <option value="">-- Modelo --</option>
                            ${allModels.slice(0, 50).map(m => `<option value="${m}">${m}</option>`).join('')}
                        </select>
                        <button class="btn-small" onclick="testProvider(${p.id})" ${!hasKey && !p.is_local ? 'disabled' : ''}>
                            Probar
                        </button>
                        <span id="pc-test-msg-${p.id}" class="pc-msg"></span>
                    </div>
                    <pre id="pc-test-result-${p.id}" style="display:none;margin-top:0.5rem;background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:0.6rem;font-size:0.8rem;max-height:150px;overflow-y:auto;white-space:pre-wrap"></pre>
                </div>
                <div class="pc-models-section" id="pc-models-${p.id}">
                    <h4>
                        Modelos activos
                        ${allModels.length > 0 ? `<span class="pc-select-all" onclick="toggleAllModels(${p.id})">seleccionar/deseleccionar todos</span>` : ''}
                    </h4>
                    ${allModels.length > 0 && Object.keys(typeCounts).length > 1 ? `
                    <div class="pc-type-filter" style="margin-bottom:0.5rem;display:flex;gap:4px;flex-wrap:wrap">
                        <button class="btn-small pc-type-btn active" onclick="filterModelGrid(${p.id}, 'all', this)" style="font-size:0.75rem;padding:2px 8px">Todos</button>
                        ${Object.entries(typeCounts).map(([t, count]) => {
                            const label = MODEL_TYPE_LABELS[t] || t;
                            const color = MODEL_TYPE_COLORS[t] || '#888';
                            return `<button class="btn-small pc-type-btn" onclick="filterModelGrid(${p.id}, '${t}', this)" style="font-size:0.75rem;padding:2px 8px;border-color:${color}">${label} (${count})</button>`;
                        }).join('')}
                    </div>` : ''}
                    <div class="pc-model-grid" id="pc-grid-${p.id}">
                        ${allModels.length > 0
                            ? allModels.map(m => {
                                const checked = enabledModels.length === 0 || enabledModels.includes(m);
                                const isCustom = (providerModels?.custom_models || []).includes(m);
                                const mType = modelTypeMap[m] || 'language';
                                const badge = mType !== 'language' ? modelTypeBadge(mType) : '';
                                return `<label class="pc-model-chip ${checked ? 'selected' : ''}" data-model-type="${mType}" ${isCustom ? 'title="Añadido manualmente"' : ''}>
                                    <input type="checkbox" value="${m}" ${checked ? 'checked' : ''}
                                           onchange="this.parentElement.classList.toggle('selected', this.checked)" />
                                    ${isCustom ? '✎ ' : ''}${m}${badge}
                                </label>`;
                            }).join('')
                            : `<span style="color:var(--text-dim);font-size:0.85rem">${hasKey ? 'Haz clic en "Descubrir modelos" para ver los disponibles' : 'Configura la API key primero'}</span>`
                        }
                    </div>
                    <div style="display:flex;gap:0.5rem;align-items:center;margin-top:0.5rem;flex-wrap:wrap">
                        <input id="pc-custom-${p.id}" placeholder="Añadir modelo manualmente (ej: minimax-01)" style="min-width:250px;font-size:0.8rem" />
                        <button class="btn-small btn-secondary" onclick="addCustomModel(${p.id})">+ Añadir</button>
                    </div>
                    ${allModels.length > 0 ? `
                    <div class="pc-actions">
                        <button class="btn-small" onclick="saveProviderModels(${p.id})">Guardar selección</button>
                        <span id="pc-models-msg-${p.id}" class="pc-msg"></span>
                    </div>` : ''}
                </div>
            </div>
        `;
        container.appendChild(card);
    }
}

async function saveProviderKey(providerId) {
    const input = document.getElementById(`pc-key-${providerId}`);
    const expiryInput = document.getElementById(`pc-expiry-${providerId}`);
    const msg = document.getElementById(`pc-msg-${providerId}`);
    const key = input.value.trim();
    const expiry = expiryInput?.value || null;

    // If no key but expiry changed, update just the expiry
    if (!key && expiry) {
        msg.textContent = 'Guardando fecha...';
        msg.className = 'pc-msg';
        await api(`/admin/api/providers/${providerId}/expiry`, 'PUT', { expires_at: expiry });
        msg.textContent = 'Fecha de expiración guardada';
        msg.className = 'pc-msg success';
        setTimeout(() => location.reload(), 1500);
        return;
    }

    if (!key) {
        msg.textContent = 'Ingresa una API key';
        msg.className = 'pc-msg error';
        return;
    }

    msg.textContent = 'Guardando...';
    msg.className = 'pc-msg';

    const body = { api_key: key };
    if (expiry) body.expires_at = expiry;

    const result = await api(`/admin/api/providers/${providerId}/key`, 'PUT', body);
    msg.textContent = `Key ${result.status} para ${result.provider}`;
    msg.className = 'pc-msg success';
    input.value = '';

    setTimeout(() => location.reload(), 1500);
}

async function clearProviderKey(providerId) {
    if (!confirm('¿Borrar la API key de este proveedor?')) return;
    await api(`/admin/api/providers/${providerId}/key`, 'PUT', { api_key: '' });
    location.reload();
}

async function discoverModels(providerId) {
    const msg = document.getElementById(`pc-msg-${providerId}`);
    msg.textContent = 'Consultando modelos disponibles...';
    msg.className = 'pc-msg';

    try {
        const result = await api(`/admin/api/providers/${providerId}/discover`);
        const models = result.models || [];

        if (models.length === 0) {
            msg.textContent = 'No se encontraron modelos. ¿La API key es correcta?';
            msg.className = 'pc-msg error';
            return;
        }

        msg.textContent = `${models.length} modelos encontrados`;
        msg.className = 'pc-msg success';

        // Get currently enabled models for this provider
        const provider = cachedProviders.find(p => p.id === providerId);
        const enabled = provider?.enabled_models || [];

        // Build type map from typed results
        const discoverTypeMap = {};
        const modelsTyped = result.models_typed || [];
        for (const mt of modelsTyped) {
            discoverTypeMap[mt.name] = mt.type;
        }

        // Render model chips with type badges
        const grid = document.getElementById(`pc-grid-${providerId}`);
        grid.innerHTML = models.map(m => {
            const checked = enabled.length === 0 || enabled.includes(m);
            const mType = discoverTypeMap[m] || 'language';
            const badge = mType !== 'language' ? modelTypeBadge(mType) : '';
            return `<label class="pc-model-chip ${checked ? 'selected' : ''}" data-model-type="${mType}">
                <input type="checkbox" value="${m}" ${checked ? 'checked' : ''}
                       onchange="this.parentElement.classList.toggle('selected', this.checked)" />
                ${m}${badge}
            </label>`;
        }).join('');

        // Show save button if not already visible
        const section = document.getElementById(`pc-models-${providerId}`);
        if (!section.querySelector('.pc-actions')) {
            const actions = document.createElement('div');
            actions.className = 'pc-actions';
            actions.innerHTML = `
                <button class="btn-small" onclick="saveProviderModels(${providerId})">Guardar selección</button>
                <span id="pc-models-msg-${providerId}" class="pc-msg"></span>
            `;
            section.appendChild(actions);
        }

        // Update select-all link
        const h4 = section.querySelector('h4');
        if (!h4.querySelector('.pc-select-all')) {
            h4.innerHTML += ` <span class="pc-select-all" onclick="toggleAllModels(${providerId})">seleccionar/deseleccionar todos</span>`;
        }
    } catch (e) {
        msg.textContent = 'Error al consultar: ' + e.message;
        msg.className = 'pc-msg error';
    }
}

function filterModelGrid(providerId, type, btn) {
    const grid = document.getElementById(`pc-grid-${providerId}`);
    const chips = grid.querySelectorAll('.pc-model-chip');
    chips.forEach(chip => {
        if (type === 'all' || chip.dataset.modelType === type) {
            chip.style.display = '';
        } else {
            chip.style.display = 'none';
        }
    });

    // Update active button
    const filterContainer = btn.closest('.pc-type-filter');
    if (filterContainer) {
        filterContainer.querySelectorAll('.pc-type-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    }
}

function toggleAllModels(providerId) {
    const grid = document.getElementById(`pc-grid-${providerId}`);
    const checkboxes = grid.querySelectorAll('input[type="checkbox"]');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);

    checkboxes.forEach(cb => {
        cb.checked = !allChecked;
        cb.parentElement.classList.toggle('selected', !allChecked);
    });
}

async function addCustomModel(providerId) {
    const input = document.getElementById(`pc-custom-${providerId}`);
    const modelName = input.value.trim();
    if (!modelName) return;

    // Get current custom models from the provider data
    const provider = cachedProviders.find(p => p.id === providerId);
    const providerModels = cachedByProvider.find(bp => bp.provider === provider?.name);
    const existing = providerModels?.custom_models || [];

    if (existing.includes(modelName) || (providerModels?.all_models || []).includes(modelName)) {
        input.value = '';
        return; // already exists
    }

    const updated = [...existing, modelName];
    await api(`/admin/api/providers/${providerId}/custom-models`, 'PUT', { custom_models: updated });

    // Add chip to grid immediately
    const grid = document.getElementById(`pc-grid-${providerId}`);
    const label = document.createElement('label');
    label.className = 'pc-model-chip selected';
    label.title = 'Añadido manualmente';
    label.innerHTML = `<input type="checkbox" value="${modelName}" checked
                              onchange="this.parentElement.classList.toggle('selected', this.checked)" />
                       ✎ ${modelName}`;
    grid.appendChild(label);

    // Also add to test select
    const testSel = document.getElementById(`pc-test-model-${providerId}`);
    if (testSel) {
        const opt = document.createElement('option');
        opt.value = modelName;
        opt.textContent = modelName;
        testSel.appendChild(opt);
    }

    input.value = '';
}

async function testProvider(providerId) {
    const modelSel = document.getElementById(`pc-test-model-${providerId}`);
    const msg = document.getElementById(`pc-test-msg-${providerId}`);
    const resultPre = document.getElementById(`pc-test-result-${providerId}`);
    const model = modelSel.value;

    if (!model) {
        msg.textContent = 'Selecciona un modelo';
        msg.className = 'pc-msg error';
        return;
    }

    msg.textContent = 'Enviando test...';
    msg.className = 'pc-msg';
    resultPre.style.display = 'none';

    try {
        const result = await api(`/admin/api/providers/${providerId}/test`, 'POST', { model });

        if (result.success) {
            msg.innerHTML = `<span style="color:var(--success)">${result.latency_ms}ms · ${result.tokens} tokens</span>`;
            resultPre.textContent = result.response;
            resultPre.style.display = 'block';
        } else {
            msg.innerHTML = `<span style="color:var(--danger)">Error</span>`;
            resultPre.textContent = result.error;
            resultPre.style.display = 'block';
        }
    } catch (e) {
        msg.textContent = 'Error: ' + e.message;
        msg.className = 'pc-msg error';
    }
}

async function saveProviderModels(providerId) {
    const grid = document.getElementById(`pc-grid-${providerId}`);
    const msg = document.getElementById(`pc-models-msg-${providerId}`);
    const checkboxes = grid.querySelectorAll('input[type="checkbox"]');
    const allChecked = Array.from(checkboxes).every(cb => cb.checked);

    let enabledModels = [];
    if (!allChecked) {
        checkboxes.forEach(cb => {
            if (cb.checked) enabledModels.push(cb.value);
        });
    }
    // If all are checked, send empty array (means "all")

    msg.textContent = 'Guardando...';
    msg.className = 'pc-msg';

    await api(`/admin/api/providers/${providerId}/models`, 'PUT', { enabled_models: enabledModels });
    msg.textContent = allChecked
        ? 'Todos los modelos activados'
        : `${enabledModels.length} modelos activados`;
    msg.className = 'pc-msg success';

    // Refresh dropdowns
    setTimeout(() => location.reload(), 1500);
}

// --- Audio Section ---

let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;

async function loadAudioModels() {
    const data = await api('/admin/api/audio-models');
    const container = document.getElementById('audio-models-info');
    if (!container) return;

    const sttModels = (data.stt || []).map(m => `<code>${m.name}</code>`).join(', ');
    const ttsModels = (data.tts || []).map(m => {
        const voices = m.voices ? ` (${m.voices.length} voces)` : '';
        return `<code>${m.name}</code>${voices}`;
    }).join(', ');

    container.innerHTML = `
        <div style="display:flex;gap:1.5rem;flex-wrap:wrap;margin-bottom:0.5rem">
            <div style="font-size:0.85rem">
                <strong>STT:</strong> ${sttModels}
                <span class="badge active" style="margin-left:0.5rem">Whisper Local</span>
            </div>
            <div style="font-size:0.85rem">
                <strong>TTS:</strong> ${ttsModels}
                <span class="badge active" style="margin-left:0.5rem">macOS Say</span>
            </div>
        </div>
    `;
}

function toggleRecording() {
    if (isRecording) {
        stopRecording();
    } else {
        startRecording();
    }
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        mediaRecorder = new MediaRecorder(stream);
        audioChunks = [];

        mediaRecorder.ondataavailable = (e) => {
            if (e.data.size > 0) audioChunks.push(e.data);
        };

        mediaRecorder.onstop = () => {
            const blob = new Blob(audioChunks, { type: 'audio/webm' });
            // Create a file from the blob and set it on the file input
            const file = new File([blob], 'recording.webm', { type: 'audio/webm' });
            const dt = new DataTransfer();
            dt.items.add(file);
            document.getElementById('audio-stt-file').files = dt.files;

            stream.getTracks().forEach(t => t.stop());
        };

        mediaRecorder.start();
        isRecording = true;
        const btn = document.getElementById('audio-record-btn');
        btn.textContent = 'Detener';
        btn.style.background = 'var(--danger)';
        document.getElementById('audio-stt-status').textContent = 'Grabando...';
        document.getElementById('audio-stt-status').className = 'pc-msg';
    } catch (e) {
        document.getElementById('audio-stt-status').textContent = 'Error al acceder al micrófono: ' + e.message;
        document.getElementById('audio-stt-status').className = 'pc-msg error';
    }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
    isRecording = false;
    const btn = document.getElementById('audio-record-btn');
    btn.textContent = 'Grabar';
    btn.style.background = '';
    document.getElementById('audio-stt-status').textContent = 'Grabación lista. Haz clic en Transcribir.';
    document.getElementById('audio-stt-status').className = 'pc-msg success';
}

async function transcribeAudio() {
    const keyInput = document.getElementById('audio-key');
    const key = keyInput.value.trim();
    const fileInput = document.getElementById('audio-stt-file');
    const model = document.getElementById('audio-stt-model').value;
    const lang = document.getElementById('audio-stt-lang').value;
    const status = document.getElementById('audio-stt-status');
    const result = document.getElementById('audio-stt-result');

    if (!key) {
        status.textContent = 'Ingresa una API key';
        status.className = 'pc-msg error';
        return;
    }

    if (!fileInput.files || fileInput.files.length === 0) {
        status.textContent = 'Selecciona un archivo de audio o graba uno';
        status.className = 'pc-msg error';
        return;
    }

    status.textContent = 'Transcribiendo...';
    status.className = 'pc-msg';
    result.style.display = 'none';

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    formData.append('model', model);
    formData.append('language', lang);
    formData.append('response_format', 'json');

    try {
        const start = performance.now();
        const res = await fetch('/v1/audio/transcriptions', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${key}` },
            body: formData,
        });
        const elapsed = Math.round(performance.now() - start);
        const data = await res.json();

        if (res.ok) {
            status.innerHTML = `<span style="color:var(--success)">Transcrito en ${elapsed}ms</span>`;
            result.textContent = data.text || '(sin texto)';
            result.style.display = 'block';
        } else {
            status.textContent = 'Error: ' + (data.detail || JSON.stringify(data));
            status.className = 'pc-msg error';
        }
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.className = 'pc-msg error';
    }
}

async function generateSpeech() {
    const key = document.getElementById('audio-key').value.trim();
    const text = document.getElementById('audio-tts-text').value.trim();
    const voice = document.getElementById('audio-tts-voice').value;
    const speed = parseFloat(document.getElementById('audio-tts-speed').value);
    const status = document.getElementById('audio-tts-status');
    const player = document.getElementById('audio-tts-player');

    if (!key) {
        status.textContent = 'Ingresa una API key (misma que para STT)';
        status.className = 'pc-msg error';
        return;
    }

    if (!text) {
        status.textContent = 'Escribe un texto para convertir';
        status.className = 'pc-msg error';
        return;
    }

    status.textContent = 'Generando audio...';
    status.className = 'pc-msg';
    player.style.display = 'none';

    try {
        const start = performance.now();
        const res = await fetch('/v1/audio/speech', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${key}`,
            },
            body: JSON.stringify({
                model: 'tts-local',
                input: text,
                voice: voice,
                speed: speed,
                response_format: 'wav',
            }),
        });
        const elapsed = Math.round(performance.now() - start);

        if (res.ok) {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            player.src = url;
            player.style.display = 'block';
            player.play();
            status.innerHTML = `<span style="color:var(--success)">Generado en ${elapsed}ms</span>`;
        } else {
            const data = await res.json();
            status.textContent = 'Error: ' + (data.detail || JSON.stringify(data));
            status.className = 'pc-msg error';
        }
    } catch (e) {
        status.textContent = 'Error: ' + e.message;
        status.className = 'pc-msg error';
    }
}

// Speed slider label
document.addEventListener('DOMContentLoaded', () => {
    const slider = document.getElementById('audio-tts-speed');
    const label = document.getElementById('audio-tts-speed-label');
    if (slider && label) {
        slider.addEventListener('input', () => {
            label.textContent = parseFloat(slider.value).toFixed(1) + 'x';
        });
    }
});

// --- Arena ---

let arenaPresets = [];
let arenaAbortControllers = [];
let arenaBattleId = null;

async function loadArenaPresets() {
    const data = await api('/admin/api/arena/presets');
    arenaPresets = [];
    const categories = data.categories || [];
    const presets = data.presets || {};

    // Populate category filter
    const filter = document.getElementById('arena-category-filter');
    if (filter) {
        for (const cat of categories) {
            const opt = document.createElement('option');
            opt.value = cat;
            opt.textContent = cat;
            filter.appendChild(opt);
        }
    }

    // Render preset chips
    const container = document.getElementById('arena-presets');
    if (!container) return;
    container.innerHTML = '';
    for (const cat of categories) {
        for (const p of (presets[cat] || [])) {
            arenaPresets.push(p);
            const chip = document.createElement('span');
            chip.className = 'arena-preset-chip';
            chip.dataset.category = p.category;
            chip.dataset.prompt = p.prompt;
            chip.textContent = `${p.category}: ${p.name}`;
            chip.onclick = () => {
                document.querySelectorAll('.arena-preset-chip').forEach(c => c.classList.remove('active'));
                chip.classList.add('active');
                document.getElementById('arena-prompt').value = p.prompt;
            };
            container.appendChild(chip);
        }
    }
}

function filterArenaPresets(category) {
    const chips = document.querySelectorAll('.arena-preset-chip');
    chips.forEach(c => {
        c.style.display = (category === 'all' || c.dataset.category === category) ? '' : 'none';
    });
}

function populateArenaModelSelects() {
    for (let i = 1; i <= 4; i++) {
        const sel = document.getElementById(`arena-model-${i}`);
        if (!sel) continue;
        const current = sel.value;
        const isOptional = i > 2;
        sel.innerHTML = isOptional ? '<option value="">-- Ninguno --</option>' : '<option value="">-- Seleccionar --</option>';

        for (const pg of cachedByProvider) {
            if (!pg.configured) continue;
            const models = pg.models_typed
                ? pg.models_typed.filter(m => m.type === 'language').map(m => m.name)
                : pg.models;
            if (models.length === 0) continue;
            const group = document.createElement('optgroup');
            group.label = pg.display_name;
            for (const m of models) {
                const opt = document.createElement('option');
                opt.value = `${pg.provider}/${m}`;
                opt.textContent = m;
                group.appendChild(opt);
            }
            sel.appendChild(group);
        }
        if (current) sel.value = current;
    }
}

function switchArenaTab(tab) {
    document.querySelectorAll('.arena-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.arena-tab-content').forEach(c => c.style.display = 'none');
    document.querySelector(`.arena-tab[onclick*="${tab}"]`).classList.add('active');
    document.getElementById(`arena-tab-${tab}`).style.display = '';

    if (tab === 'scorecard') loadArenaScorecard();
    if (tab === 'battle') loadArenaHistory();
}

function stopArenaBattle() {
    arenaAbortControllers.forEach(c => c.abort());
    arenaAbortControllers = [];
    document.getElementById('arena-run-btn').disabled = false;
    document.getElementById('arena-status').textContent = 'Detenido';
}

async function runArenaBattle() {
    const key = document.getElementById('arena-key').value.trim();
    const prompt = document.getElementById('arena-prompt').value.trim();
    const temp = parseFloat(document.getElementById('arena-temp').value) || 0.7;
    const maxTokens = parseInt(document.getElementById('arena-max-tokens').value) || 2048;

    if (!key) { document.getElementById('arena-status').textContent = 'Ingresa una API key'; return; }
    if (!prompt) { document.getElementById('arena-status').textContent = 'Ingresa un prompt'; return; }

    // Collect selected models
    const models = [];
    for (let i = 1; i <= 4; i++) {
        const val = document.getElementById(`arena-model-${i}`).value;
        if (val) {
            const [provider, ...modelParts] = val.split('/');
            models.push({ provider, model: modelParts.join('/'), selectValue: val });
        }
    }
    if (models.length < 2) {
        document.getElementById('arena-status').textContent = 'Selecciona al menos 2 modelos';
        return;
    }

    // Determine category
    const activePreset = document.querySelector('.arena-preset-chip.active');
    const category = activePreset ? activePreset.dataset.category : 'custom';

    // Create battle in DB
    const battleRes = await api('/admin/api/arena/battles', 'POST', {
        prompt, category, temperature: temp, max_tokens: maxTokens,
    });
    arenaBattleId = battleRes.id;

    document.getElementById('arena-run-btn').disabled = true;
    arenaAbortControllers = [];

    // Build grid
    const grid = document.getElementById('arena-grid');
    grid.className = `arena-grid${models.length === 3 ? ' arena-grid-3' : models.length === 4 ? ' arena-grid-4' : ''}`;
    grid.innerHTML = models.map((m, idx) => `
        <div class="arena-panel" id="arena-panel-${idx}">
            <div class="arena-panel-header">
                <span>${m.provider}/${m.model}</span>
                <span class="arena-tag" id="arena-tag-${idx}">queued</span>
            </div>
            <div class="arena-metrics">
                <div class="arena-metric"><div class="arena-metric-value" id="arena-ttft-${idx}">-</div><div class="arena-metric-label">TTFT</div></div>
                <div class="arena-metric"><div class="arena-metric-value" id="arena-tps-${idx}">-</div><div class="arena-metric-label">t/s</div></div>
                <div class="arena-metric"><div class="arena-metric-value" id="arena-tokens-${idx}">-</div><div class="arena-metric-label">Tokens</div></div>
                <div class="arena-metric"><div class="arena-metric-value" id="arena-total-${idx}">-</div><div class="arena-metric-label">Total</div></div>
                <div class="arena-metric"><div class="arena-metric-value" id="arena-cost-${idx}">-</div><div class="arena-metric-label">Costo</div></div>
            </div>
            <div class="arena-response" id="arena-response-${idx}">Esperando...</div>
            <div class="arena-rating" id="arena-rating-${idx}">
                <span class="arena-rating-label">Rating:</span>
                ${[1,2,3,4,5].map(r => `<button class="arena-rating-btn" onclick="rateArenaResult(${idx}, ${r})" data-rating="${r}">${r}</button>`).join('')}
            </div>
        </div>
    `).join('');

    // Determine execution order: local models sequential, cloud parallel
    const localModels = [];
    const cloudModels = [];
    const providerLocalMap = {};
    for (const p of cachedProviders) {
        providerLocalMap[p.name] = p.is_local;
    }

    models.forEach((m, idx) => {
        if (providerLocalMap[m.provider]) {
            localModels.push({ ...m, idx });
        } else {
            cloudModels.push({ ...m, idx });
        }
    });

    const status = document.getElementById('arena-status');

    // Run local models sequentially
    for (const m of localModels) {
        status.textContent = `Ejecutando ${m.provider}/${m.model}...`;
        await runArenaModel(m.idx, m.provider, m.model, prompt, temp, maxTokens, key);
    }

    // Run cloud models in parallel
    if (cloudModels.length > 0) {
        status.textContent = `Ejecutando ${cloudModels.length} modelos cloud en paralelo...`;
        await Promise.all(cloudModels.map(m =>
            runArenaModel(m.idx, m.provider, m.model, prompt, temp, maxTokens, key)
        ));
    }

    // Highlight winners
    highlightArenaWinners(models.length);

    document.getElementById('arena-run-btn').disabled = false;
    status.textContent = 'Batalla completada';
    loadArenaHistory();
}

// Store result IDs for rating
const arenaResultIds = {};

async function runArenaModel(idx, provider, model, prompt, temperature, maxTokens, apiKey) {
    const controller = new AbortController();
    arenaAbortControllers.push(controller);

    const responseEl = document.getElementById(`arena-response-${idx}`);
    const tagEl = document.getElementById(`arena-tag-${idx}`);
    tagEl.textContent = 'running';
    tagEl.className = 'arena-tag streaming';
    responseEl.textContent = 'Esperando respuesta...';

    const startTime = performance.now();

    // Send as provider:model to bypass routing and hit the provider directly
    const requestModel = `${provider}:${model}`;

    try {
        const res = await fetch('/v1/chat/completions', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${apiKey}`,
            },
            body: JSON.stringify({
                model: requestModel,
                stream: false,
                temperature,
                max_tokens: maxTokens,
                messages: [{ role: 'user', content: prompt }],
            }),
            signal: controller.signal,
        });

        if (!res.ok) {
            const err = await res.text();
            throw new Error(`HTTP ${res.status}: ${err.substring(0, 200)}`);
        }

        const data = await res.json();
        const totalTimeMs = Math.round(performance.now() - startTime);
        const totalTimeSec = totalTimeMs / 1000;

        const fullText = data.choices?.[0]?.message?.content || '';
        const usage = data.usage || {};
        const completionTokens = usage.completion_tokens || 0;
        const tps = totalTimeSec > 0 ? (completionTokens / totalTimeSec).toFixed(1) : '0';
        const costUsd = usage.cost || 0;

        document.getElementById(`arena-ttft-${idx}`).textContent = totalTimeMs;
        document.getElementById(`arena-tps-${idx}`).textContent = tps;
        document.getElementById(`arena-tokens-${idx}`).textContent = completionTokens;
        document.getElementById(`arena-total-${idx}`).textContent = totalTimeSec.toFixed(1) + 's';
        document.getElementById(`arena-cost-${idx}`).textContent = costUsd > 0 ? '$' + costUsd.toFixed(4) : '-';

        tagEl.textContent = 'done';
        tagEl.className = 'arena-tag done';
        responseEl.innerHTML = renderArenaMarkdown(fullText);

        // Save result to DB
        if (arenaBattleId) {
            const resData = await api(`/admin/api/arena/battles/${arenaBattleId}/results`, 'POST', {
                provider,
                model,
                ttft_ms: totalTimeMs,
                tokens_per_sec: parseFloat(tps),
                completion_tokens: completionTokens,
                total_time_ms: totalTimeMs,
                cost_usd: costUsd,
                response_text: fullText,
                status: 'success',
            });
            arenaResultIds[idx] = resData.id;
        }

    } catch (e) {
        if (e.name === 'AbortError') {
            tagEl.textContent = 'stopped';
            tagEl.className = 'arena-tag error';
        } else {
            tagEl.textContent = 'error';
            tagEl.className = 'arena-tag error';
            responseEl.textContent = `Error: ${e.message}`;
            // Save error result
            if (arenaBattleId) {
                const resData = await api(`/admin/api/arena/battles/${arenaBattleId}/results`, 'POST', {
                    provider, model,
                    response_text: e.message,
                    status: 'error',
                });
                arenaResultIds[idx] = resData.id;
            }
        }
    }
}

function highlightArenaWinners(count) {
    const metrics = ['ttft', 'tps', 'tokens', 'total'];
    const lowerBetter = ['ttft', 'total'];

    for (const metric of metrics) {
        const values = [];
        for (let i = 0; i < count; i++) {
            const el = document.getElementById(`arena-${metric}-${i}`);
            const val = parseFloat(el?.textContent);
            values.push(isNaN(val) ? null : val);
        }
        if (values.every(v => v === null)) continue;
        const filtered = values.filter(v => v !== null);
        const best = lowerBetter.includes(metric) ? Math.min(...filtered) : Math.max(...filtered);
        for (let i = 0; i < count; i++) {
            if (values[i] === best) {
                const el = document.getElementById(`arena-${metric}-${i}`);
                if (el) el.classList.add('winner');
            }
        }
    }
}

async function rateArenaResult(panelIdx, rating) {
    const resultId = arenaResultIds[panelIdx];
    if (!resultId) return;

    await api(`/admin/api/arena/results/${resultId}/rate`, 'PUT', { rating });

    // Update button visual
    const ratingContainer = document.getElementById(`arena-rating-${panelIdx}`);
    ratingContainer.querySelectorAll('.arena-rating-btn').forEach(btn => {
        const r = parseInt(btn.dataset.rating);
        btn.classList.toggle('selected', r <= rating);
    });
}

function renderArenaMarkdown(text) {
    return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

async function loadArenaHistory() {
    const data = await api('/admin/api/arena/battles?limit=20');
    const tbody = document.getElementById('arena-history-body');
    if (!tbody) return;

    tbody.innerHTML = (data || []).map((b, i) => {
        const models = (b.results || []).map(r => {
            const ratingStr = r.rating ? ` (${r.rating}/5)` : '';
            return `<code>${r.provider}/${r.model}</code>${ratingStr}`;
        }).join(', ');
        const date = new Date(b.created_at).toLocaleString();
        return `<tr>
            <td>${b.id}</td>
            <td title="${(b.prompt || '').replace(/"/g, '&quot;')}">${(b.prompt || '').substring(0, 60)}${(b.prompt || '').length > 60 ? '...' : ''}</td>
            <td>${b.category}</td>
            <td>${models}</td>
            <td style="font-size:0.8rem">${date}</td>
        </tr>`;
    }).join('');
}

async function loadArenaScorecard() {
    const minBattles = parseInt(document.getElementById('scorecard-min-battles')?.value) || 1;
    const data = await api(`/admin/api/arena/scorecard?min_battles=${minBattles}`);
    const container = document.getElementById('scorecard-table-container');
    if (!container) return;

    if (!data || data.length === 0) {
        container.innerHTML = '<p class="section-desc">No hay datos suficientes. Ejecuta batallas y califica resultados.</p>';
        return;
    }

    // Build pivot: models as rows, categories as columns
    const categories = [...new Set(data.map(r => r.category))].sort();
    const modelKeys = [...new Set(data.map(r => `${r.provider}/${r.model}`))];

    // Build lookup
    const lookup = {};
    for (const r of data) {
        const key = `${r.provider}/${r.model}`;
        if (!lookup[key]) lookup[key] = {};
        lookup[key][r.category] = r;
    }

    // Compute overall avg for sorting
    const modelAvgs = modelKeys.map(key => {
        const cats = Object.values(lookup[key]);
        const avg = cats.reduce((s, c) => s + c.avg_rating, 0) / cats.length;
        return { key, avg };
    }).sort((a, b) => b.avg - a.avg);

    let html = `<table class="scorecard-table"><thead><tr><th>Modelo</th>`;
    for (const cat of categories) html += `<th>${cat}</th>`;
    html += `<th>Promedio</th><th>Batallas</th></tr></thead><tbody>`;

    for (const { key } of modelAvgs) {
        const row = lookup[key];
        html += `<tr><td style="text-align:left;font-weight:600">${key}</td>`;
        let totalRating = 0, totalCount = 0, totalBattles = 0;
        for (const cat of categories) {
            if (row[cat]) {
                const r = row[cat];
                const cls = r.avg_rating >= 4 ? 'high' : r.avg_rating >= 3 ? 'mid' : 'low';
                html += `<td><span class="scorecard-cell ${cls}">${r.avg_rating}</span><br><span style="font-size:0.7rem;color:var(--text-dim)">${r.count} bat · ${r.avg_tps} t/s</span></td>`;
                totalRating += r.avg_rating * r.count;
                totalCount += r.count;
                totalBattles += r.count;
            } else {
                html += '<td>-</td>';
            }
        }
        const avg = totalCount > 0 ? (totalRating / totalCount).toFixed(2) : '-';
        const avgCls = avg >= 4 ? 'high' : avg >= 3 ? 'mid' : avg !== '-' ? 'low' : '';
        html += `<td><span class="scorecard-cell ${avgCls}">${avg}</span></td>`;
        html += `<td>${totalBattles}</td></tr>`;
    }

    html += '</tbody></table>';
    container.innerHTML = html;
}

async function loadArenaRecommendations() {
    const srId = document.getElementById('rec-smart-route')?.value;
    const container = document.getElementById('recommendations-container');
    if (!srId || !container) {
        if (container) container.innerHTML = '<p class="section-desc">Selecciona un Smart Route.</p>';
        return;
    }

    const data = await api(`/admin/api/arena/recommendations/${srId}`);
    if (!data || !data.recommendations) {
        container.innerHTML = '<p class="section-desc">No se pudieron obtener recomendaciones.</p>';
        return;
    }

    const recs = data.recommendations;
    if (recs.length === 0) {
        container.innerHTML = '<p class="section-desc">Este Smart Route no tiene intenciones configuradas.</p>';
        return;
    }

    container.innerHTML = recs.map(r => {
        const currentStr = r.current_provider && r.current_model
            ? `${r.current_provider}/${r.current_model}${r.current_rating ? ' (' + r.current_rating + '/5)' : ''}`
            : '(sin asignar)';
        const recStr = r.recommended_provider && r.recommended_model
            ? `${r.recommended_provider}/${r.recommended_model} (${r.recommended_rating}/5)`
            : '(sin datos)';
        const impCls = r.improvement > 0 ? 'positive' : r.improvement < 0 ? 'negative' : 'neutral';
        const impStr = r.improvement !== null ? (r.improvement > 0 ? '+' : '') + r.improvement : '-';
        const canApply = r.recommended_provider && r.recommended_model
            && (r.recommended_provider !== r.current_provider || r.recommended_model !== r.current_model);

        return `<div class="recommendation-row">
            <span class="rec-intent">${r.intent_name}</span>
            <span class="rec-current">${currentStr}</span>
            <span class="rec-arrow">&rarr;</span>
            <span class="rec-recommended">${recStr}</span>
            <span class="rec-improvement ${impCls}">${impStr}</span>
            ${canApply ? `<button class="btn-small" onclick="applyArenaRecommendation(${data.smart_route_id}, '${r.intent_name}', '${r.recommended_provider}', '${r.recommended_model}')">Aplicar</button>` : ''}
        </div>`;
    }).join('');
}

async function applyArenaRecommendation(smartRouteId, intentName, provider, model) {
    if (!confirm(`¿Actualizar intent "${intentName}" a ${provider}/${model}?`)) return;
    const res = await api('/admin/api/arena/apply-recommendation', 'POST', {
        smart_route_id: smartRouteId,
        intent_name: intentName,
        provider,
        model,
    });
    if (res.status === 'ok') {
        alert(`Intent "${intentName}" actualizado a ${provider}/${model}`);
        loadArenaRecommendations();
    }
}

// --- Dashboard Overview ---

async function loadDashboardOverview() {
    const data = await api('/admin/api/analytics?days=1');
    if (!data || !data.summary) return;

    const s = data.summary;
    const todayEl = document.getElementById('dash-today');
    if (todayEl) {
        todayEl.innerHTML = `
            <div class="dash-today-stat">
                <span class="stat-value">${s.total_requests}</span>
                <span class="stat-label">Requests</span>
            </div>
            <div class="dash-today-stat">
                <span class="stat-value">$${s.total_cost}</span>
                <span class="stat-label">Costo</span>
            </div>
            <div class="dash-today-stat">
                <span class="stat-value">${s.total_tokens.toLocaleString()}</span>
                <span class="stat-label">Tokens</span>
            </div>
            <div class="dash-today-stat">
                <span class="stat-value">${s.avg_latency}ms</span>
                <span class="stat-label">Latencia</span>
            </div>
            <div class="dash-today-stat">
                <span class="stat-value${s.error_count > 0 ? ' style="color:var(--danger)"' : ''}">${s.error_count}</span>
                <span class="stat-label">Errores</span>
            </div>
        `;
    }

    const modelsBody = document.getElementById('dash-top-models');
    if (modelsBody) {
        const models = (data.by_model || []).slice(0, 8);
        if (models.length === 0) {
            modelsBody.innerHTML = '<tr><td colspan="6" style="color:var(--text-dim);text-align:center">Sin actividad hoy</td></tr>';
        } else {
            modelsBody.innerHTML = models.map(m => `<tr>
                <td><code>${m.model}</code></td>
                <td>${m.provider}</td>
                <td>${m.requests}</td>
                <td>${m.tokens.toLocaleString()}</td>
                <td>$${m.cost}</td>
                <td>${m.avg_latency}ms</td>
            </tr>`).join('');
        }
    }
}

// --- Section Navigation ---

function navigateTo(sectionId) {
    // Hide all sections, show target
    document.querySelectorAll('main > section').forEach(s => s.classList.remove('active'));
    const target = document.getElementById(sectionId);
    if (target) target.classList.add('active');

    // Update nav active state
    document.querySelectorAll('nav a').forEach(a => {
        a.classList.toggle('active', a.dataset.section === sectionId);
    });

    // Update URL hash without scrolling
    history.replaceState(null, '', '#' + sectionId);

    // Lazy-load section data
    if (sectionId === 'dashboard') loadDashboardOverview();
    if (sectionId === 'analytics') loadAnalytics(getCurrentAnalyticsDays());
    if (sectionId === 'arena') { loadArenaHistory(); }
    if (sectionId === 'audio') loadAudioModels();
}

function getCurrentAnalyticsDays() {
    const active = document.querySelector('.range-btn.active');
    return active ? parseInt(active.dataset.days) : 7;
}

function initNavigation() {
    // Convert nav links to section navigation
    document.querySelectorAll('nav a').forEach(a => {
        const href = a.getAttribute('href');
        if (href && href.startsWith('#')) {
            const sectionId = href.slice(1);
            a.dataset.section = sectionId;
            a.removeAttribute('href');
            a.addEventListener('click', (e) => {
                e.preventDefault();
                navigateTo(sectionId);
            });
        }
    });

    // Navigate to hash or default to dashboard
    const hash = location.hash.slice(1);
    const validSections = [...document.querySelectorAll('main > section')].map(s => s.id);
    navigateTo(validSections.includes(hash) ? hash : 'dashboard');
}

// --- Boot ---
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initDropdowns().then(() => {
        populateArenaModelSelects();
    });
    loadArenaPresets();
});
