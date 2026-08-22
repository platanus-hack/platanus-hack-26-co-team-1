-- Lista negra compartida: un veredicto por dominio, en toda la red de clientes.
--
-- Lo unico que vive aca es "este dominio tiene un modelo detras si/no". Nunca
-- contenido, nunca quien lo visito (ver ADR 0003 y agent/aegis_agent/domains.py).
--
-- La comparacion del camino critico NUNCA toca esta tabla: el agente compara
-- contra un frozenset local con la caminata de sufijos de suffixes.py. Esta
-- tabla solo tiene que ser rapida para sincronizar (GET /v1/domains/sync), no
-- para decidir.

create table if not exists public.dominios (
  dominio          text primary key,
  clasificacion    text not null check (clasificacion in ('ai_unapproved', 'non_ai', 'pending')),
  tipo             text not null default '',
  confianza        real not null default 0,
  evidencia        text not null default '',
  -- seed_list | llm_classifier | heuristic | manual_review | cert_sibling
  fuente           text not null,
  clasificado_en   timestamptz not null default now(),
  -- null = nunca vence (manual_review). Ver backend/aegis_backend/store.py:ttl_for
  vence_en         timestamptz,
  visitas          integer not null default 0,
  actualizado_en   timestamptz not null default now()
);

-- Sirve la sincronizacion incremental: GET /v1/domains/sync?desde=<iso>
create index if not exists dominios_actualizado_idx on public.dominios (actualizado_en);

-- Sirve el barrido de vencidos sin recorrer la tabla entera. Parcial porque
-- un dominio "pending" (nunca se llego a clasificar) no tiene nada que vencer.
create index if not exists dominios_vencidos_idx
  on public.dominios (vence_en)
  where clasificacion <> 'pending';

-- actualizado_en se toca solo en cada escritura, sin depender de que el
-- backend se acuerde de mandarlo.
create or replace function public.dominios_tocar_actualizado_en()
returns trigger
language plpgsql
as $$
begin
  new.actualizado_en = now();
  return new;
end;
$$;

drop trigger if exists dominios_actualizado_en on public.dominios;
create trigger dominios_actualizado_en
  before update on public.dominios
  for each row
  execute function public.dominios_tocar_actualizado_en();

alter table public.dominios enable row level security;

-- Sin politicas: anon y authenticated no ven nada. Solo service_role entra,
-- y esa llave la tiene unicamente el backend (nunca el agente, nunca el
-- panel desplegado). Esto es intencional: bypassea RLS por diseno de
-- Supabase, asi que no hace falta (ni conviene) agregar una policy para el
-- service_role.
