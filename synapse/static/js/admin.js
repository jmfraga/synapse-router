const API = '';

// --- Cached data ---
let cachedModels = [];
let cachedProviders = [];

// --- Generic API helper ---
async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
    return res.json();
}

// --- Init: populate all dropdowns on page load ---
async function initDropdowns() {
    const [modelsData, servicesData, providersData] = await Promise.all([
        api('/admin/api/models'),
        api('/admin/api/services'),
        api('/admin/api/providers'),
    ]);

    cachedModels = modelsData.models || [];
    cachedProviders = providersData || [];

    // Populate model selects
    const modelSelects = ['route-pattern-select', 'pg-model', 'key-models'];
    for (const id of modelSelects) {
        const el = document.getElementById(id);
        if (!el) continue;

        if (id === 'key-models') {
            // key-models: keep "* (todos)" as first, add individual models
            for (const m of cachedModels) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                el.appendChild(opt);
            }
        } else {
            for (const m of cachedModels) {
                const opt = document.createElement('option');
                opt.value = m;
                opt.textContent = m;
                el.appendChild(opt);
            }
        }
    }

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
        // Keep first option, remove rest
        while (sel.options.length > 1) sel.remove(1);
        for (const m of cachedModels) {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            sel.appendChild(opt);
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
    const modelOptions = cachedModels
        .map(m => `<option value="${m}">${m}</option>`)
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
            ${modelOptions}
        </select>
        <button type="button" class="btn-small btn-danger" onclick="removeChainStep(this)">✕</button>
    `;
    builder.appendChild(div);
}

function removeChainStep(btn) {
    const builder = document.getElementById('route-chain-builder');
    if (builder.children.length > 1) {
        btn.closest('.chain-step').remove();
    }
}

async function createRoute() {
    const name = document.getElementById('route-name').value.trim();

    // Get pattern from select or input
    const sel = document.getElementById('route-pattern-select');
    const inp = document.getElementById('route-pattern-input');
    const pattern = sel.style.display === 'none' ? inp.value.trim() : sel.value;

    if (!name || !pattern) {
        alert('Nombre y modelo/patrón son requeridos');
        return;
    }

    // Build chain from visual builder
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

    // Get service from select or input
    const sel = document.getElementById('key-service-select');
    const inp = document.getElementById('key-service-input');
    const service = sel.style.display === 'none' ? inp.value.trim() : sel.value;

    const models = document.getElementById('key-models').value;

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
