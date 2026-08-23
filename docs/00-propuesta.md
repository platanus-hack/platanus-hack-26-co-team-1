# Aegis — Propuesta

> DLP conversacional con enfoque pedagógico para el uso seguro de IA en la empresa.
>
> Transcripción en Markdown del documento original ([`propuesta-aegis.docx`](propuesta-aegis.docx)),
> conservada aquí para poder versionarla y referenciarla desde el código.

## El problema

Aún con experiencia y criterio técnico, los propios desarrolladores caen en riesgos de
seguridad como compartir credenciales o información no pública de la aplicación con agentes
de IA, o usar herramientas de IA no aprobadas por la empresa. Si ese riesgo existe en equipos
técnicos, es considerablemente mayor en áreas no técnicas — marketing, contabilidad, recursos
humanos — que usan IA en su trabajo diario sin el mismo criterio de seguridad.

El punto de partida de Aegis no es solo evitar la filtración puntual, sino entender que la
mayoría de estos incidentes no nacen de mala intención, sino de una **brecha de comprensión**
sobre qué información no debería compartirse y por qué. Señalar el error después de que ocurre
no cierra esa brecha: la misma persona que hoy comparte una API de Meta con Claude para una
campaña puede mañana compartir datos de usuarios con ChatGPT, si nadie le explicó la lógica
detrás del riesgo.

## Por qué esto importa ahora

| Dato | Hallazgo | Fuente |
|---|---|---|
| **45% vs. 15%** | Proporción de empleados que usan IA de forma regular en dispositivos corporativos, un salto interanual de 15% a 45%. El shadow AI ya es la tercera acción interna no maliciosa más común detectada en datos de DLP, un aumento de 4x en un año. | Verizon, 2026 Data Breach Investigations Report |
| **67%** | De los empleados que acceden a servicios de IA desde dispositivos corporativos lo hacen a través de cuentas personales, no corporativas — fuera de cualquier visibilidad de la empresa. | Verizon, 2026 Data Breach Investigations Report |
| **89%** | De las organizaciones en Latinoamérica sufrió al menos un incidente de seguridad relacionado con APIs en los últimos 12 meses, por encima del promedio global de 87%. | Akamai, API Security Impact Study 2026 (1.840 profesionales, 10 países, 6 sectores) |
| **42%** | De los profesionales de seguridad afirma que las APIs que sostienen sus aplicaciones de IA, agentes o LLMs fueron blanco de ciberataques en el último año. | Akamai, API Security Impact Study 2026 |
| **27%** | De las organizaciones con inventario completo de APIs sabe cuáles de ellas exponen datos sensibles — una caída frente al 40% de 2022, mientras la adopción de IA crece. | Akamai, API Security Impact Study 2026 |

> **Nota sobre las cifras.** Se corrigieron algunos valores de la versión anterior del documento
> (93%, un desglose específico de México, y una muestra de 360 profesionales en Brasil/México)
> porque no pudimos verificarlos contra la fuente pública de Akamai. Las cifras de esta versión
> sí están verificadas contra el estudio original y son, si acaso, más contundentes para el pitch.

## La propuesta

Aegis es la plataforma que permite que los equipos interactúen con agentes de IA sin temer por
filtraciones de datos. Su diferenciador no es solo prevenir la filtración: es **identificar los
comportamientos, patrones y causas humanas** detrás de cada intento, y entregarle al equipo las
herramientas para que ese error no se repita.

> Si alguien de marketing intenta enviarle a Claude Code una API key de Meta para diseñar una
> campaña, no basta con bloquear el envío. Sin una intervención pedagógica, esa misma persona
> puede luego enviar datos de usuarios a ChatGPT. El sistema debe identificar el vacío de
> comprensión — qué información no debería compartirse y por qué — no solo la infracción puntual.

### Idea principal

1. **Modelo local de detección.** Identifica e interviene posibles filtraciones antes de que
   lleguen al modelo externo — una pared entre el empleado y el agente de IA — además de detectar
   fallas de seguridad como el uso de herramientas no aprobadas por la empresa.
2. **Base de datos creciente y colaborativa.** Mantenida por un modelo capaz de catalogar nuevas
   URLs como posibles focos de filtración (*shadow AI*), ampliando su cobertura con el tiempo sin
   depender de una lista estática.
3. **Sistema de enseñanza y monitoreo.** Análisis de las actividades del equipo (quiénes tienen
   mayor riesgo de filtrar información sensible, quiénes intentaron acceder a sitios de IA no
   permitidos, qué tipo de consultas se repiten), con patrones, estrategias propuestas e insights
   accionables para la empresa.
4. **Políticas configurables por la empresa.** Qué tipo de información está prohibido compartir,
   qué herramientas de IA están aprobadas, y qué empleados quedan sujetos a qué reglas según su
   cargo y área.

## Requisitos del MVP

- Instalación sencilla, sin fricción para el usuario final.
- Perfil de empresa (administrador) y perfil de empleado, con roles diferenciados.
- Cobertura tanto para sitios web (URLs) como para herramientas de uso común: **Claude Code**,
  **Codex** y aplicaciones de IA de escritorio.

## Diferenciación

El mercado de prevención de fuga de datos hacia IA (DLP conversacional) y el de gobernanza de
identidades no-humanas está creciendo rápido y ya atrae inversión relevante a nivel global. La
diferenciación de Aegis no está en competir en detección técnica pura, sino en el **enfoque
pedagógico**: convertir cada intento bloqueado en una oportunidad de aprendizaje específico para
esa persona, en su idioma y en el contexto de su rol — algo que las plataformas enterprise
actuales, pensadas para equipos de seguridad, no priorizan.
