from __future__ import annotations

from html import escape

from ..ui import tokens
from .metrics import Metrics

# El panel comparte lenguaje visual con la pagina de bloqueo y con el front
# principal a proposito: el empleado y el administrador ven el mismo producto
# desde dos lados. Los colores salen de ui/tokens.py, que es el espejo de
# frontend/tailwind.config.js.

_STYLES = f"""
{tokens.BASE_CSS}
body{{padding:40px 32px}}
.wrap{{max-width:1180px;margin:0 auto}}
header{{display:flex;align-items:baseline;justify-content:space-between;
border-bottom:1px solid {tokens.BORDER};padding-bottom:18px;margin-bottom:32px;
flex-wrap:wrap;gap:12px}}
.brand{{display:flex;align-items:center;gap:10px;font-size:11px;font-weight:500;
text-transform:uppercase;letter-spacing:0.13em;color:{tokens.FAINT}}}
.brand svg{{width:20px;height:20px;color:{tokens.ACCENT}}}
header .tenant{{font-size:13px;color:{tokens.DIM}}}
h1{{font-size:20px;margin:0}}

/* El interruptor. Es lo primero que se ve porque es lo unico que se aprieta. */
.mando{{display:flex;align-items:center;justify-content:space-between;gap:20px;
flex-wrap:wrap;background:{tokens.SURFACE};border:1px solid {tokens.BORDER};
border-radius:16px;padding:20px 24px;margin-bottom:28px;
box-shadow:{tokens.SOMBRA_PANEL}}}
.mando .luz{{display:flex;align-items:center;gap:12px}}
.punto{{width:11px;height:11px;border-radius:50%;flex:0 0 auto}}
.punto.on{{background:{tokens.GREEN};box-shadow:0 0 0 4px {tokens.GREEN}22}}
.punto.off{{background:{tokens.FAINT}}}
.punto.mal{{background:{tokens.RED};box-shadow:0 0 0 4px {tokens.RED}22}}
.mando .que{{font-size:15px;font-weight:600;margin:0}}
.mando .porque{{font-size:13px;color:{tokens.DIM};margin:3px 0 0}}
.switch{{appearance:none;border:0;cursor:pointer;font:inherit;font-weight:600;
font-size:14px;border-radius:10px;padding:11px 22px;color:#fff;
background:{tokens.ACCENT};transition:filter .15s}}
.switch:hover{{filter:brightness(1.08)}}
.switch.apagar{{background:{tokens.SURFACE2};color:{tokens.TEXT};
border:1px solid {tokens.BORDER}}}
.switch[disabled]{{opacity:.5;cursor:not-allowed}}
.mando .nota{{font-size:12px;color:{tokens.FAINT};margin:10px 0 0;width:100%}}
h2{{font-size:11px;font-weight:500;letter-spacing:0.13em;text-transform:uppercase;
color:{tokens.FAINT};margin:0 0 14px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
gap:16px;margin-bottom:32px}}
.kpi{{background:{tokens.SURFACE};border:1px solid {tokens.BORDER};
border-radius:16px;padding:20px 22px;box-shadow:{tokens.SOMBRA_PANEL}}}
.kpi .n{{font-size:30px;font-weight:600;line-height:1.1;letter-spacing:-0.02em}}
.kpi .l{{font-size:12px;color:{tokens.DIM};margin-top:6px;line-height:1.4}}
.kpi.alert .n{{color:{tokens.RED}}}
.kpi.good .n{{color:{tokens.GREEN}}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
gap:20px;margin-bottom:20px}}
.card{{background:{tokens.SURFACE};border:1px solid {tokens.BORDER};
border-radius:16px;padding:22px 24px;box-shadow:{tokens.SOMBRA_PANEL}}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;font-weight:500;color:{tokens.FAINT};padding:0 0 8px;
font-size:11px;letter-spacing:0.13em;text-transform:uppercase}}
td{{padding:8px 0;border-top:1px solid {tokens.BORDER};vertical-align:middle}}
td.num{{text-align:right;font-variant-numeric:tabular-nums;color:{tokens.DIM}}}
.tag{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;
border:1px solid {tokens.BORDER};color:{tokens.DIM};background:{tokens.SURFACE2}}}
.tag.bad{{border-color:rgba(201,58,76,0.28);color:{tokens.RED};
background:rgba(201,58,76,0.07)}}
.tag.warn{{border-color:rgba(168,113,10,0.28);color:{tokens.AMBER};
background:rgba(168,113,10,0.07)}}
.tag.ok{{border-color:rgba(23,122,82,0.28);color:{tokens.GREEN};
background:rgba(23,122,82,0.07)}}
.bar{{height:6px;border-radius:999px;background:{tokens.SURFACE3};
overflow:hidden;margin-top:5px}}
.bar span{{display:block;height:100%;background:{tokens.ACCENT}}}
.bar.crit span{{background:{tokens.RED}}}
.empty{{color:{tokens.FAINT};font-size:13px;line-height:1.6}}
.chart{{display:flex;align-items:flex-end;gap:4px;height:90px;margin-top:8px}}
.chart div{{flex:1;background:{tokens.SURFACE3};border-radius:3px 3px 0 0;min-height:2px}}
.chart div.peak{{background:{tokens.ACCENT}}}
.axis{{display:flex;justify-content:space-between;font-size:11px;
color:{tokens.FAINT};margin-top:6px}}
.foot{{margin-top:32px;font-size:12px;color:{tokens.FAINT};line-height:1.7;
border-top:1px solid {tokens.BORDER};padding-top:18px}}
"""
_SHIELD = tokens.ESCUDO_SVG

_CLASS_TAG = {
    "ai_unapproved": ("bad", "IA no aprobada"),
    "ai_unknown": ("warn", "sin catalogar"),
    "ai_approved": ("ok", "IA aprobada"),
    "non_ai": ("", "interno"),
    "passthrough": ("", "excluido"),
}


def _kpi(value: str, label: str, tone: str = "") -> str:
    return (
        f'<div class="kpi {tone}"><div class="n">{escape(value)}</div>'
        f'<div class="l">{escape(label)}</div></div>'
    )


def _bar_row(label: str, count: int, total: int, critical: bool = False) -> str:
    width = (count / total * 100) if total else 0
    css = "bar crit" if critical else "bar"
    return (
        f"<tr><td>{escape(label)}"
        f'<div class="{css}"><span style="width:{width:.0f}%"></span></div></td>'
        f'<td class="num">{count}</td></tr>'
    )


def _timeline(metrics: Metrics) -> str:
    if not metrics.timeline:
        chart = '<p class="empty">Sin actividad registrada todavia.</p>'
    else:
        peak = max(count for _, count in metrics.timeline)
        bars = "".join(
            f'<div class="{"peak" if count == peak else ""}" '
            f'style="height:{count / peak * 100:.0f}%" title="{escape(hour)}: {count}"></div>'
            for hour, count in metrics.timeline
        )
        first = metrics.timeline[0][0].replace("T", " ")
        last = metrics.timeline[-1][0].replace("T", " ")
        chart = (
            f'<div class="chart">{bars}</div>'
            f'<div class="axis"><span>{escape(first)}h</span>'
            f"<span>{escape(last)}h</span></div>"
        )
    return f'<div class="card"><h2>Actividad por hora</h2>{chart}</div>'


def _destinations(metrics: Metrics) -> str:
    if not metrics.by_destination:
        rows = '<tr><td class="empty">Sin destinos registrados.</td></tr>'
    else:
        rows = ""
        for domain, classification, count in metrics.by_destination:
            tone, label = _CLASS_TAG.get(classification, ("", classification))
            rows += (
                f"<tr><td>{escape(domain)}<br>"
                f'<span class="tag {tone}">{escape(label)}</span></td>'
                f'<td class="num">{count}</td></tr>'
            )
    return (
        '<div class="card"><h2>Destinos mas frecuentes</h2>'
        f"<table><tr><th>Dominio</th><th></th></tr>{rows}</table></div>"
    )


def _rules(metrics: Metrics) -> str:
    total = max((count for _, count in metrics.by_rule), default=0)
    if not metrics.by_rule:
        rows = '<tr><td class="empty">Ninguna deteccion todavia.</td></tr>'
    else:
        rows = "".join(_bar_row(rule, count, total) for rule, count in metrics.by_rule)
    return (
        '<div class="card"><h2>Que se intenta enviar</h2>'
        f"<table><tr><th>Deteccion</th><th></th></tr>{rows}</table></div>"
    )


def _areas(metrics: Metrics) -> str:
    total = max((count for _, count, _ in metrics.by_area), default=0)
    if not metrics.by_area:
        rows = '<tr><td class="empty">Sin actividad por area.</td></tr>'
    else:
        rows = "".join(
            _bar_row(f"{area} ({critical} criticos)", count, total, critical > 0)
            for area, count, critical in metrics.by_area
        )
    return (
        '<div class="card"><h2>Riesgo por area</h2>'
        f"<table><tr><th>Area</th><th></th></tr>{rows}</table></div>"
    )


def _people(metrics: Metrics, repeats: dict[str, list[str]]) -> str:
    if not metrics.people_at_risk:
        rows = '<tr><td class="empty">Nadie con incidentes.</td></tr>'
    else:
        rows = ""
        for user, area, total, critical in metrics.people_at_risk:
            repeated = repeats.get(user, [])
            if repeated:
                # La lista completa satura la celda y deja de leerse. Dos nombres
                # alcanzan para saber por donde empezar la conversacion.
                visibles = ", ".join(repeated[:2])
                resto = f" +{len(repeated) - 2}" if len(repeated) > 2 else ""
                nota = f'<span class="tag warn">repite: {escape(visibles)}{resto}</span>'
            else:
                nota = '<span class="tag ok">sin reincidencia</span>'
            rows += (
                f"<tr><td>{escape(user)}<br><span class='tag'>{escape(area)}</span></td>"
                f"<td>{nota}</td>"
                f'<td class="num">{critical}</td><td class="num">{total}</td></tr>'
            )
    return (
        '<div class="card"><h2>Personas que necesitan acompanamiento</h2>'
        "<table><tr><th>Persona</th><th>Patron</th><th>Criticos</th><th>Total</th></tr>"
        f"{rows}</table></div>"
    )


def _discovery(metrics: Metrics) -> str:
    def _list(domains: list[str], vacio: str) -> str:
        if not domains:
            html = f'<p class="empty">{escape(vacio)}</p>'
        else:
            html = "".join(
                f'<div style="padding:6px 0;border-top:1px solid #1e222b">{escape(d)}</div>'
                for d in domains
            )
        return html

    return (
        '<div class="card"><h2>Shadow AI descubierta</h2>'
        + _list(metrics.shadow_domains, "Ningun servicio no aprobado en uso.")
        + '<h2 style="margin-top:22px">Detectada por su comportamiento</h2>'
        '<p class="empty" style="margin:0 0 6px">Dominios que no estaban en ninguna '
        "lista y se delataron por la forma de sus peticiones.</p>"
        + _list(metrics.uncatalogued_domains, "Ninguno por ahora.")
        + "</div>"
    )


# Que dice el panel en cada situacion. El texto vive en un solo lugar para que
# el estado ROTO -- el navegador apunta a Aegis y Aegis no escucha -- se explique
# igual aca que en el CLI: es el unico en el que la persona no tiene internet, y
# leer "apagado" ahi seria mentirle justo cuando mas necesita la verdad.
_SITUACIONES = {
    "protegiendo": (
        "on",
        "Aegis esta protegiendo este equipo",
        "Todo lo que sale hacia una IA pasa por aca antes de irse.",
        "Apagar",
        "apagar",
    ),
    "apagado": (
        "off",
        "Aegis esta apagado",
        "El trafico sale directo: este equipo no tiene proteccion ahora mismo.",
        "Prender",
        "prender",
    ),
    "roto": (
        "mal",
        "Sin internet: el navegador apunta a Aegis y Aegis no esta corriendo",
        "Apretar Prender levanta el proxy y lo arregla. Apagar tambien te "
        "devuelve la red, pero sin proteccion.",
        "Prender",
        "prender",
    ),
    "sin_instalar": (
        "off",
        "Aegis no esta instalado en este equipo",
        "Corre `aegis instalar` una vez. Despues este interruptor alcanza para "
        "todo lo demas.",
        "Prender",
        "prender",
    ),
}


def _mando(control: dict | None, token: str) -> str:
    """El interruptor. Lo primero de la pagina porque es lo unico que se aprieta.

    El boton se deshabilita solo si no hay nada que hacer (no esta instalado):
    en cualquier otro estado hay una accion util, incluida la de rescatar a
    alguien que se quedo sin internet.
    """

    if control is None:
        return ""

    situacion = control.get("situacion", "apagado")
    punto, que, porque, etiqueta, accion = _SITUACIONES.get(
        situacion, _SITUACIONES["apagado"]
    )
    deshabilitado = " disabled" if situacion == "sin_instalar" else ""
    clase = " apagar" if accion == "apagar" else ""

    return f"""<section class="mando">
  <div class="luz">
    <span class="punto {punto}"></span>
    <div>
      <p class="que">{escape(que)}</p>
      <p class="porque">{escape(porque)}</p>
    </div>
  </div>
  <button class="switch{clase}" id="switch" data-accion="{accion}"{deshabilitado}>{etiqueta}</button>
  <p class="nota">Esto prende y apaga el ruteo, no desinstala nada: la CA y las
  variables se quedan en su lugar, asi que volver es instantaneo. Para sacar
  Aegis del equipo de verdad, <code>aegis desinstalar</code>.</p>
</section>
<script>
// El token viaja en una cabecera PROPIA y no en el cuerpo, y eso es lo que
// sostiene la seguridad de este boton: una cabecera que no es estandar obliga
// al navegador a pedir permiso (preflight) antes de mandar el request desde
// otro origen, y el panel no lo da. Sin esto, cualquier pagina abierta en otra
// pestana podria apagarle el DLP a la persona con un formulario.
document.getElementById('switch')?.addEventListener('click', async (e) => {{
  const boton = e.currentTarget;
  boton.disabled = true;
  boton.textContent = 'Un momento...';
  try {{
    const r = await fetch('/api/proteccion', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json', 'X-Aegis-Token': {token!r}}},
      body: JSON.stringify({{accion: boton.dataset.accion}}),
    }});
    const datos = await r.json();
    if (!r.ok || datos.ok === false) {{
      boton.disabled = false;
      boton.textContent = 'Reintentar';
      alert(datos.mensaje || 'No se pudo cambiar el estado.');
      return;
    }}
    location.reload();
  }} catch (err) {{
    boton.disabled = false;
    boton.textContent = 'Reintentar';
  }}
}});
</script>"""


def render(
    metrics: Metrics,
    repeats: dict[str, list[str]],
    tenant: str = "acme",
    control: dict | None = None,
    token: str = "",
) -> str:
    shadow_total = len(metrics.shadow_domains) + len(metrics.uncatalogued_domains)
    kpis = (
        _kpi(str(metrics.total), "Envios inspeccionados hacia IA")
        + _kpi(str(metrics.blocked), "Fugas evitadas", "alert")
        + _kpi(f"{metrics.block_rate:.0f}%", "Tasa de bloqueo")
        + _kpi(str(shadow_total), "Servicios de IA no aprobados en uso", "alert")
        + _kpi(str(len(repeats)), "Personas que repiten el mismo error", "good" if not repeats else "")
    )

    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aegis — Panel de {escape(tenant)}</title><style>{_STYLES}</style></head>
<body><div class="wrap">
<header>
  <div>
    <div class="brand">{_SHIELD}<span>Aegis</span></div>
    <h1 id="titulo">Panel de la empresa</h1>
  </div>
  <div class="tenant">Organizacion: {escape(tenant)}</div>
</header>
{_mando(control, token)}
<section class="kpis">{kpis}</section>
{_timeline(metrics)}
<section class="grid">{_destinations(metrics)}{_rules(metrics)}</section>
<section class="grid">{_areas(metrics)}{_discovery(metrics)}</section>
<section class="grid">{_people(metrics, repeats)}</section>
<p class="foot">Todas estas metricas se calculan sobre eventos redactados: Aegis
nunca recibio el contenido de lo que las personas escribieron. Lo que se ve aca
es que tipo de dato se intento enviar y hacia donde, nunca el dato.</p>
</div></body></html>"""
