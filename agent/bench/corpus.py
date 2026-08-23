"""Corpus en espanol para decidir el umbral de T2 con datos.

El criterio de aceptacion no es cuanto detecta sino cuanto NO detecta. Un T2
ruidoso es peor que no tener T2: ensena a la gente a ignorar los avisos, y
despues a desinstalar.

Por eso la mitad larga de este archivo son casos normales, y los mas valiosos
son los DIFICILES: mencionan una persona, una empresa, una cifra o una
enfermedad, pero no hay ninguna fuga. Son los que separan un modelo que sirve de
uno que estorba, y son justo los que faltaban cuando esto eran diecisiete frases
escritas de memoria.
"""

from __future__ import annotations

# --- Lo que T1 no puede ver, porque no tiene formato: tiene sentido ----------

# Datos de la empresa. Deberian cortar el envio.
EMPRESA = [
    "El cliente Bancolombia esta renegociando el contrato de nomina para 2027",
    "Adjunto el acuerdo con Grupo Exito, valor 4.500 millones de pesos",
    "La propuesta para Ecopetrol cierra en 1.200 millones, no lo comentes",
    "Avianca nos pidio bajar la tarifa un 12% o se van con la competencia",
    "El contrato con Postobon vence en marzo y no lo vamos a renovar",
    "Le vendimos a Sura el paquete completo por 800 millones",
    "Nequi rechazo la integracion, hay que avisarle al equipo comercial",
    "Isagen pidio una prorroga de 90 dias sobre el pago pendiente",
    "El margen del contrato con Alpina quedo en 4% despues del descuento",
    "Terpel nos debe 340 millones desde noviembre",
    "Cementos Argos cancelo el piloto, perdemos 200 millones proyectados",
    "La junta de Davivienda aprueba nuestro presupuesto el jueves",
    "Mi jefe Carlos Restrepo aprobo el despido de tres personas del area",
    "Rappi nos saco del concurso porque Mercado Libre ofrecio la mitad",
]

# Credenciales dichas en lenguaje natural, sin el formato que busca una regla.
#
# El modelo local encuentra CERO de estas, y no es un defecto suyo: un extractor
# de entidades reconoce tipos de cosa (una persona, una empresa), y una
# contrasena no es un tipo de cosa, es una cadena cualquiera que resulta ser
# secreta por el contexto. Las ve T1 con dos reglas deterministas. Se miden aca
# igual, porque son lo mas grave que puede salir y hay que saber si salen.
CREDENCIALES = [
    "La contrasena del servidor de produccion es Verano2026Bogota",
    "Entra con el usuario admin y la clave Temporal#2026 al panel",
    "El acceso al FTP es aegis / Sup3rS3cret, no lo cambies todavia",
    "Te paso el acceso: usuario soporte, clave Bogota#2026Aegis",
    "La clave de la wifi de la oficina es Platanus2026Hack",
    "Guarda esta credencial del correo corporativo: Mktg2026Flash",
    "Usuario juan.perez, password Aegis2026Demo, entorno de produccion",
    "El login del panel de pagos quedo con la clave Cartera#2026Co",
]

# Datos personales y de salud. Alcanza con avisar: cortar por esto le frena el
# trabajo a alguien que quizas solo esta redactando una carta.
PERSONALES = [
    "Ana Maria Gomez, historia clinica: diagnostico de diabetes tipo 2",
    "El paciente reporta dolor toracico y antecedentes de hipertension",
    "Vive en la calle 93 numero 15-20, apartamento 502, Bogota",
    "Juan Perez fue diagnosticado con depresion y pidio incapacidad",
    "La direccion de entrega es carrera 7 numero 71-52, torre B, oficina 604",
    "Maria Fernanda esta en tratamiento por cancer de mama",
    "El empleado sufre de epilepsia, hay que ajustarle el horario",
    "Domicilio registrado: transversal 23 numero 98-45, Medellin",
]

SENSIBLE = EMPRESA + CREDENCIALES + PERSONALES

# --- Trabajo cotidiano. Cada marca aca es una razon para desinstalar ---------

RUTINA = [
    "Ayudame a escribir el resumen de la reunion de manana en tres vinetas",
    "Como optimizo una consulta SQL con muchos joins?",
    "Dame diez ideas de copy para una campana de cafe de origen",
    "Explicame la diferencia entre un proxy y un firewall",
    "Traduci este parrafo al ingles, tono formal",
    "Que patron de diseno conviene para un sistema de notificaciones?",
    "Escribi una funcion en Python que ordene una lista de diccionarios",
    "Cual es la mejor forma de estructurar un README?",
    "Revisa la ortografia de este texto y sugerime un titulo mas corto",
    "Necesito un cronograma de tres semanas para migrar a la version nueva",
    "Hace un test unitario para esta funcion que valida correos",
    "Como configuro el cache de una API para que no se sature?",
]

# Nombran a una persona sin que haya nada privado en juego.
PERSONAS_SIN_FUGA = [
    "Escribile un correo a Juan pidiendole el informe del mes",
    "Como le explico a Maria que el proyecto se atrasa dos semanas?",
    "Ayudame a redactar la invitacion para la charla de Andres",
    "Resumime en un parrafo quien fue Gabriel Garcia Marquez",
    "Dame cinco nombres posibles para el personaje de un cuento",
    "Como se escribe una carta de recomendacion para un companero?",
]

# Nombran una empresa como tema publico, no como cliente.
EMPRESAS_SIN_FUGA = [
    "Explicame que hace Bancolombia como negocio, es para la universidad",
    "Compara las APIs de Stripe y PayPal para cobros recurrentes",
    "Que ventajas tiene AWS sobre Azure para una aplicacion pequena?",
    "Como se llama la estrategia que uso Netflix cuando empezo?",
    "Cuales son los principales bancos de Colombia?",
    "Por que Nokia perdio el mercado de los telefonos?",
]

# Hablan de plata sin que sea plata de nadie.
DINERO_SIN_FUGA = [
    "Cuanto cuesta en promedio un servidor en la nube al mes?",
    "Explicame que es la inflacion con un ejemplo de 100 mil pesos",
    "Como calculo el IVA del 19% sobre un precio de lista?",
    "Arma un presupuesto de ejemplo para un proyecto ficticio de 10 millones",
    "Que significa que una startup levante una ronda de 5 millones de dolares?",
]

# Los mas dificiles: usan la palabra exacta que el modelo esta buscando.
PALABRA_TRAMPA = [
    "Como genero una contrasena segura desde Python?",
    "Explicame el hashing de contrasenas con bcrypt",
    "Que es la diabetes y como se previene?",
    "Explicame como funciona el sistema inmune",
    "Como escribo una direccion en formato colombiano para un formulario?",
    "Dame el formato correcto de una carta formal con remitente y destinatario",
    "Cual es la diferencia entre autenticacion y autorizacion?",
]

# Los negativos de la regla de credenciales, que es la mas peligrosa de todas
# porque su categoria es `secret` y por lo tanto BLOQUEA. Cada frase de aca
# nombra una credencial y no la contiene: son las que hacen que un desarrollador
# no pueda trabajar. Tres de ellas rompieron versiones anteriores de la regla y
# por eso estan escritas tal cual:
#
#   "ISO27001_v3"      entraba con la ventana de 30 caracteres, ahora son 24
#   "usuarios_2024_id" entraba hasta que "clave primaria" quedo excluida
#   "Free2024"         entraba con el largo minimo en 8, ahora son 10
TRAMPAS_DE_CREDENCIAL = [
    "const password = hashPassword(input.value)",
    "Explicame OAuth2.0 y como funciona el acceso con tokens",
    "La clave primaria de la tabla es usuarios_2024_id",
    "El usuario reporto un error 500 en el endpoint /api/v2/checkout",
    "Como valido una contrasena con al menos 8 caracteres y un numero?",
    "Documenta el acceso a la API REST usando Bearer <TOKEN_AQUI>",
    "El login falla en Chrome 120.0.6099 pero funciona en Firefox",
    "Instala el paquete con pip install django-allauth==0.57.0 para el login",
    "La credencial se rota cada 90 dias segun la ISO27001_v3 del area",
    "Usuario: Juan Perez. Cargo: analista. Ingreso: 2024-03-15",
    "Escribi un test para la funcion de login con pytest-mock 3.12",
    "El acceso al repositorio es via GitHub Actions, no con clave personal",
    "Como configuro el acceso SSH con llave publica en Ubuntu 24.04?",
    "Revisa el modulo auth/Login2FA.tsx que valida la contrasena",
    "El acceso de invitados usa el plan Free2024 sin costo",
    "El usuario admin del entorno de pruebas no tiene datos reales",
    "Configura el login social con Auth0 siguiendo la guia oficial",
    "La clave publica del servidor cambia con cada despliegue automatico",
]

NORMAL = (
    RUTINA
    + PERSONAS_SIN_FUGA
    + EMPRESAS_SIN_FUGA
    + DINERO_SIN_FUGA
    + PALABRA_TRAMPA
    + TRAMPAS_DE_CREDENCIAL
)

# Los grupos, para poder mirar donde falla y no solo cuanto falla.
GRUPOS_SENSIBLES = {
    "empresa": EMPRESA,
    "credenciales": CREDENCIALES,
    "personales": PERSONALES,
}

GRUPOS_NORMALES = {
    "rutina": RUTINA,
    "personas sin fuga": PERSONAS_SIN_FUGA,
    "empresas sin fuga": EMPRESAS_SIN_FUGA,
    "dinero sin fuga": DINERO_SIN_FUGA,
    "palabra trampa": PALABRA_TRAMPA,
    "trampas de credencial": TRAMPAS_DE_CREDENCIAL,
}
