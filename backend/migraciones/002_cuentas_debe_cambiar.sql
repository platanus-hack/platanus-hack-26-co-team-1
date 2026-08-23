-- La contrasena temporal: una cuenta que todavia no eligio la suya.
--
-- Cuando un admin da de alta a un colaborador desde el panel, la cuenta nace
-- con una contrasena que la persona no eligio y que le llega por otro canal
-- --un chat, un mail, alguien dictandosela--. Esta columna es lo que hace que
-- el primer ingreso frene en la pantalla de onboarding hasta que elija la suya,
-- en vez de dejarla trabajando para siempre con la que le entregaron.
--
-- La escribe cuentas.guardar(..., debe_cambiar=True) y la apaga PUT /v1/password.
--
-- POR QUE ESTO ES UNA MIGRACION Y NO SE NOTO ANTES
--
-- El codigo que la usa venia de una rama (auth de colaborador) y la tabla se
-- habia creado a mano, antes, sin ella. Nada se pone rojo cuando falta:
--
--   1. PostgREST rechaza el INSERT con 400, porque la columna no existe.
--   2. supabase._pedir() se lo traga y devuelve None. Es a proposito: "nadie
--      deberia quedarse sin panel porque un servicio de terceros tardo".
--   3. cuentas.guardar() igual escribe en _memoria y devuelve la fila.
--   4. El panel muestra "colaborador creado".
--   5. La cuenta vive solo en la memoria de ESE proceso, y se va en el proximo
--      redespliegue -o cuando el plan gratuito de Render duerma la instancia
--      por inactividad, que pasa solo-.
--
-- Y la suite no lo ve porque corre contra el almacen en memoria, que es
-- justamente el unico camino de los cinco que funciona.
--
-- Es idempotente: correrla dos veces no hace nada la segunda.

alter table public.aegis_cuentas
  add column if not exists debe_cambiar boolean not null default false;

-- `not null default false` y no nullable: el default tiene que ser el caso
-- SEGURO. Una fila vieja -las cuentas de admin que ya existen- no eligio
-- ninguna contrasena temporal, asi que no tiene nada que cambiar, y frenarlas
-- en onboarding seria dejar afuera del panel a quien ya estaba adentro.
