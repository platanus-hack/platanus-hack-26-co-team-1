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
CREDENCIALES = [
    "La contrasena del servidor de produccion es Verano2026Bogota",
    "Entra con el usuario admin y la clave Temporal#2026 al panel",
    "El acceso al FTP es aegis / Sup3rS3cret, no lo cambies todavia",
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

NORMAL = RUTINA + PERSONAS_SIN_FUGA + EMPRESAS_SIN_FUGA + DINERO_SIN_FUGA + PALABRA_TRAMPA

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
}
