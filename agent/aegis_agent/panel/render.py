from __future__ import annotations

from html import escape

from .metrics import Metrics

# El panel comparte lenguaje visual con la pagina de bloqueo a proposito: el
# empleado y el administrador ven el mismo producto desde dos lados.

_STYLES = """
*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e8eaed;
font-family:"Segoe UI",system-ui,-apple-system,sans-serif;padding:40px 32px}
.wrap{max-width:1180px;margin:0 auto}
header{display:flex;align-items:baseline;justify-content:space-between;
border-bottom:1px solid #232834;padding-bottom:18px;margin-bottom:32px;flex-wrap:wrap;gap:12px}
.brand{display:flex;align-items:center;gap:10px;font-size:13px;letter-spacing:.14em;
text-transform:uppercase;color:#8b93a7}
.brand svg{width:20px;height:20px;color:#5b8def}
header .tenant{font-size:13px;color:#6b7285}
h1{font-size:20px;margin:0;font-weight:600}
h2{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:#7b8398;
margin:0 0 14px;font-weight:600}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:32px}
.kpi{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:20px 22px}
.kpi .n{font-size:30px;font-weight:600;line-height:1.1}
.kpi .l{font-size:12px;color:#8b93a7;margin-top:6px;line-height:1.4}
.kpi.alert .n{color:#e5747d}
.kpi.good .n{color:#5fb98a}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:20px;margin-bottom:20px}
.card{background:#171a21;border:1px solid #262b36;border-radius:12px;padding:22px 24px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-weight:500;color:#6b7285;padding:0 0 8px;font-size:11px;
letter-spacing:.08em;text-transform:uppercase}
td{padding:8px 0;border-top:1px solid #1e222b;vertical-align:middle}
td.num{text-align:right;font-variant-numeric:tabular-nums;color:#aab2c5}
.tag{display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;
border:1px solid #2f3644;color:#8b93a7}
.tag.bad{border-color:#5b2b31;color:#e5747d;background:#20161a}
.tag.warn{border-color:#5c4a24;color:#d8a44a;background:#1f1c14}
.tag.ok{border-color:#28503f;color:#5fb98a;background:#152019}
.bar{height:6px;border-radius:3px;background:#232834;overflow:hidden;margin-top:5px}
.bar span{display:block;height:100%;background:#5b8def}
.bar.crit span{background:#e5747d}
.empty{color:#6b7285;font-size:13px;line-height:1.6}
.chart{display:flex;align-items:flex-end;gap:4px;height:90px;margin-top:8px}
.chart div{flex:1;background:#2d4a80;border-radius:2px 2px 0 0;min-height:2px}
.chart div.peak{background:#5b8def}
.axis{display:flex;justify-content:space-between;font-size:11px;color:#6b7285;margin-top:6px}
.foot{margin-top:32px;font-size:12px;color:#6b7285;line-height:1.7;
border-top:1px solid #232834;padding-top:18px}
"""

_SHIELD = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 3 4.5 6v5.5c0 4.5 3.2 8.3 7.5 9.5 4.3-1.2 7.5-5 7.5-9.5V6L12 3Z"/>'
    '<path d="m9.2 12 2 2 3.6-3.8"/></svg>'
)

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


def render(metrics: Metrics, repeats: dict[str, list[str]], tenant: str = "acme") -> str:
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
<section class="kpis">{kpis}</section>
{_timeline(metrics)}
<section class="grid">{_destinations(metrics)}{_rules(metrics)}</section>
<section class="grid">{_areas(metrics)}{_discovery(metrics)}</section>
<section class="grid">{_people(metrics, repeats)}</section>
<p class="foot">Todas estas metricas se calculan sobre eventos redactados: Aegis
nunca recibio el contenido de lo que las personas escribieron. Lo que se ve aca
es que tipo de dato se intento enviar y hacia donde, nunca el dato.</p>
</div></body></html>"""
