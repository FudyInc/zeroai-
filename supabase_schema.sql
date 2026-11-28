-- ZERO · esquema Supabase para el CRM
-- Corre esto una vez en Supabase → SQL Editor → New query → Run.

create table if not exists crm_leads (
  id           bigint generated always as identity primary key,
  client_id    text not null,
  lead_key     text not null,
  company      text,
  name         text,
  role         text,
  email        text,
  phone        text,
  domain       text,
  score        integer,
  channel      text,
  stage        text default 'new',
  icp_reasons  jsonb default '[]'::jsonb,
  income_range text,
  income_ok    boolean,
  lead_origin  jsonb,
  outreach     jsonb,
  tags         jsonb default '[]'::jsonb,
  history      jsonb default '[]'::jsonb,
  created      timestamptz default now(),
  updated      timestamptz default now(),
  unique (client_id, lead_key)
);

-- También cubre tablas crm_leads que ya existían antes de agregar respuestas de formularios.
alter table crm_leads add column if not exists income_range text;
alter table crm_leads add column if not exists income_ok boolean;
alter table crm_leads add column if not exists lead_origin jsonb;

create index if not exists crm_leads_client_idx on crm_leads (client_id);
create index if not exists crm_leads_stage_idx  on crm_leads (client_id, stage);

-- Estado de sesión en la nube (ICP por cliente, secuencias de follow-up, contactados).
-- Un snapshot JSON por agencia. Ver zero/memory_supabase.py.
create table if not exists app_state (
  id       text primary key,
  data     jsonb not null default '{}'::jsonb,
  updated  timestamptz default now()
);

-- Versión de la fila para el caché del backend (zero/memory_supabase.py): cada carga
-- compara `updated` y solo baja la fila si cambió, así que TODO update debe moverlo,
-- venga de quien venga. EJECUTAR en el SQL editor de Supabase cuando vuelva la cuota y
-- ANTES de desplegar la rama fix/egress-supabase. Es idempotente.
create or replace function app_state_touch_updated() returns trigger as $$
begin
  new.updated = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists app_state_touch_updated on app_state;
create trigger app_state_touch_updated
  before update on app_state
  for each row execute function app_state_touch_updated();

-- Nota: el backend usa la service_role key (omite RLS). Cuando sumes login de
-- equipo con Supabase Auth, activá RLS y agregá políticas por usuario/cliente.
