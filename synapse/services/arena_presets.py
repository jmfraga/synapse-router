"""Arena battle presets — 23 prompts categorized for model evaluation."""

ARENA_PRESETS = [
    # --- Simple ---
    {
        "category": "simple",
        "name": "Traducción",
        "prompt": "Traduce al inglés: 'Buenos días, ¿cómo estás? Me gustaría reservar una mesa para dos personas a las ocho de la noche.'"
    },
    {
        "category": "simple",
        "name": "Sentimiento",
        "prompt": "Clasifica el sentimiento de cada frase como positivo, negativo o neutro:\n1. Me encantó la película, la recomiendo mucho.\n2. El servicio fue pésimo, nunca vuelvo.\n3. El paquete llegó el martes.\n4. ¡Qué increíble experiencia!\n5. No me gustó nada el sabor."
    },
    {
        "category": "simple",
        "name": "Resumen",
        "prompt": "Resume en máximo 3 oraciones: La inteligencia artificial generativa ha transformado múltiples industrias en los últimos años. Desde la creación de contenido hasta el diagnóstico médico, los modelos de lenguaje han demostrado capacidades que antes se consideraban exclusivas de los humanos. Sin embargo, también han surgido preocupaciones sobre el sesgo algorítmico, la privacidad de los datos y el impacto en el empleo. Expertos coinciden en que la regulación debe evolucionar al mismo ritmo que la tecnología para garantizar un uso ético y responsable."
    },
    {
        "category": "simple",
        "name": "Extracción JSON",
        "prompt": "Extrae los datos estructurados del siguiente texto y devuélvelos en JSON:\n\nEl paciente Juan Pérez, de 42 años, masculino, acudió el 10 de marzo de 2026. Peso: 78 kg, talla: 1.72 m, presión arterial: 130/85 mmHg. Diagnóstico: hipertensión arterial sistémica grado 1. Medicamento recetado: losartán 50 mg cada 24 horas."
    },
    {
        "category": "simple",
        "name": "Corrección",
        "prompt": "Corrige la ortografía y gramática del siguiente texto, devuelve solo el texto corregido:\n\nAyer fui ha el doctor por que me dolia mucho la caveza y el me dijo que tenia que tomar acetaminofen cada ocho oras y que si no se me quitava en tres dias que regresara para aserme unos estudios de sangre."
    },
    {
        "category": "simple",
        "name": "Nombres Creativos",
        "prompt": "Genera 5 nombres creativos para una cafetería temática de ciencia ficción ubicada en la Ciudad de México. Para cada nombre incluye una breve descripción de una línea."
    },
    # --- Medicine ---
    {
        "category": "medicine",
        "name": "STEMI",
        "prompt": "A 55-year-old male presents with acute chest pain radiating to the left arm, diaphoresis, and shortness of breath. ECG shows ST-elevation in leads II, III, and aVF. Troponin levels are elevated. Provide a differential diagnosis, immediate management plan, and explain the pathophysiology. Include drug dosages."
    },
    {
        "category": "medicine",
        "name": "Diabetes Pharma",
        "prompt": "Explain the mechanism of action of metformin in Type 2 Diabetes, including its effects on hepatic gluconeogenesis, AMPK activation, and gut microbiome. Compare with GLP-1 receptor agonists. When would you switch from metformin to insulin therapy?"
    },
    # --- Coding ---
    {
        "category": "coding",
        "name": "WebSocket",
        "prompt": "Write a Python async WebSocket server that: 1) Accepts connections and authenticates via JWT token in the first message, 2) Broadcasts messages to all authenticated clients in the same 'room', 3) Handles disconnections gracefully, 4) Includes rate limiting (max 10 msgs/sec per client). Use only the standard library and PyJWT."
    },
    {
        "category": "coding",
        "name": "Rust LRU",
        "prompt": "Implement a LRU Cache in Rust with O(1) get and put operations. It should be thread-safe using Arc and RwLock. Include proper error handling and unit tests. Explain your design decisions."
    },
    # --- Tool Use ---
    {
        "category": "tool_use",
        "name": "Multi-step",
        "prompt": "You have access to these tools:\n- search_web(query: str) -> list[str]: Search the web\n- get_weather(city: str) -> dict: Get current weather\n- calculate(expression: str) -> float: Evaluate math\n- send_email(to: str, subject: str, body: str) -> bool: Send email\n\nUser request: 'Check the weather in Tokyo and Mexico City, calculate the temperature difference in Fahrenheit, and if the difference is more than 20°F, draft an email to weather-alerts@company.com about it.'\n\nShow your reasoning step-by-step and output each tool call in JSON format."
    },
    {
        "category": "tool_use",
        "name": "Data Pipeline",
        "prompt": "You have these tools:\n- query_db(sql: str) -> list[dict]: Execute SQL query\n- create_chart(data: list, chart_type: str, title: str) -> str: Create chart, returns URL\n- send_slack(channel: str, message: str, attachments: list[str]) -> bool\n\nUser: 'Get last month sales by region from the sales table, create a bar chart, and post it to #sales-reports on Slack with a summary.'\n\nPlan and execute each step, showing exact tool calls with parameters."
    },
    # --- Reasoning ---
    {
        "category": "reasoning",
        "name": "River Puzzle",
        "prompt": "A farmer has a fox, a chicken, and a bag of grain. He needs to cross a river in a boat that can only carry him and one item at a time. If left alone, the fox will eat the chicken, and the chicken will eat the grain. But there's a twist: the boat has a small cage that can hold either the chicken OR the grain (not the fox) safely on the boat while the farmer makes an extra trip. What's the minimum number of crossings needed? Prove your answer is optimal."
    },
    {
        "category": "reasoning",
        "name": "Missing Dollar",
        "prompt": "Three people check into a hotel room that costs $30. They each pay $10. Later, the manager realizes the room only costs $25, so he gives $5 to the bellboy to return. The bellboy keeps $2 and gives each person $1 back. Now each person paid $9 (total $27), plus the bellboy has $2. That's $29. Where's the missing dollar? Explain clearly why this is a fallacy."
    },
    # --- Spanish ---
    {
        "category": "spanish",
        "name": "Clínica Rural",
        "prompt": "Eres un médico general en una clínica rural de México. Un paciente de 45 años llega con dolor abdominal agudo en el cuadrante inferior derecho, fiebre de 38.5°C, y náuseas desde hace 12 horas. No tienes acceso a tomografía. Describe tu abordaje diagnóstico, diagnósticos diferenciales, y plan de manejo con los recursos limitados disponibles. Responde en español."
    },
    {
        "category": "spanish",
        "name": "Urgencias Neuro",
        "prompt": "Eres un asistente médico experto. Un paciente de 60 años con antecedentes de hipertensión y diabetes tipo 2 presenta cefalea intensa de inicio súbito, rigidez de nuca y fotofobia. Glasgow 14. TA: 190/110 mmHg. Describe paso a paso: triaje, estudios de gabinete prioritarios, diagnósticos diferenciales (incluye hemorragia subaracnoidea, meningitis, crisis hipertensiva), y manejo inicial en urgencias. Responde en español con dosis de medicamentos."
    },
    {
        "category": "spanish",
        "name": "Contrato Legal",
        "prompt": "Redacta un contrato de prestación de servicios profesionales entre una empresa de tecnología (OpenClaw Tech S.A. de C.V.) y un desarrollador freelance. Incluye: objeto del contrato, vigencia de 6 meses, monto de $45,000 MXN mensuales, cláusula de confidencialidad, propiedad intelectual, causales de rescisión, y jurisdicción en Ciudad de México. Usa lenguaje jurídico mexicano apropiado."
    },
    {
        "category": "spanish",
        "name": "Bot Telegram",
        "prompt": "Escribe un bot de Telegram en Python usando python-telegram-bot que: 1) Responda a /start con un menú de opciones usando InlineKeyboard, 2) Tenga un comando /consulta que reciba texto libre y lo envíe a una API de Ollama local (localhost:11434), 3) Maneje errores y timeouts, 4) Incluya rate limiting de 5 mensajes por minuto por usuario. Comenta el código en español."
    },
    {
        "category": "spanish",
        "name": "Preeclampsia",
        "prompt": "Paciente femenina de 32 años, embarazo de 34 semanas, acude a urgencias con TA 160/100 mmHg, proteinuria +++, edema generalizado, y refiere visión borrosa y dolor en epigastrio. Laboratorios: plaquetas 85,000, TGO 280, TGP 310, DHL 650, creatinina 1.4. Analiza el caso: ¿Cuál es el diagnóstico más probable? Describe la fisiopatología, clasifica la severidad, indica el manejo inmediato incluyendo sulfato de magnesio y antihipertensivos con dosis, y define los criterios para interrupción del embarazo. Responde en español."
    },
    {
        "category": "spanish",
        "name": "Tool Use Médico",
        "prompt": "Tienes acceso a estas herramientas:\n- buscar_paciente(nombre: str, curp: str) -> dict: Busca en el expediente clínico\n- agendar_cita(paciente_id: str, especialidad: str, fecha: str, hora: str) -> dict: Agenda una cita médica\n- enviar_recordatorio(paciente_id: str, mensaje: str, via: str) -> bool: Envía recordatorio por SMS o WhatsApp\n- consultar_disponibilidad(especialidad: str, fecha: str) -> list[dict]: Muestra horarios disponibles\n\nSolicitud del usuario: 'Busca al paciente María García López con CURP GALM850315MDFRPR01, revisa si tiene cita pendiente de cardiología, si no tiene agéndale la próxima disponible esta semana, y envíale un recordatorio por WhatsApp.'\n\nMuestra tu razonamiento paso a paso y cada llamada a herramienta en formato JSON."
    },
    {
        "category": "spanish",
        "name": "Arquitectura Telemedicina",
        "prompt": "Explica en español y de forma detallada cómo implementar una arquitectura de microservicios para una plataforma de telemedicina que incluya: 1) Servicio de autenticación con JWT, 2) Servicio de expediente clínico electrónico, 3) Servicio de videoconsulta con WebRTC, 4) Servicio de recetas electrónicas con firma digital (e.firma SAT), 5) Gateway API con rate limiting. Usa Python/FastAPI, PostgreSQL y Redis. Incluye diagrama de arquitectura en formato texto y ejemplo de código para el servicio de autenticación."
    },
    {
        "category": "spanish",
        "name": "Interacciones Fármaco",
        "prompt": "Eres un farmacólogo clínico. Un paciente de 70 años polimedicado toma: metformina 850mg c/12h, enalapril 10mg c/12h, atorvastatina 40mg/noche, ácido acetilsalicílico 100mg/día, omeprazol 20mg/día, y sertralina 50mg/día. Ahora le recetan claritromicina 500mg c/12h por una infección respiratoria. Analiza todas las interacciones farmacológicas potenciales, clasifícalas por severidad, y sugiere alternativas terapéuticas si es necesario. Incluye mecanismos de interacción (CYP450, etc.). Responde en español."
    },
    # --- OpenClaw ---
    {
        "category": "openclaw",
        "name": "PM Delegación",
        "prompt": "Eres PM, el Project Manager de un sistema multi-agente. Recibes este mensaje del usuario:\n\n'Necesito que Iris le mande un recordatorio a mi esposa por WhatsApp de la cita con el cardiólogo mañana a las 4pm, que Atlas cree una tarea en el Kanban para revisar los backups del servidor, y que CHAPPiE revise si el endpoint /api/health del gateway está respondiendo correctamente.'\n\nTienes estas herramientas:\n- sessions_send(agent_id: str, message: str) -> dict: Envía mensaje a otro agente\n- sessions_spawn(agent_id: str, task: str) -> dict: Crea subagente temporal\n- kanban_create_task(title: str, assignee: str, priority: str) -> dict: Crea tarea\n\nPlanifica la delegación: decide qué agente maneja cada solicitud, en qué orden, y genera las llamadas a herramientas en JSON. Explica brevemente tu razonamiento."
    },
    {
        "category": "openclaw",
        "name": "Iris Conversación",
        "prompt": "Eres Iris, una asistente personal amable y eficiente que atiende por WhatsApp. El usuario te envía este audio transcrito:\n\n'Oye Iris, fíjate que ando buscando un restaurante italiano por la zona de Polanco para cenar el viernes con mi esposa, somos dos personas, algo no tan caro pero que esté bonito. Y aparte recuérdame que tengo que pasar por la farmacia a comprar el medicamento que me recetó el doctor, creo que era losartán.'\n\nResponde de forma natural, cálida y concisa (máximo 150 palabras). Separa las dos solicitudes: la del restaurante (ofrece ayuda concreta) y el recordatorio (confírmalo). Usa español mexicano coloquial pero profesional."
    },
    {
        "category": "openclaw",
        "name": "Atlas DevOps + Kanban",
        "prompt": "Eres Atlas, agente de DevOps e infraestructura. Tienes estas herramientas:\n- kanban_list_tasks(status: str, assignee: str) -> list[dict]: Lista tareas\n- kanban_update_task(task_id: str, status: str, notes: str) -> dict: Actualiza tarea\n- shell_exec(command: str) -> dict: Ejecuta comando en servidor (solo lectura)\n- http_check(url: str, timeout: int) -> dict: Verifica endpoint\n\nRecibiste esta instrucción del PM:\n'Revisa el estado de los servicios de OpenClaw en la RPi5. Verifica que el gateway (puerto 18789), el hub (puerto 8080) y contacts (puerto 3335) estén respondiendo. Si alguno falla, crea una tarea de alta prioridad en el Kanban. Después actualiza la tarea OC-147 como completada.'\n\nMuestra tu plan paso a paso y las llamadas a herramientas en JSON."
    },
    {
        "category": "openclaw",
        "name": "Argus Log Analysis",
        "prompt": "Eres Argus, el agente de QA y monitoreo. Analiza este fragmento de logs del gateway de OpenClaw y genera un reporte:\n\n```\n2026-04-02 02:00:01 [INFO] cron-argus: Starting daily health check\n2026-04-02 02:00:03 [OK] gateway: 18789 responding (latency: 45ms)\n2026-04-02 02:00:03 [OK] hub: 8080 responding (latency: 120ms)\n2026-04-02 02:00:04 [WARN] contacts: 3335 responding (latency: 2340ms)\n2026-04-02 02:00:05 [OK] ollama: 11434 responding, models loaded: 2\n2026-04-02 02:00:06 [ERROR] session iris-assistant: context_tokens=127450/128000 (99.6%) — CRITICAL\n2026-04-02 02:00:06 [WARN] session pm: context_tokens=98000/128000 (76.6%)\n2026-04-02 02:00:07 [OK] session atlas: context_tokens=12000/128000 (9.4%)\n2026-04-02 02:00:07 [WARN] memory-core: disk usage 89% on /home/jmfraga/.openclaw\n2026-04-02 02:00:08 [ERROR] whatsapp-channel: last_message_received=6h ago — possible disconnect\n```\n\nGenera: 1) Resumen ejecutivo, 2) Problemas críticos con prioridad, 3) Acciones recomendadas para cada problema, 4) Si alguno requiere escalamiento al owner."
    },
    {
        "category": "openclaw",
        "name": "CHAPPiE Code Review",
        "prompt": "Eres CHAPPiE, agente desarrollador. Revisa este fragmento de código Python de un endpoint del gateway de OpenClaw y señala problemas de seguridad, rendimiento y buenas prácticas:\n\n```python\n@router.post('/api/sessions/{agent_id}/send')\nasync def send_message(agent_id: str, request: Request):\n    body = await request.json()\n    message = body['message']\n    session_file = f'/home/jmfraga/.openclaw/agents/{agent_id}/sessions/current.jsonl'\n    \n    with open(session_file, 'a') as f:\n        f.write(json.dumps({'role': 'user', 'content': message, 'ts': str(datetime.now())}) + '\\n')\n    \n    cmd = f\"cd /home/jmfraga/.openclaw && node gateway.js process {agent_id} '{message}'\"\n    result = subprocess.run(cmd, shell=True, capture_output=True, timeout=30)\n    \n    return {'status': 'ok', 'response': result.stdout.decode()}\n```\n\nSé específico: señala cada issue, explica el riesgo, y proporciona el código corregido."
    },
    {
        "category": "openclaw",
        "name": "Phoenix Estrategia",
        "prompt": "Eres Phoenix, agente de marketing y estrategia de contenido. El usuario te dice por WhatsApp:\n\n'Phoenix, necesito que me ayudes a armar una estrategia de contenido para la cuenta de Instagram de SimAcademy. Es una academia de simulación médica en México, nuestro público son médicos residentes y estudiantes de medicina. Tenemos un presupuesto limitado y queremos crecer de 500 a 2000 seguidores en 3 meses. Dame un plan concreto con ideas de posts para las primeras 2 semanas.'\n\nResponde con un plan estructurado pero conciso. Incluye: estrategia general (3-4 líneas), calendario de las 2 semanas con tipo de contenido y copy sugerido para cada post. Usa español mexicano."
    },
]

ARENA_CATEGORIES = [
    "simple", "medicine", "coding", "tool_use", "reasoning", "spanish",
    "openclaw", "agentic", "creative", "analysis", "multimodal",
]
