"""Tests del guardarraíl de temporada del agente.

Verificado contra el modelo real (qwen2.5:3b): ni el prompt de sistema ni
repetir la temporada en cada herramienta bastan para que deje de mencionar
otra por su cuenta. Ante "el perfil de Pedri esta temporada" con datos de
2627, contestó "en la temporada 2023-2024 (2627)"; ante "como juega el
Barcelona" contestó "en la temporada 2023" sin mencionar 2627 en absoluto. Las
dos veces el texto de la herramienta llevaba "En la temporada 2627" delante.

Por eso el agente no confía en que el modelo respete el prompt: reescribe
cualquier temporada que aparezca en la respuesta final por la que de verdad
citó la última herramienta usada. Estas funciones son la parte pura y
comprobable de esa corrección; el resto de `agent.answer` depende de Ollama.
"""

from __future__ import annotations

from futbol_analytics.chat.agent import _fuerza_temporada, _ultima_temporada_citada


def _mensaje_herramienta(texto: str) -> dict[str, str]:
    return {"role": "tool", "content": texto, "name": "cualquiera"}


# --- _ultima_temporada_citada ------------------------------------------------


def test_lee_la_temporada_del_ultimo_resultado_de_herramienta() -> None:
    mensajes = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        _mensaje_herramienta("En la temporada 2627: Pedri (Barcelona, ESP-La Liga)..."),
    ]

    assert _ultima_temporada_citada(mensajes) == "2627"


def test_usa_la_ultima_si_hay_varias_llamadas_a_herramientas() -> None:
    mensajes = [
        _mensaje_herramienta("En la temporada 2526, Barcelona se agrupa como..."),
        {"role": "assistant", "content": "", "tool_calls": []},
        _mensaje_herramienta("En la temporada 2627: Pedri (Barcelona, ESP-La Liga)..."),
    ]

    assert _ultima_temporada_citada(mensajes) == "2627"


def test_sin_llamadas_a_herramientas_no_hay_temporada_que_citar() -> None:
    mensajes = [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "Hola"},
    ]

    assert _ultima_temporada_citada(mensajes) is None


# --- _fuerza_temporada --------------------------------------------------------


def test_corrige_un_rango_de_anos_inventado() -> None:
    # Lo que el modelo escribió de verdad contra datos de 2627.
    texto = "El perfil de Pedri en la temporada 2023-2024 (2627) muestra que es centrocampista."

    corregido = _fuerza_temporada(texto, "2627")

    assert "temporada 26/27" in corregido
    assert "2023-2024" not in corregido


def test_corrige_un_ano_suelto_inventado() -> None:
    texto = "En la temporada 2023, el Barcelona se agrupa como presión alta."

    corregido = _fuerza_temporada(texto, "2627")

    assert "temporada 26/27" in corregido
    assert "2023" not in corregido


def test_normaliza_la_temporada_correcta_al_formato_con_barra() -> None:
    # Aunque el modelo cite bien la temporada, se muestra como "26/27" y no
    # como el codigo crudo "2627", que a primera vista parece un año suelto.
    texto = "En la temporada 2627, el Barcelona se agrupa como presión alta."

    corregido = _fuerza_temporada(texto, "2627")

    assert "temporada 26/27" in corregido
    assert "2627" not in corregido


def test_no_toca_numeros_que_no_acompanan_a_la_palabra_temporada() -> None:
    # 2850 minutos no es una temporada: no debe tocarse por tener cuatro cifras.
    texto = "Pedri ha jugado 2850 minutos en la temporada 2023."

    corregido = _fuerza_temporada(texto, "2627")

    assert "2850 minutos" in corregido
    assert "temporada 26/27" in corregido
