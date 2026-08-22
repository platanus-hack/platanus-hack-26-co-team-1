"""Upstream falso para los tests: responde como si fuera el servicio de IA.

Existe para que la suite no dependa de la red ni mande datos de prueba a un
tercero. Se carga despues del addon de Aegis, asi que solo contesta lo que Aegis
dejo pasar: si responde, es porque el trafico no fue bloqueado.
"""

from __future__ import annotations

from mitmproxy import http

_CHAT_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>{name}</title></head><body>
<h1 id="titulo">{name}</h1>
<form id="form" method="post" action="{action}" enctype="multipart/form-data">
  <textarea id="prompt" name="{field}" rows="6" cols="60"></textarea>
  <input id="archivo" type="file" name="file">
  <button id="enviar" type="submit">Enviar</button>
</form></body></html>"""

_REPLY_PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Respuesta</title></head><body>
<p id="respuesta">Respuesta del modelo: recibi tu mensaje y lo proceso.</p>
</body></html>"""

# El nombre del campo importa: la intranet no llama "prompt" a su formulario, y
# usar el mismo template para todo haria que el test se aprobara a si mismo.
_SITES = {
    "claude.ai": ("Claude (aprobada por la empresa)", "/api/chat", "prompt"),
    "novaai.local": ("NovaAI", "/api/chat", "prompt"),
    "asistente-magico.co": ("Asistente Magico", "/v1/chat/completions", "prompt"),
    "intranet.acme.co": ("Intranet Acme", "/documentos/subir", "descripcion"),
}


class MockUpstream:
    def request(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            host = flow.request.pretty_host
            site = _SITES.get(host)
            if site is not None:
                name, action, field = site
                if flow.request.method == "GET":
                    body = _CHAT_PAGE.format(name=name, action=action, field=field)
                else:
                    body = _REPLY_PAGE
                flow.response = http.Response.make(
                    200,
                    body.encode("utf-8"),
                    {"Content-Type": "text/html; charset=utf-8"},
                )


addons = [MockUpstream()]
