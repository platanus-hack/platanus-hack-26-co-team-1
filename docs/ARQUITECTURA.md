# Arquitectura

Cómo encaja todo y, sobre todo, por dónde pasa un request desde que sale del
navegador hasta que se bloquea o se deja ir.

---

## 1. Las piezas

```
┌──────────────────── EQUIPO DEL EMPLEADO ─────────────────────┐
│                                                              │
│  navegador ─┐                                                │
│  CLIs ──────┼─▶ proxy local (mitmproxy + addon de Aegis)      │
│  IDEs ──────┤        │                                       │
│  apps ──────┘        ├─ catalog.py    ¿el destino es IA?     │
│                      ├─ signals.py    ¿se comporta como IA?  │
│                      ├─ detect/       ¿qué lleva adentro?    │
│                      ├─ lessons.py    ¿qué le explico?       │
│                      └─ events.py     cola en disco          │
└──────────────────────────────┬───────────────────────────────┘
                               │  solo eventos redactados
              ┌────────────────┴────────────────┐
              ▼                                 ▼
     backend (base colaborativa)          panel de la empresa
     un dominio se clasifica una          métricas, áreas de riesgo,
     vez para toda la red                 reincidencia
```

| Carpeta | Qué vive ahí |
|---|---|
| `agent/aegis_agent/detect/` | El motor: reglas, normalización, archivos, modelo |
| `agent/aegis_agent/proxy/` | Addon de mitmproxy, página de bloqueo |
| `agent/aegis_agent/panel/` | Métricas y render del panel |
| `agent/aegis_agent/install/` | Instalador de Windows |
| `backend/aegis_backend/` | Base colaborativa de dominios y clasificador |
| `web/app.py` | El panel y la base, como servicio web en Render |

## 2. El camino de un request

Este es el orden real del código en `proxy/addon.py`, y el orden importa: cada
paso existe para no pagar el siguiente.

```
1. ¿El destino está en passthrough?          → sale sin descifrar. Fin.
   (banca, salud, gov.co, updates del SO)

2. ¿El destino es IA no aprobada?
   modo estricto     → se corta el destino. Fin.
   modo equilibrado  → se registra el uso y se sigue inspeccionando.

3. ¿El método lleva payload? (POST/PUT/PATCH)  Si no, fin.

4. ¿El destino es non_ai?
   → se le hacen DOS preguntas sobre los primeros 4 KB, y ninguna sola alcanza:

     a. ¿tiene forma de llamada a un modelo? (claves messages, prompt, model)
     b. ¿es un archivo yendose, y yendose hacia una IA?
        (multipart con filename, o Content-Type binario, o firma de archivo
         — Y el Origin/Referer del request apunta a un dominio de IA)

     Si ninguna, fin: no se escanea nada.
     Si alguna, pasa a ai_unknown y se manda a clasificar.

5. ¿El texto trae órdenes dirigidas al modelo?
   Es la dirección contraria: no un dato que sale, sino una instrucción para
   que salga. Va antes del escaneo porque en ese momento **todavía no hay
   ningún dato sensible en el texto**.

6. Se escanea el payload:
   a. se decodifica (gzip, zip, PDF, UTF-16, base64, hex, JSON escapado…)
      y se normaliza (invisibles, homoglifos, NFKC)
   b. T1: 28 reglas + firmas de archivo   ~1 ms por KB, techo de 500 ms
   c. señal de volumen (15 datos personales = un export)
   d. OCR de las imágenes, si está prendido      ~2 s  (apagado por defecto)
   e. T2: modelo local, SOLO si T1 no vio nada  ~110 ms
   f. se ordenan por especificidad

7. Se cruza el hallazgo con la política:
   secret o internal_data       → bloquear
   pii suelto                   → advertir
   hallazgo del modelo, secret/internal_data → bloquear (salvo AEGIS_T2_ACCION=warn)
   hallazgo del modelo, pii     → advertir

8. Si se bloquea:
   navegación → página HTML con la lección
   fetch/CLI  → JSON con el motivo en error.message

9. Se escribe el evento redactado en disco y se sube en segundo plano.

10. Y al volver, se mira la respuesta con las mismas reglas de inyección.
    Ahí solo se registra: cuando la respuesta llega, el modelo ya la generó.
```

**El paso 4 es el que hace viable todo lo demás.** Un equipo genera miles de
peticiones por hora y casi ninguna va a una IA; escanearlas todas gasta CPU en
cada clic y llena el panel de hallazgos donde el dato nunca estuvo yendo a un
modelo.

**Y la pregunta (b) existe porque durante un tiempo el paso 4 preguntó una sola
cosa, y por ahí se iba el adjunto entero.** Cuando alguien arrastra un archivo a
ChatGPT, los bytes no van a `chatgpt.com`: van a `files.oaiusercontent.com`. Ese
host no estaba en el catálogo —ningún catálogo de "aplicaciones de IA" lista los
endpoints de subida— y la pregunta (a) tampoco lo rescataba, porque busca la
forma de una *conversación* y una subida no tiene ninguna de esas claves.
Resultado: la acción más común y más fácil de sacar un documento completo no
disparaba nada. No era una regla que faltaba, era un agujero en el embudo.

Las dos condiciones de (b) se piden **juntas** a propósito. Una subida sola es la
navegación normal —una foto de perfil, un adjunto a un ticket de Jira— y
escanearla es exactamente lo que el embudo existe para evitar. Lo que la vuelve
interesante es que salga desde la página de una IA, y eso el propio request lo
dice: el navegador pone `Origin: https://chatgpt.com` en la subida al host de
blobs. No hay que adivinar ni guardar estado.

Lo que **todavía** no cubre (b) es la app de escritorio que no manda `Origin`.
Para ese caso hace falta saber qué proceso abrió la conexión, y esa señal la
construye la atribución por proceso: el punto de enganche está marcado en
`subidas.py` y es una línea.

## 3. La cascada de detección

| Nivel | Qué es | Dónde corre | Costo | Qué atrapa |
|---|---|---|---|---|
| **T1** | 28 reglas + entropía + Luhn + firmas binarias | Local | **~1 ms/KB**, techo 500 ms | Credenciales, volcados, exports, documentos de identidad, archivos críticos |
| **Volumen** | Agregación sobre los hallazgos de T1 | Local | 0 | Un export de clientes que línea a línea parece inocente |
| **OCR** | Lectura del texto de una imagen | Local | **~2 s** | El pantallazo, que era el canal invisible. Apagado por defecto: ver abajo |
| **T2** | Modelo de entidades (289M parámetros) | Local | ~110 ms | Lo que no tiene formato: nombres de clientes, cifras de contratos, datos de salud |
| **Inyección** | 3 reglas, en las dos direcciones | Local | ~0.1 ms | Órdenes escritas para el modelo dentro del contenido: el ataque que convierte a la herramienta en el que filtra |

T2 corre **solo si T1 no encontró nada**. Si ya hay una credencial detectada,
gastar 110 ms más no cambia la decisión ni la lección.

**Y el nivel más caro de la cascada no es el modelo: es el OCR.** Medido en CPU
sobre una captura de 900×260, la inferencia da p50 1,7 s con la máquina
descansada y entre 5 y 9 s con la máquina ocupada — entre dos y trece veces el
presupuesto *completo* de T2. Por eso está apagado por defecto (`AEGIS_OCR=1`) y
por eso su presupuesto se mide en segundos y no en milisegundos: cuando está
prendido, se paga sólo en un envío **con imagen**, que es una acción puntual que
la persona acaba de iniciar y donde ya espera una demora. No es un tecleo.

**T1 también tiene presupuesto ahora, y hacía falta.** No costaba 0,2 ms sino
del orden de 1 ms por KB: cierto sobre un prompt corto, falso sobre el pegado de
un documento, que es el caso que importa. Un cuerpo de 1 MB tardaba cerca de un
segundo. Ahora una vista grande se recorre por segmentos con un techo de 500 ms,
y **el orden de los segmentos es cabeza → cola → medio**, porque si el
presupuesto corta el recorrido lo que tiene que quedar sin mirar es la parte
menos peligrosa: este proyecto ya documentó que el secreto al final de un archivo
grande es la evasión más barata que existe. La cabeza y la cola se miran
**siempre**, sin importar el presupuesto — una garantía que depende de que sobre
tiempo no es una garantía. Y cuando algo queda sin mirar, el evento lo dice
(`truncated`): un escaneo incompleto en silencio es una promesa que el producto
no está cumpliendo.

## 4. Anti-evasión

`detect/payload.py` no escanea el body tal cual llega: arma vistas derivadas.

| Vector | Cómo se cubre |
|---|---|
| **captura de pantalla** | OCR local, si está prendido. Era el canal invisible |
| **PDF** (`FlateDecode`) | se descomprimen los streams. El de Word, Docs y LaTeX |
| **carácter de ancho cero** dentro del secreto | normalización. Y aparece **solo** al copiar de una web |
| **homoglifo** (А cirílica por A latina) | tabla de confusables; NFKC no los toca |
| hexdump | se decodifican las corridas largas si salen como texto |
| gzip / brotli en el transporte | `get_content()` en vez de `raw_content` |
| `.gz` como adjunto | firma `1f 8b` y descompresión |
| `.docx`, `.xlsx` (son zips) | se leen los miembros de texto |
| base64, y base64 de base64 | se decodifican hasta dos niveles |
| percent-encoding | `unquote_plus` |
| comillas escapadas del JSON | vista sin escapes |
| UTF-16 con y sin BOM | detección por densidad de nulos |
| secreto partido con espacios | vista compacta sin espacios |
| secreto al final de un archivo grande | se conservan cabeza **y** cola |
| archivo renombrado | firmas binarias (SQLite, PGDMP, llaves SSH) |

## 5. Clasificación de destinos

Tres fuentes, de más barata a más cara:

1. **Catálogo local** (`catalog.py`): 167 dominios en trece categorías, más
   siete **patrones** de host. Los patrones cubren a los proveedores que tienen
   un host por región: `bedrock-runtime.us-east-1` estaba en la lista literal y
   las otras diecinueve regiones no, así que Bedrock estaba cubierto en un 5%.
   Se consultan solo cuando la lista literal no dijo nada, y son estrechos a
   propósito: un patrón ancho sobre `blob.core.windows.net` convertiría el
   almacenamiento propio de la empresa en un destino de IA. Resolución
   por especificidad: gana el dominio más largo que matchea, y por eso
   `copilot.microsoft.com` es IA aunque `microsoft.com` esté en passthrough.
2. **Forma del request** (`policy.looks_like_ai_api`): rutas y claves del cuerpo
   que solo aparecen en una llamada a un modelo. Pistas fuertes y débiles con
   pesos distintos, para no confundir el sistema de facturación con un chat.
3. **Comportamiento** (`signals.py`): sobre todo el streaming por eventos, que es
   la huella más fiable que existe. Cuando un dominio junta suficientes señales,
   se manda al backend para que lo investigue **una sola vez para toda la red**.

## 6. La frontera de datos

Lo único que cruza del equipo hacia afuera:

```jsonc
{
  "destination": { "domain": "chatgpt.com", "classification": "ai_unapproved" },
  "detection":   { "rule_id": "aws_access_key_id", "evidence": "AKIA****" },
  "action": "blocked",
  "actor": { "user_id": "u_8f21", "area": "marketing" }
}
```

Nunca el texto, nunca la URL completa, nunca el nombre real de la persona. El
backend **rechaza con 422** cualquier evento que traiga contenido: la frontera no
puede depender de que el agente se porte bien, porque el endpoint es público.

Detalle completo en [el contrato de datos](spec/contrato-de-datos.md).

## 7. Qué pasa cuando algo se cae

| Se cae | Qué sigue funcionando |
|---|---|
| El backend | Todo. La decisión es local; los veredictos de dominios quedan en caché |
| El panel remoto | Todo. Los eventos se escriben en disco primero |
| El modelo T2 | T1 completo. T2 es opcional por diseño |
| La red entera | La protección completa. Ninguna decisión hace una llamada de red |

La ausencia de veredicto nunca es un permiso.
