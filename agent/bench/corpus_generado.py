"""Volumen para el corpus, generado por composicion y con semilla fija.

## Por que hace falta

`corpus.py` tiene 84 frases curadas y cada una se gano su lugar: varias estan
escritas tal cual porque rompieron una version anterior de una regla. Ese archivo
no se toca.

Pero 84 frases no alcanzan para *decidir* nada, y la documentacion del proyecto
ya lo dice mejor de lo que yo lo diria: «con 30 frases sensibles, la diferencia
entre 22 y 26 son cuatro frases: eso es ruido, no una jerarquia». Un corpus chico
no solo mide mal: hace que cualquier cambio parezca una mejora.

## Lo que este modulo mide de verdad, y lo que NO

Hay que decirlo antes de que alguien cite un numero de aca en una presentacion.

**Los positivos con formato --las llaves de proveedor-- miden REGRESION, no
descubrimiento.** El generador arma `sk-ant-...` porque la regla busca
`sk-ant-...`: que los encuentre no prueba nada sobre el mundo, prueba que nadie
rompio la regla. Sirve, y es exactamente para lo que esta el trinquete, pero no
es evidencia de cobertura.

**Donde si hay ciencia es en dos lugares:**

1. **Los negativos.** Cada frase legitima que dispara es un falso positivo real,
   y ninguna regla fue escrita mirandolas. Es la unica mitad del corpus donde el
   generador puede sorprender al motor, y es tambien la mitad que decide si el
   producto sigue instalado.
2. **La variacion de redaccion en espanol.** Una contrasena dicha en lenguaje
   natural o una cedula nombrada de quince formas distintas si estresan de verdad
   las ventanas de las expresiones regulares, que es donde este proyecto ya
   encontro fugas dos veces ("contrasena" con enie, la cedula que no estaba
   pegada al numero).

**Y lo que falta, que es lo mismo que faltaba antes:** casos de negocio reales.
La receta buena para eso es generacion sintetica con un LLM (es lo que hace el
paper de CAPID) y esta bloqueada por la misma API key que bloquea las lecciones.
El hueco esta marcado abajo con un TODO.

## Determinismo

Semilla fija y orden estable, siempre. Un trinquete sobre un corpus que cambia
entre corridas no es un trinquete: es un test intermitente, y un test
intermitente se termina borrando.
"""

from __future__ import annotations

import random
import string

SEMILLA = 20260822

# --- piezas ------------------------------------------------------------------

EMPRESAS = (
    "Bancolombia", "Grupo Exito", "Ecopetrol", "Avianca", "Postobon", "Sura",
    "Nequi", "Isagen", "Alpina", "Terpel", "Cementos Argos", "Davivienda",
    "Rappi", "Corona", "Nutresa", "Claro", "Movistar", "Falabella",
    "Mercado Libre", "Bavaria",
)

PERSONAS = (
    "Ana Maria Gomez", "Carlos Restrepo", "Juan Perez", "Maria Fernanda Ruiz",
    "Andres Villalba", "Luz Adriana Mejia", "Diego Cardenas", "Paula Ortiz",
    "Santiago Herrera", "Camila Rojas",
)

CIUDADES = ("Bogota", "Medellin", "Cali", "Barranquilla", "Bucaramanga", "Pereira")

# --- 1. secretos con formato: REGRESION ---------------------------------------
#
# El prefijo es el que busca la regla. El cuerpo se genera al azar pero se
# rechaza si tiene una corrida de caracteres identicos, porque desde que existe
# el filtro de placeholder una corrida ES la senal de que algo es una plantilla:
# un generador perezoso mediria el filtro en vez de la regla.

PREFIJOS = (
    ("aws_access_key_id", "AKIA", 16, string.ascii_uppercase + string.digits),
    ("anthropic_api_key", "sk-ant-api03-", 40, string.ascii_letters + string.digits),
    ("openai_api_key", "sk-proj-", 40, string.ascii_letters + string.digits),
    ("github_token", "ghp_", 36, string.ascii_letters + string.digits),
    ("google_api_key", "AIza", 35, string.ascii_letters + string.digits + "_-"),
    ("slack_token", "xoxb-", 24, string.digits + "-" + string.ascii_letters),
    ("stripe_secret_key", "sk_live_", 24, string.ascii_letters + string.digits),
    # Una llave de SendGrid de verdad son DOS segmentos: SG.xxx.yyy. El
    # generador armaba uno solo y despues acusaba a la regla de no verla:
    # el bug era del corpus, no del motor. Vale anotarlo porque es el modo
    # de falla mas facil de un banco de pruebas sintetico.
    ("sendgrid_api_key", "SG.", 22, string.ascii_letters + string.digits, 43),
    ("digitalocean_token", "dop_v1_", 64, string.hexdigits[:16].lower()),
    ("huggingface_token", "hf_", 34, string.ascii_letters + string.digits),
)

ENVOLTORIOS = (
    "revisa este codigo, la llave es {v}",
    "me tira error de autenticacion con {v}, que puede ser?",
    "{v}",
    "export MI_LLAVE={v}",
    "el config quedo asi:\nkey = {v}\ntimeout = 30",
    "no me funciona el deploy, la credencial que puse es {v}",
    "ayudame a rotar {v} sin tumbar el servicio",
)


def _cuerpo(rnd: random.Random, largo: int, alfabeto: str) -> str:
    """Un valor sin corridas de caracteres identicos (ver el comentario de arriba)."""

    while True:
        valor = "".join(rnd.choice(alfabeto) for _ in range(largo))
        if not any(valor[i] == valor[i + 1] == valor[i + 2] for i in range(len(valor) - 2)):
            return valor


def secretos_con_formato(rnd: random.Random) -> list[tuple[str, str]]:
    """(frase, regla que deberia verla)."""

    salida: list[tuple[str, str]] = []
    for entrada in PREFIJOS:
        regla, prefijo, largo, alfabeto = entrada[:4]
        # Un quinto campo opcional: el largo del segundo segmento, para las
        # llaves que llevan dos (SendGrid).
        segundo = entrada[4] if len(entrada) > 4 else 0
        for envoltorio in ENVOLTORIOS:
            for _ in range(4):
                valor = prefijo + _cuerpo(rnd, largo, alfabeto)
                if segundo:
                    valor += "." + _cuerpo(rnd, segundo, alfabeto)
                salida.append((envoltorio.format(v=valor), regla))
    return salida


# --- 2. credenciales en espanol: DESCUBRIMIENTO --------------------------------
#
# Aca si hay senal. La regla tiene una ventana de 24 caracteres entre la palabra
# ancla y el valor, y la pregunta que este grupo contesta es si esa ventana
# aguanta como habla la gente de verdad. Este proyecto ya perdio credenciales dos
# veces por como estaban redactadas.

ANCLAS = ("contrasena", "clave", "password", "credencial", "acceso", "usuario y clave")

FRASES_DE_CREDENCIAL = (
    "la {a} del servidor de produccion es {v}",
    "la {a} es {v}, no la compartas",
    "entra con la {a} {v}",
    "te paso el {a}: {v}",
    "el {a} quedo en {v} por ahora",
    "{a}: {v}",
    "guarda esta {a} del correo corporativo: {v}",
    "mira, la {a} de la wifi es {v} y el ssid es Acme_Corp",
    "para el panel de pagos usa la {a} {v}",
    "el ambiente de staging tiene {a} {v}, cambialo despues",
    "ojo que la {a} vieja era otra, ahora es {v}",
    "me dijeron que la {a} nueva es {v} pero no me deja entrar",
)

CONTRASENAS = (
    "Verano2026Bogota", "Temporal#2026", "Sup3rS3cret1", "Bogota#2026Aegis",
    "Platanus2026Hack", "Mktg2026Flash", "Aegis2026Demo", "Cartera#2026Co",
    "Nomina$2026Med", "Acme2026Prod!", "Xk8fRm2Qw9Zt", "Cali2026Segura",
)


def credenciales_en_espanol(rnd: random.Random) -> list[tuple[str, str]]:
    """Cada plantilla contra varios valores, no contra uno al azar.

    El valor importa tanto como la redaccion: la regla exige que la contrasena
    MEZCLE clases de caracteres, asi que una que arranca con simbolo y una que
    arranca con mayuscula recorren caminos distintos del patron.
    """

    salida: list[tuple[str, str]] = []
    for frase in FRASES_DE_CREDENCIAL:
        for ancla in ANCLAS:
            # "usuario y clave" no encaja en "el {a} quedo", y forzarlo generaria
            # frases que nadie diria: el corpus perderia realismo, que es lo unico
            # que lo hace valer.
            if ancla == "usuario y clave" and "{a}:" not in frase:
                continue
            for valor in rnd.sample(CONTRASENAS, 4):
                salida.append((frase.format(a=ancla, v=valor), "credencial"))
    return salida


# --- 3. identidad de LatAm: DESCUBRIMIENTO ------------------------------------

DOCUMENTOS = (
    ("cedula", "1020345678"), ("cedula", "79.482.113"), ("c.c.", "43.115.902"),
    ("CC", "1.130.652.441"), ("NIT", "900.123.456-7"), ("nit", "830074936"),
    ("documento de identidad", "52.998.114"),
    ("RUT", "12.345.678-5"), ("CPF", "123.456.789-09"), ("DNI", "34567890"),
    ("CURP", "GODE561231HDFRRL04"),
)

FRASES_DE_DOCUMENTO = (
    "el cliente con {d} {v} pidio el certificado",
    "mi {d} es {v}, para el tramite",
    "la {d} del titular es {v}",
    "adjunto los datos: {d} {v}, y el correo del contacto",
    "{d}: {v}",
    "verifica el {d} numero {v} en el sistema",
    "el pagador registra {d} {v} desde el ano pasado",
)


def documentos_de_identidad(rnd: random.Random) -> list[tuple[str, str]]:
    return [
        (frase.format(d=doc, v=valor), "latam_national_id")
        for frase in FRASES_DE_DOCUMENTO
        for doc, valor in DOCUMENTOS
    ]


# --- 4. exports y volcados ----------------------------------------------------

def exports(rnd: random.Random) -> list[tuple[str, str]]:
    salida: list[tuple[str, str]] = []
    salida.append(("-- MySQL dump 10.13  Distrib 8.0.35\n-- Host: db.acme.co", "volcado"))
    salida.append(("-- PostgreSQL database dump\n-- Dumped from version 15.4", "volcado"))
    for empresa in EMPRESAS[:8]:
        clave = empresa.lower().replace(" ", "_")
        salida.append(
            (
                f"INSERT INTO clientes (id, nombre, nit) VALUES "
                f"(1, '{empresa}', '900123456'), (2, '{clave}', '830074936');",
                "filas",
            )
        )
    for sep in (";", ",", "\t"):
        salida.append(
            (
                f"email{sep}telefono{sep}ciudad\n"
                + "\n".join(
                    f"cliente{i}@acme.co{sep}+57300123456{i}{sep}{CIUDADES[i % len(CIUDADES)]}"
                    for i in range(6)
                ),
                "export",
            )
        )
    for n in (16, 25, 40):
        salida.append(
            ("\n".join(f"contacto{i}@empresa{i}.com" for i in range(n)), "volumen")
        )
    return salida


# --- 5. datos de empresa sin formato: lo que T1 NO puede ver -------------------
#
# Se miden aparte porque su resultado esperado es distinto: T1 no tiene como
# verlos --no tienen formato, tienen sentido-- y contarlos como fuga escapada de
# T1 seria medir mal a proposito. Son el territorio de T2 y del juez que todavia
# no existe.

PLANTILLAS_DE_EMPRESA = (
    "El cliente {e} esta renegociando el contrato de nomina para 2027",
    "Adjunto el acuerdo con {e}, valor 4.500 millones de pesos",
    "La propuesta para {e} cierra en 1.200 millones, no lo comentes",
    "{e} nos pidio bajar la tarifa un 12% o se van con la competencia",
    "El contrato con {e} vence en marzo y no lo vamos a renovar",
    "Le vendimos a {e} el paquete completo por 800 millones",
    "{e} rechazo la integracion, hay que avisarle al equipo comercial",
    "El margen del contrato con {e} quedo en 4% despues del descuento",
    "{e} nos debe 340 millones desde noviembre",
    "La junta de {e} aprueba nuestro presupuesto el jueves",
)


def datos_de_empresa(rnd: random.Random) -> list[str]:
    return [p.format(e=e) for p in PLANTILLAS_DE_EMPRESA for e in EMPRESAS]


# --- 6. NEGATIVOS DUROS: aca esta la ciencia ----------------------------------

PLANTILLAS_NEGATIVAS = (
    # Preguntas sobre la herramienta, con la palabra exacta que busca la regla.
    "Como roto una {a} en AWS sin downtime?",
    "Explicame como se hashea una {a} con bcrypt",
    "Que largo minimo deberia pedirle a una {a}?",
    "Como valido una {a} en el formulario de registro?",
    "Donde guardo la {a} para que no quede en el repositorio?",
    "Escribi un test que valide que la {a} no se guarda en claro",
    "Como configuro la rotacion automatica de la {a}?",
    "Que diferencia hay entre cifrar y hashear una {a}?",
    # Documentacion y plantillas.
    "En la documentacion la {a} aparece como TU_VALOR_ACA",
    "El .env.example trae la {a} vacia a proposito",
    "Pone la {a} como <REEMPLAZAR> en el README",
    # Vocabulario tecnico que comparte la palabra.
    "La {a} primaria de la tabla pedidos es compuesta",
    "La {a} publica del servidor va en authorized_keys",
    "La {a} foranea apunta a la tabla de clientes",
)

PLANTILLAS_MENCION = (
    "Explicame que hace {e} como negocio, es para la universidad",
    "Por que {e} es tan grande en Colombia?",
    "Compara a {e} con su competencia mas cercana",
    "Que estrategia de marketing usa {e}?",
    "Cuando se fundo {e}?",
    "Resumime la historia de {e} en tres parrafos",
    "Como le escribo a {e} para pedir una cotizacion?",
    "Que opinas de la marca de {e}?",
)

PLANTILLAS_PERSONA = (
    "Escribile un correo a {p} pidiendole el informe del mes",
    "Como le explico a {p} que el proyecto se atrasa?",
    "Ayudame a redactar la invitacion para la charla de {p}",
    "Necesito agendar una reunion con {p} la semana que viene",
    "Como le doy feedback a {p} sin que se lo tome mal?",
)

RUTINA_GENERADA = (
    "Necesito un correo de seguimiento para el cliente de {c}, tono amable",
    "Como presento los resultados del trimestre en {c} sin abrumar?",
    "Dame tres asuntos posibles para el newsletter de {c}",
    "Que metricas deberia mostrar en el tablero de la sucursal de {c}?",
    "Resumime este documento tecnico en lenguaje simple",
    "Como le explico a mi jefe que necesito dos personas mas?",
    "Escribi la descripcion de un cargo de analista para {c}",
    "Dame un guion de dos minutos para presentar el producto",
    "Como redacto una disculpa por un retraso de entrega?",
    "Que preguntas hago en una entrevista para un rol de soporte?",
    "Ayudame a escribir el resumen de la reunion de {c} en tres vinetas",
    "Dame diez ideas de copy para una campana en {c}",
    "Como optimizo una consulta SQL con muchos joins?",
    "Traduci este parrafo al ingles, tono formal",
    "Que patron de diseno conviene para un sistema de notificaciones?",
    "Armame un cronograma de tres semanas para la migracion",
    "Revisa la ortografia y sugerime un titulo mas corto",
    "Como estructuro un README para un proyecto nuevo?",
    "Explicame la diferencia entre un proxy y un firewall",
    "Hace un test unitario para la funcion que valida correos",
)

# Numeros que pasan Luhn y no son tarjetas: el falso positivo medido.
NO_SON_TARJETAS = (
    "el numero de la factura es 4111111111111111 segun el sistema",
    "la orden de compra 4111111111111111 quedo aprobada",
    "el radicado es 4539578763621486 en la ventanilla",
    "guia de envio 4916338506082832, llega el jueves",
    "el consecutivo del pedido es 5555555555554444",
    "referencia de pago 4012888888881881 en el banco",
    "el celular del proveedor es +57 3001234567890123",
)

PREGUNTAS_CONFIDENCIAL = (
    "como configuro el confidencial en el pie de pagina de Word?",
    "que formato uso para el uso interno en la plantilla?",
    "donde pongo la marca de agua de confidencial?",
    "explicame como se maqueta un membrete con la palabra confidencial",
    "ayudame con un ejemplo de aviso de no distribuir para el correo",
)


def negativos(rnd: random.Random) -> list[str]:
    salida: list[str] = []
    for plantilla in PLANTILLAS_NEGATIVAS:
        for ancla in (
            "contrasena",
            "clave",
            "password",
            "credencial",
            "api key",
            "token",
            "llave privada",
            "credencial de servicio",
        ):
            salida.append(plantilla.format(a=ancla))
    salida.extend(p.format(e=e) for p in PLANTILLAS_MENCION for e in EMPRESAS)
    salida.extend(p.format(p=p2) for p in PLANTILLAS_PERSONA for p2 in PERSONAS)
    salida.extend(p.format(c=c) for p in RUTINA_GENERADA for c in CIUDADES)
    salida.extend(NO_SON_TARJETAS)
    salida.extend(PREGUNTAS_CONFIDENCIAL)
    # Codigo, que es lo que un desarrollador pega diez veces por dia.
    for nombre in ("password", "apiKey", "token", "secret"):
        salida.append(f"const {nombre} = hashValue(input.{nombre})")
        salida.append(f"if (!{nombre}) throw new Error('falta {nombre}')")
        salida.append(f"self.{nombre} = os.environ.get('{nombre.upper()}')")
        salida.append(f"{nombre}: str = Field(..., description='el {nombre} del usuario')")
    return salida


# TODO(corpus real): lo que falta son casos de negocio reales, y la receta buena
# es generacion sintetica con un LLM sobre plantillas de dominio (es lo que hace
# el paper de CAPID: un modelo grande fabrica el corpus con el que se afina el
# chico). Esta bloqueado por la misma ANTHROPIC_API_KEY que bloquea las lecciones
# y el clasificador de dominios. El otro camino, gratis y ya disponible, es bajar
# el split en espanol de ai4privacy/pii-masking-400k, que trae 30 idiomas y esta
# armado justo para el contexto de asistentes de IA.


def construir() -> dict[str, object]:
    """Todo el corpus generado, con el mismo resultado en cada corrida."""

    rnd = random.Random(SEMILLA)
    return {
        # Positivos que T1 TIENE que ver.
        "secretos_con_formato": secretos_con_formato(rnd),
        "credenciales_en_espanol": credenciales_en_espanol(rnd),
        "documentos_de_identidad": documentos_de_identidad(rnd),
        "exports": exports(rnd),
        # Positivos que T1 no puede ver: son de T2 y del juez que falta.
        "datos_de_empresa": datos_de_empresa(rnd),
        # Negativos duros: la mitad que decide si el producto sigue instalado.
        "negativos": negativos(rnd),
    }


if __name__ == "__main__":
    corpus = construir()
    total = 0
    for nombre, casos in corpus.items():
        print(f"{len(casos):5}  {nombre}")
        total += len(casos)
    print(f"{total:5}  TOTAL")
