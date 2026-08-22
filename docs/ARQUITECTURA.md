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
   → solo se mira la FORMA del request sobre los primeros 4 KB.
     Si no parece una llamada a un modelo, fin. No se escanea nada.
     Si lo parece, pasa a ai_unknown y se manda a clasificar.

5. Se escanea el payload:
   a. se decodifica (gzip, zip, UTF-16, base64, JSON escapado…)
   b. T1: 26 reglas + firmas de archivo        ~0.2 ms
   c. señal de volumen (15 datos personales = un export)
   d. T2: modelo local, SOLO si T1 no vio nada  ~110 ms
   e. se ordenan por especificidad

6. Se cruza el hallazgo con la política:
   secret o internal_data       → bloquear
   pii suelto                   → advertir
   hallazgo del modelo, secret/internal_data → bloquear (salvo AEGIS_T2_ACCION=warn)
   hallazgo del modelo, pii     → advertir

7. Si se bloquea:
   navegación → página HTML con la lección
   fetch/CLI  → JSON con el motivo en error.message

8. Se escribe el evento redactado en disco y se sube en segundo plano.
```

**El paso 4 es el que hace viable todo lo demás.** Un equipo genera miles de
peticiones por hora y casi ninguna va a una IA; escanearlas todas gasta CPU en
cada clic y llena el panel de hallazgos donde el dato nunca estuvo yendo a un
modelo.

## 3. La cascada de detección

| Nivel | Qué es | Dónde corre | Costo | Qué atrapa |
|---|---|---|---|---|
| **T1** | 26 reglas + entropía + Luhn + firmas binarias | Local | ~0.2 ms | Credenciales, volcados, exports, documentos de identidad, archivos críticos |
| **Volumen** | Agregación sobre los hallazgos de T1 | Local | 0 | Un export de clientes que línea a línea parece inocente |
| **T2** | Modelo de entidades (~50M parámetros) | Local | ~110 ms | Lo que no tiene formato: nombres de clientes, cifras de contratos, datos de salud |

T2 corre **solo si T1 no encontró nada**. Si ya hay una credencial detectada,
gastar 110 ms más no cambia la decisión ni la lección.

## 4. Anti-evasión

`detect/payload.py` no escanea el body tal cual llega: arma vistas derivadas.

| Vector | Cómo se cubre |
|---|---|
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

1. **Catálogo local** (`catalog.py`): 112 dominios en siete categorías. Resolución
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
