# Aegis

**DLP conversacional con enfoque pedagógico para el uso seguro de IA en la empresa.**

Aegis se interpone entre el empleado y los agentes de IA (Claude Code, Codex, ChatGPT,
Gemini y el largo tail de *shadow AI*) para evitar que información privada — credenciales,
datos de clientes, código no público — salga de la organización. Su diferenciador no es
solo bloquear: es entender **por qué** la persona lo intentó y cerrar esa brecha de
comprensión con intervención pedagógica en el momento del incidente.

## Los tres componentes

1. **Detector local** — clasifica en tiempo real si el texto o archivo que se está enviando
   contiene información que no debería salir (secretos, PII, datos internos).
2. **Base de datos colaborativa de destinos** — lista negra viva de URLs con IA detrás.
   Cada dominio nuevo se investiga **una sola vez** con un modelo y el veredicto se comparte
   entre todos los tenants. Lo único colaborativo del sistema; los incidentes son privados
   por empresa.
3. **Capa pedagógica y de monitoreo** — cada bloqueo se convierte en una lección concreta
   para esa persona, en su idioma y en el contexto de su rol; el admin ve patrones, riesgo
   por área y recomendaciones accionables.

## Estado

Fase de investigación y diseño. Ver:

- [`docs/00-propuesta.md`](docs/00-propuesta.md) — propuesta original (el "qué" y el "por qué").
- [`docs/research/01-interceptacion-de-trafico.md`](docs/research/01-interceptacion-de-trafico.md) — cómo interceptar tráfico en navegador y apps de escritorio.
- [`docs/adr/`](docs/adr) — decisiones de arquitectura.

## Contexto

Proyecto para **Platanus Hack 26 — Bogotá** (21–23 agosto 2026), track de AI Security.
