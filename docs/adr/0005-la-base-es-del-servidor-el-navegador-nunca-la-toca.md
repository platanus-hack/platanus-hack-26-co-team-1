# ADR 0005 — La base es del servidor; el navegador nunca la toca

- **Estado:** aceptado
- **Fecha:** 2026-08-22
- **Extiende:** [ADR 0003](0003-frontera-de-datos-local-decide-remoto-ensena.md)

## Contexto

El panel desplegado guardaba en memoria. El plan gratuito de Render no tiene disco, así que cada
redespliegue —y se redespliega solo cuando nadie entra un rato— se llevaba todo, y el panel tapaba
el hueco mostrando una semana simulada. Sirve para enseñar el producto y no para operarlo: una
demo en la que el incidente que acabás de provocar desaparece al recargar no demuestra nada.

Conectar una base hospedada arregla eso y abre otra cosa, más incómoda: es el momento en que los
eventos de Aegis dejan de vivir en la máquina de la empresa y se van a un tercero. El ADR 0003 dice
que el contenido nunca sale del equipo. Esta es la primera vez que algo cruza de verdad, y el
producto es justamente una herramienta contra la fuga de datos: si Aegis filtrara por su propio
almacén, no habría discusión que valga.

## Decisión

**Supabase es el almacén duradero, se habla con él sólo desde el servidor, y lo que cruza está
nombrado una por una.**

Cuatro puntos, del más importante al menos:

1. **Lista blanca en el borde, no lista negra.** Adentro del sistema alcanza con rechazar: el
   servicio ya tira 422 a cualquier evento con campos prohibidos. Para *salir del equipo* hace
   falta lo contrario. `_a_fila()` proyecta **sólo** las columnas nombradas, así que un campo nuevo
   en el contrato se queda afuera por omisión en vez de filtrarse porque nadie se acordó de venir a
   prohibirlo.

2. **En la tabla no hay ninguna columna donde quepa el contenido.** Es la garantía más fuerte,
   porque no depende de que el código esté bien: aunque la lista blanca se rompiera, no hay dónde
   escribirlo. Y encima van dos `CHECK` que hace cumplir la base misma —no el servicio—: una
   evidencia de más de 32 caracteres dejó de ser una etiqueta y se volvió una cita, y un «dominio»
   con `/` es una URL con su ruta. Los dos rebotan en Postgres.

3. **RLS prendida y sin políticas, y la clave es la `service_role`.** Sin políticas, ni `anon` ni
   `authenticated` pueden tocar nada; sólo la `service_role`, que las saltea. Es exactamente lo que
   hace falta **porque el navegador nunca habla con Supabase**: no hay `anon key` en el front, todo
   pasa por `/api/metrics`. Si el front hablara directo con la base, cualquiera con el panel
   abierto se leería el diccionario de términos de la empresa desde la consola —la lista de sus
   clientes, sus proyectos sin anunciar y sus dominios internos—, que es la información más
   sensible de todo el sistema.

4. **Sin dependencias nuevas.** `requirements.txt` está vacío a propósito y el servicio arranca con
   Python pelado. PostgREST es HTTP con JSON, que es lo que este repositorio ya sabía hacer para
   hablar con el KV. `supabase-py` o `psycopg2` cambiarían el build entero por una comodidad de
   sintaxis.

## Consecuencias

**A favor:** los eventos sobreviven a los redespliegues, así que el panel deja de necesitar la
semana simulada para tener algo que mostrar. La política que se escribe en el panel deja de vivir
en la memoria del navegador. Y los veredictos de dominio pasan a ser compartidos de verdad: un
dominio se investiga una vez en toda la red de clientes.

**En contra:** hay un tercero en el camino, y una credencial más que rotar. Se acota con lo de
arriba: lo que ese tercero puede llegar a tener es un conjunto de etiquetas, dominios y
enumeraciones, nunca una frase que alguien escribió.

**Lo que se sigue de esto:** Supabase es opcional. Sin las variables el sistema entero funciona
igual y guarda en los niveles de abajo (KV, disco, memoria), porque el agente protege sin backend y
el panel se dibuja sin base. Y esos niveles dejan de ser sólo el caso «sin configurar»: son la red
que atrapa al de arriba cuando se cae, porque perder un evento por un almacén caído sería perder
justo el incidente que pasó mientras estaba caído.
