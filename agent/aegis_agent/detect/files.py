from __future__ import annotations

import re

from .types import Finding

# Hasta aca todo el motor leia el contenido. Pero un archivo puede ser critico
# por lo que ES, no por lo que dice: un volcado de base de datos es binario y no
# tiene ni una palabra que una regla de texto pueda encontrar, y un .env con
# FOO=bar no dispara ninguna heuristica de entropia aunque el archivo entero sea
# una configuracion de produccion.
#
# Esto mira el nombre del adjunto y su firma binaria, que es lo que se sabe
# antes de leer una sola linea.

# Nombres exactos que no tienen ninguna razon de existir fuera del equipo.
NOMBRES_CRITICOS: dict[str, str] = {
    ".env": "env",
    ".npmrc": "credenciales_npm",
    ".pypirc": "credenciales_pypi",
    ".netrc": "credenciales_netrc",
    ".pgpass": "credenciales_postgres",
    ".htpasswd": "credenciales_web",
    "credentials": "credenciales_aws",
    "kubeconfig": "acceso_kubernetes",
    "id_rsa": "llave_ssh",
    "id_ed25519": "llave_ssh",
    "id_ecdsa": "llave_ssh",
    "known_hosts": "inventario_ssh",
    "shadow": "contrasenas_del_sistema",
    "web.config": "configuracion_de_servidor",
}

EXTENSIONES_CRITICAS: dict[str, tuple[str, str]] = {
    # extension -> (categoria, tipo)
    ".pem": ("secret", "certificado"),
    ".key": ("secret", "llave_privada"),
    ".p12": ("secret", "almacen_de_llaves"),
    ".pfx": ("secret", "almacen_de_llaves"),
    ".jks": ("secret", "almacen_de_llaves"),
    ".keystore": ("secret", "almacen_de_llaves"),
    ".kdbx": ("secret", "gestor_de_contrasenas"),
    ".ovpn": ("secret", "acceso_vpn"),
    ".tfstate": ("secret", "estado_de_infraestructura"),
    ".tfvars": ("secret", "variables_de_infraestructura"),
    ".sql": ("internal_data", "volcado_de_base"),
    ".dump": ("internal_data", "volcado_de_base"),
    ".bak": ("internal_data", "respaldo"),
    ".sqlite": ("internal_data", "base_de_datos"),
    ".sqlite3": ("internal_data", "base_de_datos"),
    ".db": ("internal_data", "base_de_datos"),
    ".mdb": ("internal_data", "base_de_datos"),
    ".accdb": ("internal_data", "base_de_datos"),
    ".pcap": ("internal_data", "captura_de_red"),
}

# Un .env se llama de muchas formas y todas significan lo mismo.
_PREFIJOS_ENV = (".env.", "env.", ".env-")

# Firmas binarias: el archivo puede llegar renombrado a "reporte.txt" y la
# cabecera lo delata igual.
FIRMAS: tuple[tuple[bytes, str, str], ...] = (
    (b"SQLite format 3\x00", "internal_data", "base_de_datos"),
    (b"PGDMP", "internal_data", "volcado_de_base"),
    (b"-----BEGIN OPENSSH PRIVATE KEY", "secret", "llave_ssh"),
    (b"-----BEGIN RSA PRIVATE KEY", "secret", "llave_privada"),
    (b"PuTTY-User-Key-File", "secret", "llave_privada"),
)

_ADJUNTO = re.compile(r'filename\*?=(?:"([^"]+)"|([^;\r\n]+))', re.I)

MAX_FIRMA_BYTES = 500_000


def _nombre_base(ruta: str) -> str:
    return ruta.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


def clasificar_nombre(nombre: str) -> tuple[str, str] | None:
    """Devuelve (categoria, tipo) si el nombre delata un archivo critico."""

    base = _nombre_base(nombre)
    resultado = None

    if base in NOMBRES_CRITICOS:
        resultado = ("secret", NOMBRES_CRITICOS[base])
    else:
        if base.startswith(_PREFIJOS_ENV) or base.endswith(".env"):
            resultado = ("secret", "env")
        else:
            for extension, (categoria, tipo) in EXTENSIONES_CRITICAS.items():
                if resultado is None and base.endswith(extension):
                    resultado = (categoria, tipo)
    return resultado


def nombres_adjuntos(texto: str) -> list[str]:
    """Saca los nombres de archivo de un multipart sin parsear el formato entero."""

    return [
        (comillas or suelto).strip()
        for comillas, suelto in _ADJUNTO.findall(texto)
        if (comillas or suelto).strip()
    ]


def scan_files(body: bytes, texto: str) -> list[Finding]:
    """Hallazgos que salen del archivo en si, sin mirar su contenido."""

    hallazgos: list[Finding] = []
    vistos: set[str] = set()

    # Los nombres se buscan sobre los bytes crudos y no sobre el texto decodificado:
    # un adjunto binario hace que el decode adivine mal el juego de caracteres y
    # el nombre del archivo se pierde, que es justo el caso que mas importa.
    cabeceras = body[:MAX_FIRMA_BYTES].decode("latin-1", errors="replace")

    for nombre in nombres_adjuntos(cabeceras) + nombres_adjuntos(texto):
        clasificado = clasificar_nombre(nombre)
        if clasificado is not None:
            categoria, tipo = clasificado
            clave = f"nombre:{tipo}"
            if clave not in vistos:
                vistos.add(clave)
                hallazgos.append(
                    Finding(
                        rule_id="archivo_critico",
                        category=categoria,
                        severity="critical",
                        confidence=0.97,
                        # El nombre completo puede ser sensible en si mismo
                        # ("clientes-2026.sql"), asi que solo sale el tipo.
                        evidence=f"<archivo:{tipo}>"[:32],
                        start=0,
                        end=0,
                    )
                )

    cabecera = body[:MAX_FIRMA_BYTES]
    for firma, categoria, tipo in FIRMAS:
        clave = f"firma:{tipo}"
        if firma in cabecera and clave not in vistos:
            vistos.add(clave)
            hallazgos.append(
                Finding(
                    rule_id="archivo_critico_por_firma",
                    category=categoria,
                    severity="critical",
                    confidence=0.99,
                    evidence=f"<binario:{tipo}>"[:32],
                    start=0,
                    end=0,
                )
            )

    return hallazgos
