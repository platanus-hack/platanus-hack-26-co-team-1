# Contrato de datos entre el agente local y el backend

Este documento define **exactamente qué cruza la frontera** establecida en el
[ADR 0003](../adr/0003-frontera-de-datos-local-decide-remoto-ensena.md). Es también la interfaz que
permite que el agente y el backend se desarrollen en paralelo.

Regla que gobierna todo lo demás: **el contenido interceptado nunca sube**. Lo que sube es la
descripción de un hallazgo, no el hallazgo.

---

## 1. Evento de incidente — `POST /v1/events`

Lo emite el agente después de tomar la decisión, de forma asíncrona. Si falla el envío, se encola
en disco y se reintenta; nunca bloquea al usuario.

```jsonc
{
  "event_id": "01J8...",              // ULID generado local, idempotencia
  "tenant_id": "acme",
  "actor": {
    "user_id": "u_8f21",              // seudónimo estable, no el email
    "area": "marketing",              // para la pedagogía y los agregados
    "role": "employee"
  },
  "destination": {
    "domain": "chat.deepseek.com",    // dominio, NO la URL completa (la ruta puede llevar datos)
    "classification": "ai_unapproved", // ai_approved | ai_unapproved | unknown | non_ai
    "process": "chrome.exe"
  },
  "detection": {
    "rule_id": "aws_access_key_id",
    "category": "secret",             // secret | pii | internal_data | policy
    "severity": "critical",           // critical | high | medium | low
    "confidence": 0.99,
    "engine": "t1_rules",             // t1_rules | t2_model
    "evidence": "AKIA****************",  // SIEMPRE redactado, máx. 32 caracteres
    "match_count": 1
  },
  "action": "blocked",                // blocked | redacted | warned | allowed
  "payload_stats": {                  // estadística, no contenido
    "bytes": 4821,
    "language": "es"
  },
  "occurred_at": "2026-08-22T14:03:11Z",
  "agent_version": "0.1.0",
  "ruleset_version": "2026.08.22"
}
```

**Prohibido en este payload**, y verificado por test: el texto original completo o parcial sin
redactar, la URL con query string o path, el contenido del archivo adjunto, el nombre real o el
email del empleado, rutas locales del sistema de archivos.

### Cómo se redacta la evidencia

La evidencia existe para que el admin reconozca el tipo de secreto, no para reconstruirlo. Regla:
**máximo los primeros 4 caracteres visibles, el resto enmascarado, máximo 32 caracteres de
salida**. Para PII, ni siquiera eso: se reporta el tipo (`email`, `national_id`) sin muestra.

---

## 2. Consulta de clasificación de dominio — `GET /v1/domains/{domain}`

El agente consulta su cache local primero. Solo si el dominio es desconocido pregunta al backend.

```jsonc
// respuesta
{
  "domain": "chat.deepseek.com",
  "classification": "ai_unapproved",
  "kind": "llm_chat",                 // llm_chat | llm_api | ai_feature | non_ai
  "confidence": 0.96,
  "evidence": "Interfaz de chat con modelos propios; formulario de subida de archivos.",
  "classified_at": "2026-08-20T09:12:00Z",
  "source": "llm_classifier",         // seed_list | llm_classifier | manual_review
  "ttl_seconds": 604800
}
```

Si el dominio no existe todavía en la base, el backend responde `202 Accepted` y lo encola para
clasificar. Mientras tanto manda la política de la empresa para dominios desconocidos
(`block` o `warn`). **Lo único que viaja acá es un nombre de dominio.**

---

## 3. Lección pedagógica — `POST /v1/lessons`

Se pide a partir de un `event_id` ya subido. El backend arma el prompt con los campos del evento —
nunca con contenido — y devuelve la lección para mostrarle a esa persona.

```jsonc
// request
{ "event_id": "01J8...", "locale": "es-CO" }

// respuesta
{
  "title": "Las credenciales de AWS no se comparten con herramientas de IA",
  "body": "Lo que intentaste enviar era una llave de acceso...",
  "why_it_matters": "...",
  "what_to_do_instead": "...",
  "estimated_read_seconds": 40
}
```

El LLM remoto ve, como máximo: tipo de detección, severidad, área y rol del empleado, tipo de
destino, y si es reincidencia. Es suficiente para enseñar e inútil para filtrar.

---

## 4. Política de la empresa — `GET /v1/policy`

El agente la descarga y **la cachea en disco**. Sin conexión, sigue aplicando la última que tenga.

```jsonc
{
  "policy_version": 14,
  "unknown_domain_action": "warn",
  "approved_ai": ["claude.ai", "api.anthropic.com"],
  "passthrough": ["*.bancolombia.com", "*.gov.co", "*.windowsupdate.com"],
  "rules": { "secret": "block", "pii": "warn", "internal_data": "warn" },
  "by_area": { "finance": { "pii": "block" } },
  "internal_fingerprints_url": "/v1/fingerprints"   // hashes, nunca los valores en claro
}
```

Las huellas de datos internos (nombres de clientes, proyectos, repositorios) se distribuyen como
**hashes**: el agente compara localmente sin que el backend sepa contra qué está comparando.

---

## 5. Invariantes verificables

Estos puntos van como tests automáticos, no como buenas intenciones:

1. Ningún campo emitido por el agente contiene texto del payload sin redactar.
2. `destination` lleva dominio, nunca path ni query string.
3. La evidencia redactada nunca supera 32 caracteres ni muestra más de 4 sin enmascarar.
4. Con el backend caído, el agente sigue decidiendo y encolando.
5. Con la política en cache y sin red, el comportamiento es idéntico al de con red.
