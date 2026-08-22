# ADR 0003 — Frontera de datos: lo local decide, lo remoto enseña

- **Estado:** aceptado
- **Fecha:** 2026-08-22
- **Complementa:** [ADR 0002](0002-el-proxy-es-el-producto.md)
- **Contexto:** [Investigación 02](../research/02-motor-de-deteccion.md)

## Contexto

La Investigación 02 dejaba un LLM remoto como juez para los casos ambiguos, dentro del camino
crítico de la decisión. Eso implicaba que, en esos casos, el contenido interceptado salía de la
máquina hacia una API de IA — el mismo movimiento que el producto existe para impedir.

## Decisión

**Se traza una frontera dura entre lo que decide y lo que enseña.**

| | Lado local (el equipo del empleado) | Lado remoto (la nube de Aegis) |
|---|---|---|
| Qué hace | Interceptar, detectar y **decidir**: permitir, redactar o bloquear | Clasificar dominios nuevos, panel de diagnóstico, generar la lección pedagógica |
| Qué ve | El contenido completo, en claro | **Nunca** el contenido: solo eventos redactados y metadatos |
| Con qué | Reglas deterministas + modelo pequeño local (ONNX) | LLM vía API |
| Latencia | Camino crítico, presupuesto < 60 ms | Asíncrono, fuera del camino crítico |

Reglas que se derivan y que no se negocian:

1. **Ninguna decisión de bloqueo depende de la red.** Si el equipo está sin internet o el backend
   caído, Aegis sigue protegiendo. El fallo del backend degrada el panel y las lecciones, nunca la
   protección.
2. **El payload interceptado no cruza la frontera.** Lo que sube es el evento redactado descrito en
   el [contrato de datos](../spec/contrato-de-datos.md).
3. **La clasificación de dominios sí es remota**, y no viola nada: lo que viaja es una URL y lo que
   el clasificador lee es el sitio público, nunca el contenido del empleado.
4. **La lección se genera a partir del evento redactado**, no del texto original. El LLM recibe
   "se intentó enviar una credencial de AWS a un dominio de IA no aprobado, el usuario es del área
   de marketing" — suficiente para enseñar, inútil para filtrar.

## Razones

- Es la única versión de la arquitectura que se puede defender frente a un CISO sin una nota al
  pie. La respuesta a "¿ustedes ven mis prompts?" pasa a ser un no, sin matices.
- Protección offline: un DLP que deja de proteger cuando se cae el backend no es un control de
  seguridad, es telemetría.
- Separa limpio el trabajo del equipo: el agente local y el backend se desarrollan en paralelo
  contra el contrato de datos, sin bloquearse.

## Consecuencias

**A favor**

- Cero exposición de contenido, por construcción y no por promesa.
- Latencia predecible: sin llamadas de red en el camino crítico.
- El backend no maneja datos sensibles de los clientes, lo que baja muchísimo su superficie de
  riesgo y de cumplimiento.

**En contra**

- **Sin juez remoto, se pierden las detecciones que dependen de contexto amplio.** Un secreto con
  formato conocido lo atrapa una regla; "esto es el roadmap interno del Q4" es mucho más difícil
  para un modelo pequeño. Se mitiga con tres cosas: huellas de datos internos que la propia empresa
  carga (nombres de clientes, proyectos, repositorios), políticas por área, y una postura de
  *advertir en vez de bloquear* cuando la confianza es baja.
- El modelo local pasa a ser una pieza crítica del producto: hay que versionarlo, distribuirlo y
  actualizarlo. La cadena de actualización del modelo y de las reglas es ahora parte del alcance.

## Efecto sobre el stack

La detección local en Python (ONNX Runtime, y las mismas reglas y tests) y el proxy en Python
(mitmproxy) quedan en el mismo proceso y el mismo lenguaje. Meter el modelo en un agente escrito en
Go implicaría bindings o un sidecar, y no compra nada dentro del plazo del hackathon.
