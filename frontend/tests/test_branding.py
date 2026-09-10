"""Tests del logotipo.

Lo que se comprueba aqui no es como se ve, sino que nada del fichero acabe
pintado como texto en la portada.
"""

from __future__ import annotations

from futbol_front import branding


def test_un_comentario_del_svg_no_acaba_en_la_pantalla() -> None:
    # Fallo real: Streamlit pasa el HTML por su procesador de markdown antes de
    # pintarlo, y ahi un comentario XML no se ignora. El de nuestro logotipo
    # llevaba guiones, asi que salio convertido en una lista con vinetas encima
    # del titulo, con las letras cayendo en columna por la izquierda.
    svg = (
        "<!-- Generator: Adobe Illustrator\n - Un lienzo cuadrado\n -->"
        '<svg viewBox="0 0 48 48"><circle cx="24" cy="24" r="20"/></svg>'
    )

    limpio = branding._limpiar_svg(svg)

    assert "Generator" not in limpio
    assert "lienzo" not in limpio
    assert "<circle" in limpio


def test_se_quitan_la_declaracion_xml_y_el_doctype() -> None:
    # Los exportadores los ponen siempre, y dentro de un markdown se leen como
    # texto igual que el comentario.
    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/svg11.dtd">'
        '<svg viewBox="0 0 48 48"><path d="M4 24h40"/></svg>'
    )

    limpio = branding._limpiar_svg(svg)

    assert limpio.startswith("<svg")
    assert "DOCTYPE" not in limpio


def test_un_svg_ya_limpio_no_se_toca() -> None:
    svg = '<svg viewBox="0 0 48 48"><path d="M4 24h40"/></svg>'

    assert branding._limpiar_svg(svg) == svg


def test_el_logotipo_del_proyecto_no_lleva_texto_suelto() -> None:
    # El fichero que se sirve de verdad. Si alguien vuelve a documentar dentro
    # del SVG, este test lo para antes de que llegue a la portada.
    html = branding.logo_html()

    assert "<!--" not in html
    assert "<svg" in html


def test_sin_fichero_se_dibuja_un_hueco_en_lugar_de_romperse(monkeypatch) -> None:
    # Un logotipo que falta no puede tumbar la cabecera de la aplicacion.
    from pathlib import Path

    branding.logo_html.cache_clear()
    monkeypatch.setattr(branding, "ASSETS", Path("/no/existe"))
    try:
        html = branding.logo_html()
    finally:
        branding.logo_html.cache_clear()

    assert "<svg" in html
    assert "FA" in html
