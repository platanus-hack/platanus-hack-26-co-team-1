"""Dispara credenciales de prueba contra el proxy y reporta que se escapa.

Todos los valores de aca son falsos: formato real, contenido inventado o tomado
de la documentacion publica del proveedor. Ninguno sirve para autenticarse en
ningun lado, y esa es la unica forma honesta de probar un DLP.

Corre contra el proxy que este levantado, apuntando a una IA aprobada, que es el
caso donde Aegis inspecciona contenido.

    python -m demo.bateria_credenciales
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

PROXY = os.environ.get("AEGIS_PROXY", "http://127.0.0.1:8899")
COLA = os.environ.get("AEGIS_QUEUE", "aegis-events.jsonl")
DESTINO = "https://api.anthropic.com/v1/messages"
CA = os.path.expanduser("~/.mitmproxy/mitmproxy-ca-cert.pem")

# (nombre, texto a enviar). Formato real, valor inventado.
CREDENCIALES: list[tuple[str, str]] = [
    ("AWS access key", "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"),
    ("AWS secret key", "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"),
    ("Anthropic", "ANTHROPIC_API_KEY=sk-ant-api03-" + "x1Y2z3A4b5C6d7E8f9G0h1I2j3K4l5M6"),
    ("OpenAI", "OPENAI_API_KEY=sk-proj-" + "aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY"),
    ("GitHub token", "GH_TOKEN=ghp_" + "a" * 36),
    ("GitHub fine-grained", "token: github_pat_" + "1B" + "c" * 30),
    ("Google API key", "GOOGLE_API_KEY=AIza" + "SyD-EXAMPLE_dummy_key_1234567890abc"),
    ("Slack bot token", "SLACK_TOKEN=xoxb-1234567890-0987654321-ABCdefGHIjklMNOpqr"),
    ("Stripe live", "STRIPE_SECRET=sk_live_4eC39HqLyjWDarjtT1zdp7dc"),
    ("Twilio auth", "TWILIO_AUTH_TOKEN=" + "9f8e7d6c5b4a3210fedcba9876543210"),
    ("SendGrid", "SENDGRID_API_KEY=SG." + "a" * 22 + "." + "b" * 43),
    ("Mailgun", "MAILGUN_KEY=key-" + "0123456789abcdef0123456789abcdef"),
    ("DigitalOcean", "DO_TOKEN=dop_v1_" + "f" * 64),
    ("HuggingFace", "HF_TOKEN=hf_" + "ABcdEFghIJklMNopQRstUVwxYZ012345"),
    ("OpenRouter", "OPENROUTER_KEY=sk-or-v1-" + "d" * 40),
    ("Azure storage", "DefaultEndpointsProtocol=https;AccountName=acme;AccountKey=" + "Z" * 60 + "==;"),
    ("JWT", "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefghijklmnop"),
    ("Postgres", "DATABASE_URL=postgres://admin:s3cr3t@db.acme.co:5432/prod"),
    ("MongoDB", "MONGO_URL=mongodb+srv://root:p4ssw0rd@cluster0.acme.mongodb.net/db"),
    ("Redis", "REDIS_URL=redis://default:cl4ve@cache.acme.co:6379"),
    ("Llave privada", "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA\n"),
    ("Password de alta entropia", 'password = "xK9$mQ2wZr7Lp4Nv8Ty"'),
    ("Volcado MySQL", "-- MySQL dump 10.13  Distrib 8.0.32\n-- Host: prod"),
    ("Filas de una tabla", "INSERT INTO clientes (id, correo) VALUES (1, 'ana@acme.co');"),
    ("Export de clientes", "nombre,email,telefono\nAna,ana@acme.co,3001234567"),
    ("Cedula colombiana", "El titular con CC 1.023.456.789 solicito el credito"),
    ("Tarjeta", "Pago con la tarjeta 4111111111111111 vence 12/28"),
]

ARCHIVOS: list[tuple[str, str, bytes]] = [
    ("archivo .env", ".env", b"FOO=bar\nDEBUG=true\n"),
    ("volcado .sql", "respaldo.sql", b"algo\n"),
    ("base sqlite", "datos.sqlite", b"SQLite format 3\x00" + b"\x00" * 200),
    ("sqlite renombrado", "notas.txt", b"SQLite format 3\x00" + b"\x00" * 200),
    ("llave ssh", "id_rsa", b"contenido\n"),
    ("estado terraform", "terraform.tfstate", b'{"version": 4}\n'),
    ("kubeconfig", "kubeconfig", b"apiVersion: v1\n"),
    ("archivo normal", "informe.pdf", b"%PDF-1.7\n1 0 obj\n"),
]


def _opener():
    contexto = ssl.create_default_context(cafile=CA) if os.path.exists(CA) else ssl._create_unverified_context()
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": PROXY, "http": PROXY}),
        urllib.request.HTTPSHandler(context=contexto),
    )


def _eventos() -> list[dict]:
    if not os.path.exists(COLA):
        return []
    with open(COLA, encoding="utf-8") as archivo:
        return [json.loads(l) for l in archivo if l.strip()]


def _enviar(opener, cuerpo: bytes, cabeceras: dict) -> tuple[str, str]:
    """Devuelve (resultado, detalle).

    Un envio que no se bloquea no siempre es una fuga: la politica advierte sobre
    los datos personales sueltos en vez de cortar. Para saber cual de las dos
    cosas paso hay que mirar el evento que quedo registrado, no la respuesta.
    """

    antes = len(_eventos())
    peticion = urllib.request.Request(DESTINO, data=cuerpo, headers=cabeceras)
    try:
        opener.open(peticion, timeout=20)
        resultado = ("pasa", "sin deteccion")
    except urllib.error.HTTPError as error:
        accion = error.headers.get("X-Aegis-Action")
        if accion:
            resultado = ("bloquea", error.headers.get("X-Aegis-Rule") or accion)
        else:
            resultado = ("pasa", f"respuesta {error.code} del servidor")
    except urllib.error.URLError as error:
        resultado = ("pasa", f"sin conexion: {error.reason}")

    if resultado[0] == "pasa":
        nuevos = _eventos()[antes:]
        advertencias = [e for e in nuevos if e.get("action") == "warned"]
        if advertencias:
            deteccion = advertencias[-1].get("detection") or {}
            resultado = ("advierte", deteccion.get("rule_id", "sin regla"))
    return resultado


def _como_prompt(texto: str) -> bytes:
    return json.dumps(
        {
            "model": "claude",
            "max_tokens": 16,
            "messages": [{"role": "user", "content": f"Revisa esto: {texto}"}],
        }
    ).encode()


def _como_adjunto(nombre: str, contenido: bytes) -> bytes:
    return (
        b"--X\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + nombre.encode() + b'"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n" + contenido + b"\r\n--X--\r\n"
    )


def main() -> int:
    opener = _opener()
    json_headers = {"Content-Type": "application/json", "Sec-Fetch-Dest": "empty"}
    multipart_headers = {"Content-Type": "multipart/form-data; boundary=X", "Sec-Fetch-Dest": "empty"}

    escapados: list[str] = []

    print(f"Batería contra {PROXY} -> {DESTINO}\n")
    print("CREDENCIALES PEGADAS EN EL PROMPT")
    for nombre, texto in CREDENCIALES:
        resultado, detalle = _enviar(opener, _como_prompt(texto), json_headers)
        marca = {"bloquea": "BLOQUEA", "advierte": "advierte", "pasa": "SE ESCAPA"}[resultado]
        print(f"  {marca:10} {nombre:28} {detalle}")
        if resultado == "pasa":
            escapados.append(nombre)

    print("\nARCHIVOS ADJUNTOS")
    for nombre, archivo, contenido in ARCHIVOS:
        resultado, detalle = _enviar(opener, _como_adjunto(archivo, contenido), multipart_headers)
        bloqueado = resultado == "bloquea"
        esperado = nombre != "archivo normal"
        correcto = bloqueado == esperado
        marca = ("BLOQUEA" if bloqueado else "pasa") + ("" if correcto else "  <-- MAL")
        print(f"  {marca:18} {nombre:28} {detalle}")
        if esperado and not bloqueado:
            escapados.append(nombre)

    total = len(CREDENCIALES) + len(ARCHIVOS) - 1
    print(f"\nCubiertos {total - len(escapados)} de {total}")
    if escapados:
        print("Se escapan: " + ", ".join(escapados))
    return 1 if escapados else 0


if __name__ == "__main__":
    raise SystemExit(main())
