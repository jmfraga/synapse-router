const API = '';

// --- Cached data ---
let cachedModels = [];          // flat list of all model names
let cachedByProvider = [];      // [{provider, display_name, configured, models}]
let cachedProviders = [];       // from /api/providers

// --- Generic API helper ---
async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
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
function populateModelSelect(selectId, byProvider, flat) {
    const el = document.getElementById(selectId);
    if (!el) return;

    // Keep the first default option
    while (el.options.length > 1) el.remove(1);

    if (byProvider && byProvider.length > 0) {
        for (const pg of byProvider) {
            if (pg.models.length === 0) continue;
            const group = document.createElement('optgroup');
            const status = pg.configured ? '' : ' (sin key)';
            group.label = `${pg.display_name}${status}`;
            for (const m of pg.models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                if (!pg.configured) opt.disabled = true;
                group.appendChild(opt);
            }
            el.appendChild(group);
        }
    } else {
        for (const m of flat) {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            el.appendChild(opt);
        }
    }
}

// --- Init: populate all dropdowns on page load ---
async function initDropdowns() {
    const [modelsData, servicesData, providersData] = await Promise.all([
        api('/admin/api/models'),
        api('/admin/api/services'),
        api('/admin/api/providers'),
    ]);

    cachedModels = modelsData.models || [];
    cachedByProvider = modelsData.by_provider || [];
    cachedProviders = providersData || [];

    // Populate model selects with optgroups
    populateModelSelect('route-pattern-select', cachedByProvider, cachedModels);
    populateModelSelect('pg-model', cachedByProvider, cachedModels);

    // Multi-select for API key allowed models
    createMultiSelect('key-models-ms', cachedModels, {
        allValue: '*',
        allLabel: '* (todos)',
        grouped: true,
        providerData: cachedByProvider,
    });

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
                if (pg.models.length === 0) continue;
                const group = document.createElement('optgroup');
                group.label = pg.display_name;
                for (const m of pg.models) {
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
        <select class="chain-provider">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeChainStep(this)">✕</button>
    `;
    builder.appendChild(div);

    // Populate the new chain-model select
    const modelSel = div.querySelector('.chain-model');
    populateSingleChainModel(modelSel);
}

function populateSingleChainModel(sel) {
    if (cachedByProvider.length > 0) {
        for (const pg of cachedByProvider) {
            if (pg.models.length === 0) continue;
            const group = document.createElement('optgroup');
            group.label = pg.display_name;
            for (const m of pg.models) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                group.appendChild(opt);
            }
            sel.appendChild(group);
        }
    }
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
async function createKey() {
    const name = document.getElementById('key-name').value.trim();

    const sel = document.getElementById('key-service-select');
    const inp = document.getElementById('key-service-input');
    const service = sel.value === '__new__' ? inp.value.trim() : sel.value;

    const msContainer = document.getElementById('key-models-ms');
    const models = msContainer?.getValue ? msContainer.getValue() : '*';

    const smartRouteVal = document.getElementById('key-smart-route')?.value;
    const smartRouteId = smartRouteVal ? parseInt(smartRouteVal) || null : null;

    if (!name || !service) {
        alert('Nombre y servicio son requeridos');
        return;
    }

    const body = { name, service, allowed_models: models };
    if (smartRouteId) body.smart_route_id = smartRouteId;

    const result = await api('/admin/api/keys', 'POST', body);

    document.getElementById('new-key-value').textContent = result.key;
    document.getElementById('new-key-display').style.display = 'block';
}

async function revokeKey(id) {
    if (!confirm('¿Revocar esta key? No se puede deshacer.')) return;
    await api(`/admin/api/keys/${id}`, 'DELETE');
    location.reload();
}

// --- Metrics ---
async function loadMetrics() {
    const data = await api('/admin/api/metrics');
    const container = document.getElementById('metrics-data');

    let html = '<h3>Por Provider</h3><table><thead><tr><th>Provider</th><th>Requests</th><th>Tokens</th><th>Costo</th><th>Latencia</th></tr></thead><tbody>';
    for (const p of data.by_provider) {
        html += `<tr><td>${p.provider}</td><td>${p.requests}</td><td>${p.tokens}</td><td>$${p.cost}</td><td>${p.avg_latency}ms</td></tr>`;
    }
    html += '</tbody></table>';

    html += '<h3 style="margin-top:1.5rem">Requests Recientes</h3><table><thead><tr><th>Hora</th><th>Provider</th><th>Modelo</th><th>Tokens</th><th>Latencia</th><th>Costo</th><th>Estado</th></tr></thead><tbody>';
    for (const l of data.recent.slice(0, 20)) {
        const time = new Date(l.created_at).toLocaleString('es');
        html += `<tr><td>${time}</td><td>${l.provider}</td><td>${l.model}</td><td>${l.tokens}</td><td>${l.latency_ms}ms</td><td>$${l.cost_usd}</td><td>${l.status}</td></tr>`;
    }
    html += '</tbody></table>';
    container.innerHTML = html;
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

    // Populate classifier model select if empty
    const sel = document.getElementById('sr-classifier');
    if (sel.options.length <= 1) {
        populateModelSelect('sr-classifier', cachedByProvider, cachedModels);
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
                    <select class="chain-provider">
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
        <select class="chain-provider">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeIntentChainStep(this)">✕</button>
    `;
    stepsContainer.appendChild(div);
    populateSingleChainModel(div.querySelector('.chain-model'));
}

function removeIntentChainStep(btn) {
    const steps = btn.closest('.intent-chain-steps');
    if (steps.children.length > 1) {
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
        <select class="chain-provider">
            <option value="">-- Provider --</option>
            ${providerOptions}
        </select>
        <select class="chain-model">
            <option value="">-- Modelo --</option>
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeDefaultChainStep(this)">✕</button>
    `;
    container.appendChild(div);
    populateSingleChainModel(div.querySelector('.chain-model'));
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
    document.getElementById('sr-classifier').value = data.classifier_model;

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
    document.getElementById('sr-intents').innerHTML = '';
    document.getElementById('sr-default-chain').innerHTML = '';
}

async function submitSmartRoute() {
    const editId = document.getElementById('sr-edit-id').value;
    const name = document.getElementById('sr-name').value.trim();
    const trigger = document.getElementById('sr-trigger').value.trim();
    const classifier = document.getElementById('sr-classifier').value;

    if (!name || !trigger || !classifier) {
        alert('Nombre, modelo trigger, y clasificador son requeridos');
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
    const body = {
        name, trigger_model: trigger, classifier_model: classifier,
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

        const typeLabel = isLocal ? 'Local' : 'Cloud';
        const enabledBadge = p.is_enabled
            ? '<span class="badge active">Activo</span>'
            : '<span class="badge inactive">Inactivo</span>';

        card.innerHTML = `
            <div class="pc-header" onclick="this.parentElement.classList.toggle('open')">
                <h3>${p.display_name}</h3>
                <span style="font-size:0.75rem;color:var(--text-dim)">${typeLabel} · P${p.priority}</span>
                ${enabledBadge}
                ${!isLocal ? `<span class="pc-key-status ${keyStatusClass}">${keyStatusText}</span>` : ''}
                ${keyPreview && !isLocal ? `<code style="font-size:0.8rem;color:var(--text-dim)">${keyPreview}</code>` : ''}
                ${expiryBadge}
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
                </div>` : `<span id="pc-msg-${p.id}" class="pc-msg"></span>`}
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
                    <div class="pc-model-grid" id="pc-grid-${p.id}">
                        ${allModels.length > 0
                            ? allModels.map(m => {
                                const checked = enabledModels.length === 0 || enabledModels.includes(m);
                                const isCustom = (providerModels?.custom_models || []).includes(m);
                                return `<label class="pc-model-chip ${checked ? 'selected' : ''}" ${isCustom ? 'title="Añadido manualmente"' : ''}>
                                    <input type="checkbox" value="${m}" ${checked ? 'checked' : ''}
                                           onchange="this.parentElement.classList.toggle('selected', this.checked)" />
                                    ${isCustom ? '✎ ' : ''}${m}
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

        // Render model chips
        const grid = document.getElementById(`pc-grid-${providerId}`);
        grid.innerHTML = models.map(m => {
            const checked = enabled.length === 0 || enabled.includes(m);
            return `<label class="pc-model-chip ${checked ? 'selected' : ''}">
                <input type="checkbox" value="${m}" ${checked ? 'checked' : ''}
                       onchange="this.parentElement.classList.toggle('selected', this.checked)" />
                ${m}
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

// --- Boot ---
document.addEventListener('DOMContentLoaded', initDropdowns);
