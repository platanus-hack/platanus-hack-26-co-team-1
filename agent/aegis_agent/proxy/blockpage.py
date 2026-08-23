from __future__ import annotations

from html import escape

from ..ui import tokens

# Esta pagina es el producto tanto como el detector: es el unico momento en que
# el empleado interactua con Aegis, y de como este escrita depende que entienda
# el riesgo o que solo sienta que le trabaron el trabajo.

_SHIELD_ICON = tokens.ESCUDO_SVG

_STYLES = f"""
{tokens.BASE_CSS}
body{{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:32px}}
.card{{width:100%;max-width:620px;background:{tokens.SURFACE};
border:1px solid {tokens.BORDER};border-radius:16px;padding:36px 40px;
box-shadow:{tokens.SOMBRA_PANEL}}}
.brand{{display:flex;align-items:center;gap:10px;margin-bottom:28px;
font-size:11px;font-weight:500;text-transform:uppercase;letter-spacing:0.13em;
color:{tokens.FAINT}}}
.brand svg{{width:20px;height:20px;color:{tokens.ACCENT}}}
h1{{margin:0 0 14px;font-size:23px;line-height:1.3}}
.lead{{margin:0 0 26px;color:{tokens.DIM};line-height:1.6;font-size:15px}}
.detail{{border-left:2px solid {tokens.ACCENT};padding:2px 0 2px 16px;margin:0 0 26px}}
.detail dt{{font-size:11px;font-weight:500;text-transform:uppercase;
letter-spacing:0.13em;color:{tokens.FAINT}}}
.detail dd{{margin:2px 0 14px;font-size:14px;font-family:{tokens.FUENTE_MONO};
color:{tokens.TEXT}}}
.detail dd:last-child{{margin-bottom:0}}
.lesson{{background:{tokens.SURFACE2};border:1px solid {tokens.BORDER};
border-radius:12px;padding:22px 24px}}
.lesson h2{{margin:0 0 10px;font-size:15px}}
.lesson p{{margin:0 0 12px;color:{tokens.DIM};line-height:1.65;font-size:14px}}
.lesson p:last-child{{margin-bottom:0}}
.foot{{margin-top:26px;font-size:12px;color:{tokens.FAINT};line-height:1.6}}
"""

def _page(title: str, lead: str, rows: list[tuple[str, str]], lesson_html: str, foot: str) -> str:
    details = "".join(
        f"<dt>{escape(label)}</dt><dd>{escape(value)}</dd>" for label, value in rows
    )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aegis — accion bloqueada</title><style>{_STYLES}</style></head>
<body><main class="card">
<div class="brand">{_SHIELD_ICON}<span>Aegis</span></div>
<h1>{escape(title)}</h1>
<p class="lead">{escape(lead)}</p>
<dl class="detail">{details}</dl>
{lesson_html}
<p class="foot">{escape(foot)}</p>
</main></body></html>"""


def destination_blocked(host: str, approved: list[str]) -> str:
    approved_list = ", ".join(approved) if approved else "ninguna por ahora"
    lesson = f"""<section class="lesson">
<h2>Por que este sitio esta restringido</h2>
<p>Este dominio ofrece un modelo de inteligencia artificial que la empresa no ha
aprobado. Lo que se escribe ahi puede quedar guardado en servidores de terceros y,
en varios de estos servicios, usarse para entrenar modelos.</p>
<p>Las herramientas aprobadas si estan cubiertas por un acuerdo con la empresa:
<strong>{escape(approved_list)}</strong>. Usalas con confianza, es exactamente para
eso que estan.</p>
</section>"""
    return _page(
        title="Este servicio de IA no esta aprobado por tu empresa",
        lead=(
            "Aegis interrumpio la conexion antes de que saliera cualquier dato. "
            "No es un castigo: es que este destino no paso la revision de seguridad."
        ),
        rows=[("Destino", host), ("Clasificacion", "IA no aprobada")],
        lesson_html=lesson,
        foot="El intento quedo registrado para tu empresa sin el contenido de lo que escribiste.",
    )


def content_blocked(
    host: str, rule_id: str, evidence: str, lesson: dict[str, str], aprobada: bool = True
) -> str:
    lesson_html = f"""<section class="lesson">
<h2>{escape(lesson["title"])}</h2>
<p>{escape(lesson["why"])}</p>
<p>{escape(lesson["what_to_do"])}</p>
</section>"""
    return _page(
        title="Lo que ibas a enviar contiene informacion que no debe salir",
        lead=(
            f"El destino ({host}) es una herramienta aprobada, asi que podes seguir "
            "usandola. Lo que Aegis freno es el dato, no la herramienta."
            if aprobada
            else (
                f"Aegis no te corta {host}: podes seguir usandolo para trabajo "
                "normal. Lo que freno es este envio en concreto, porque lleva "
                "informacion que no puede salir de la empresa."
            )
        ),
        rows=[
            ("Destino", host),
            ("Estado", "aprobada por tu empresa" if aprobada else "no aprobada"),
            ("Deteccion", rule_id),
            ("Evidencia", evidence),
        ],
        lesson_html=lesson_html,
        foot="Aegis nunca envio el contenido a ningun lado. El analisis ocurrio en tu equipo.",
    )
