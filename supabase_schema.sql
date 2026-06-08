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
  outreach     jsonb,
  tags         jsonb default '[]'::jsonb,
  history      jsonb default '[]'::jsonb,
  created      timestamptz default now(),
  updated      timestamptz default now(),
  unique (client_id, lead_key)
);

create index if not exists crm_leads_client_idx on crm_leads (client_id);
create index if not exists crm_leads_stage_idx  on crm_leads (client_id, stage);

-- Estado de sesión en la nube (ICP por cliente, secuencias de follow-up, contactados).
-- Un snapshot JSON por agencia. Ver zero/memory_supabase.py.
create table if not exists app_state (
  id       text primary key,
  data     jsonb not null default '{}'::jsonb,
  updated  timestamptz default now()
);

-- Nota: el backend usa la service_role key (omite RLS). Cuando sumes login de
-- equipo con Supabase Auth, activá RLS y agregá políticas por usuario/cliente.
