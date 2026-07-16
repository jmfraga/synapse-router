"""Tests del manejo de razonamiento híbrido (GX10 vLLM / MLX / Nemotron)."""

from synapse.services.sanitizers import sanitize_response_data, split_think_block


def _resp(content=None, reasoning=None, reasoning_content=None):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if reasoning is not None:
        msg["reasoning"] = reasoning
    if reasoning_content is not None:
        msg["reasoning_content"] = reasoning_content
    return {"choices": [{"message": msg, "finish_reason": "stop"}]}


def test_split_think_block_basic():
    thinking, answer = split_think_block("déjame pensar...</think>La respuesta es 42.")
    assert thinking == "déjame pensar..."
    assert answer == "La respuesta es 42."


def test_split_no_block_passthrough():
    thinking, answer = split_think_block("respuesta directa")
    assert thinking == ""
    assert answer == "respuesta directa"


def test_inline_think_split_in_content():
    d = _resp(content="pensando paso a paso</think>\n\nContrato listo.")
    sanitize_response_data(d)
    assert d["choices"][0]["message"]["content"] == "Contrato listo."


def test_vllm_reasoning_field_dropped_when_content_ok():
    d = _resp(content="respuesta limpia", reasoning="pensamiento interno")
    sanitize_response_data(d)
    m = d["choices"][0]["message"]
    assert m["content"] == "respuesta limpia"
    assert "reasoning" not in m


def test_truncated_thinking_fallback_flagged():
    d = _resp(content="", reasoning="iba a la mitad del razonamiento")
    sanitize_response_data(d)
    c = d["choices"][0]["message"]["content"]
    assert c.startswith("[razonamiento truncado")
    assert "iba a la mitad" in c


def test_nemotron_reasoning_content_still_works():
    d = _resp(content="", reasoning_content="respuesta en reasoning_content")
    sanitize_response_data(d)
    assert "respuesta en reasoning_content" in d["choices"][0]["message"]["content"]
