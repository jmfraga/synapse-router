const API = '';

async function api(path, method = 'GET', body = null) {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(API + path, opts);
    return res.json();
}

// Providers
async function toggleProvider(id, enable) {
    await api(`/admin/api/providers/${id}`, 'PUT', { is_enabled: enable });
    location.reload();
}

// Routes
function showRouteForm() {
    document.getElementById('route-form').style.display = 'block';
}

async function createRoute() {
    const name = document.getElementById('route-name').value;
    const pattern = document.getElementById('route-pattern').value;
    const chain = document.getElementById('route-chain').value;
    const priority = parseInt(document.getElementById('route-priority').value);

    try {
        const parsed = JSON.parse(chain);
        await api('/admin/api/routes', 'POST', {
            name, model_pattern: pattern, provider_chain: parsed, priority
        });
        location.reload();
    } catch (e) {
        alert('Error en JSON de cadena: ' + e.message);
    }
}

async function deleteRoute(id) {
    if (!confirm('¿Eliminar esta ruta?')) return;
    await api(`/admin/api/routes/${id}`, 'DELETE');
    location.reload();
}

// API Keys
async function createKey() {
    const name = document.getElementById('key-name').value;
    const service = document.getElementById('key-service').value;
    const models = document.getElementById('key-models').value;

    if (!name || !service) { alert('Nombre y servicio requeridos'); return; }

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

// Metrics
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

// Playground
async function sendPlayground() {
    const key = document.getElementById('pg-key').value;
    const model = document.getElementById('pg-model').value;
    const message = document.getElementById('pg-message').value;
    const stream = document.getElementById('pg-stream').checked;
    const output = document.getElementById('pg-output');

    if (!key || !model || !message) { alert('Completa todos los campos'); return; }

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
