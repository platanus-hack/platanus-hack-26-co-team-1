# Investigación 02 — El motor de detección: qué corre local y qué no

**Pregunta que responde este documento:** si Aegis tiene que cubrir *toda* la IA que corra en una
computadora, ¿es factible analizar cada cosa que se envía? ¿Hace falta un LLM local?

**Respuesta corta:** sí es factible, y **no** hace falta un LLM local — pero solo si se respeta el
orden del embudo. El error de diseño sería analizar todo el tráfico con un modelo. Lo correcto es
que el **destino filtre primero** y reduzca el volumen dos órdenes de magnitud, y que sobre ese
resto sobreviviente corra una cascada donde el modelo caro es el último recurso, no el primero.

---

## 1. El embudo: el destino filtra antes que el contenido

Un equipo genera miles de peticiones HTTP por hora: telemetría, CDNs, actualizaciones, Google
Drive, Slack, Spotify. **Nada de eso hay que analizarlo.** Aegis solo inspecciona el contenido de
una conexión cuando su destino ya está clasificado como servicio de IA.

```
100%  conexiones del equipo
 │
 ├─ passthrough inmediato (banca, salud, SO, dominios corporativos)   ← ni se descifra
 │
 ├─ registro de metadatos: proceso + dominio + hora                   ← alimenta el inventario
 │
 └─ ~1-3%  destino clasificado como IA  ────────────▶  INSPECCIÓN DE CONTENIDO
                                                       (aquí corre la cascada)
```

Esto es lo que hace factible todo lo demás. No estamos escaneando Netflix: estamos escaneando la
fracción del tráfico que va a un endpoint de IA. Y el costo de decidir "¿este dominio es IA?" es
una búsqueda en un cache local — no un modelo.

**El dominio desconocido es el único caso que cuesta.** Se clasifica **una sola vez** con un LLM,
el veredicto se guarda en la base colaborativa y se reparte a todos los clientes. El segundo
usuario del mundo que visite ese dominio ya no paga nada. Mientras la clasificación está en curso,
la política decide: bloquear por precaución o permitir y marcar.

---

## 2. La cascada de detección: cuatro niveles, el caro al final

Sobre ese 1-3% que sí hay que mirar:

| Nivel | Qué es | Dónde corre | Costo | Qué atrapa |
|---|---|---|---|---|
| **T1 — Determinista** | Reglas de secretos (estilo gitleaks), entropía de Shannon, formatos conocidos, huellas de datos internos de la empresa | Local | Microsegundos, sin modelo | API keys, tokens, connection strings, claves privadas, tarjetas, documentos. La mayoría de los incidentes reales. |
| **T2 — Modelo pequeño local** | NER de PII cuantizado a INT8 en ONNX (DeBERTa-small, GLiNER y similares) | Local | Milisegundos en CPU, 40-100 MB de modelo | Nombres, direcciones, datos de clientes, PII que no tiene formato fijo |
| **T3 — LLM juez** | Solo para lo ambiguo, **con el payload ya redactado por T1/T2** | API remota (o local en modo air-gapped) | Cientos de ms, unos pocos casos | Contexto: "esto es el roadmap interno", "esto es código propietario" |
| **T4 — Pedagogía** | Genera la lección para esa persona y ese incidente | API remota, **asíncrona** | Fuera del camino crítico | No decide nada: explica después |

Dos decisiones que sostienen el diseño:

**T2 es un modelo local de verdad, y sí es factible.** La confusión frecuente es asumir que
"modelo local" significa "LLM local". Un encoder pequeño cuantizado corre en CPU en milisegundos y
pesa menos que una imagen de Docker. Es lo que usan las soluciones de redacción de PII on-device.
Un LLM local (Llama 3.2 3B, Qwen 2.5) es otra cosa: gigabytes de RAM y latencia de segundos en CPU
— viable solo como T3 en modo air-gapped, nunca en el camino crítico de cada request.

**T4 no bloquea.** La lección pedagógica se genera *después* de que la decisión ya se tomó y se le
mostró al usuario un mensaje inmediato. Sacar el LLM del camino crítico es lo que permite que el
producto sea al mismo tiempo pedagógico y rápido.

---

## 3. La contradicción que hay que evitar (y que es argumento de venta)

Un DLP que manda todo el contenido inspeccionado a una API de IA en la nube **es exactamente la
fuga que dice prevenir**. Si el prompt con la API key de Meta va a nuestro servidor para ser
analizado, el dato salió igual — solo cambió el destinatario.

Por eso T1 y T2 son locales por diseño, no por optimización, y a T3 solo llega texto ya redactado
y solo cuando los niveles anteriores no alcanzaron. Es una decisión de arquitectura defendible
frente a un CISO, y es de las primeras preguntas que va a hacer un jurado técnico.

---

## 4. Presupuesto de latencia

El proxy está en el camino crítico: si Aegis agrega un segundo a cada request, el empleado
desinstala Aegis. Objetivo por request inspeccionado:

| Etapa | Presupuesto |
|---|---|
| Clasificación de destino (cache hit) | < 1 ms |
| T1 determinista | < 5 ms |
| T2 modelo local | < 50 ms |
| T3 LLM juez (solo lo ambiguo, estimado 2-5% de los casos) | 200-800 ms |
| **Total típico (T1/T2 resuelven)** | **< 60 ms** |

Los números de T1 y T2 son estimaciones a validar con medición propia durante el desarrollo, no
benchmarks publicados. La decisión de arquitectura no depende de que sean exactos: depende de que
el orden sea barato → caro, y de que el caro se ejecute pocas veces.

---

## 5. Consecuencia para el alcance

Nada de esta cascada sabe qué aplicación originó el tráfico. Recibe *texto que va hacia un
destino* y decide. Por eso el mismo motor cubre Claude Code, ChatGPT en el navegador, Cursor,
Copilot, una app de escritorio desconocida o un script de Python — la cobertura la da el punto de
intercepción (ver [Investigación 01](01-interceptacion-de-trafico.md)), no el detector.

---

## Fuentes

- [Arcjet — Running PII detection locally with the Rampart NER model](https://blog.arcjet.com/running-pii-detection-locally-with-the-rampart-ner-model/)
- [hoop.dev — Lightweight CPU-only PII detection model](https://hoop.dev/blog/lightweight-cpu-only-pii-detection-ai-model-for-fast-secure-data-processing)
- [GLiNER PII small (ONNX cuantizado)](https://huggingface.co/knowledgator/gliner-pii-small-v1.0)
- [DeBERTa-small para redacción de PII](https://huggingface.co/bengid/pii-redaction-deberta-small)
- [Protecto — Comparación de modelos NER para identificación de PII](https://www.protecto.ai/blog/best-ner-models-for-pii-identification/)
- [Microsoft Presidio — detección de PII](https://explainx.ai/blog/microsoft-presidio-pii-detection-anonymization-guide-2026)
