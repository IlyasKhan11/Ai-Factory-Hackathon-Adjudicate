-- Adjudicate — Supabase schema
--
-- Use this if there is no schema yet, or to diff against Burhan's existing
-- one. These are exactly the tables and columns supabase_client.py reads and
-- writes: if the live project matches this, storage works with no code
-- changes. Run it in the Supabase dashboard -> SQL Editor.
--
-- Verify afterwards with:  python check_schema.py

create table if not exists claims (
  id          uuid primary key default gen_random_uuid(),
  risk_tier   text,
  created_at  timestamptz default now()
);

create table if not exists intake_sessions (
  id          uuid primary key default gen_random_uuid(),
  claim_id    uuid references claims(id),
  status      text not null default 'active',   -- 'active' | 'completed'
  created_at  timestamptz default now()
);

create table if not exists extracted_fields (
  id          bigserial primary key,
  session_id  uuid references intake_sessions(id),
  field_name  text not null,   -- date | location | vehicle | cause | injuries | stated_damage | repair_shop
  field_value text,
  confidence  real,            -- 0-1
  created_at  timestamptz default now(),
  -- Lets you switch the insert in save_extracted_field() to an upsert if
  -- duplicate rows ever become a problem.
  unique (session_id, field_name)
);

create table if not exists contradictions (
  id             bigserial primary key,
  claim_id       uuid references claims(id),
  field_name     text,
  claimed_value  text,
  evidence_value text,
  verdict        text,   -- CONTRADICTED | SUSPICIOUS | OVERSTATED | CANNOT_DETERMINE | CONSISTENT
  detail         text,   -- e.g. "15%" for OVERSTATED
  source_url     text,
  confidence     real,
  created_at     timestamptz default now()
);

create table if not exists verdicts (
  id          bigserial primary key,   -- serial, not uuid: get_latest_verdict() orders on this
  claim_id    uuid references claims(id),
  risk_score  int,                     -- 0-100
  risk_tier   text,                    -- fast_track | standard | investigate
  summary     text,
  created_at  timestamptz default now()
);

create table if not exists audit_log (
  id          bigserial primary key,
  claim_id    uuid,
  event_type  text,   -- intake_started | intake_ended | dossier_computed
  payload     jsonb,
  created_at  timestamptz default now()
);

-- A claim row to demo against. The frontend opens
-- /ws/intake/{claim_id} with this id.
insert into claims (id) values ('11111111-1111-1111-1111-111111111111')
on conflict (id) do nothing;

-- RLS is off by default on new tables. That's correct for this build: only
-- the backend touches Supabase, and it holds the service-role key (which
-- bypasses RLS anyway). The rule that matters is that the service key must
-- never reach the frontend bundle. Turn RLS on before this sees real
-- claimant data.
