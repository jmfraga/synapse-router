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

    // Populate service select
    const serviceSelect = document.getElementById('key-service-select');
    if (serviceSelect) {
        const services = servicesData.services || [];
        for (const s of services) {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            serviceSelect.appendChild(opt);
        }
    }

    // Populate chain-model selects in route builder
    populateChainModelSelects();
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

async function createRoute() {
    const name = document.getElementById('route-name').value.trim();

    const sel = document.getElementById('route-pattern-select');
    const inp = document.getElementById('route-pattern-input');
    const pattern = sel.style.display === 'none' ? inp.value.trim() : sel.value;

    if (!name || !pattern) {
        alert('Nombre y modelo/patrón son requeridos');
        return;
    }

    const chain = [];
    document.querySelectorAll('.chain-step').forEach(step => {
        const provider = step.querySelector('.chain-provider').value;
        const model = step.querySelector('.chain-model').value;
        if (provider && model) {
            chain.push({ provider, model });
        }
    });

    if (chain.length === 0) {
        alert('Agrega al menos un provider a la cadena');
        return;
    }

    const priority = parseInt(document.getElementById('route-priority').value) || 10;

    await api('/admin/api/routes', 'POST', {
        name, model_pattern: pattern, provider_chain: chain, priority
    });
    location.reload();
}

async function deleteRoute(id) {
    if (!confirm('¿Eliminar esta ruta?')) return;
    await api(`/admin/api/routes/${id}`, 'DELETE');
    location.reload();
}

// --- API Keys ---
function toggleServiceMode() {
    const sel = document.getElementById('key-service-select');
    const inp = document.getElementById('key-service-input');
    const link = sel.parentElement.querySelector('.toggle-link');

    if (sel.style.display === 'none') {
        sel.style.display = '';
        inp.style.display = 'none';
        inp.value = '';
        link.textContent = 'o crear nuevo';
    } else {
        sel.style.display = 'none';
        inp.style.display = '';
        link.textContent = 'o seleccionar existente';
    }
}

async function createKey() {
    const name = document.getElementById('key-name').value.trim();

    const sel = document.getElementById('key-service-select');
    const inp = document.getElementById('key-service-input');
    const service = sel.style.display === 'none' ? inp.value.trim() : sel.value;

    const msContainer = document.getElementById('key-models-ms');
    const models = msContainer?.getValue ? msContainer.getValue() : '*';

    if (!name || !service) {
        alert('Nombre y servicio son requeridos');
        return;
    }

    const result = await api('/admin/api/keys', 'POST', {
        name, service, allowed_models: models
    });

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

// --- Boot ---
document.addEventListener('DOMContentLoaded', initDropdowns);
