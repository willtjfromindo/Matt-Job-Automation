-- Outreach: initial schema.
-- Shared by the website (Vercel), the sender (Railway) and the pipeline scripts.

create table if not exists firms (
  id                serial primary key,
  name              text not null unique,
  career_paths      text[] not null,              -- any of 'IB', 'PE', 'VC'
  per_office        boolean not null default false, -- quota per office (LA/NY/SF/Chicago) instead of per firm
  rotation_position integer,                      -- order in the round-robin (1 = first)
  rank_source       text,                         -- e.g. 'PEI 300 #12'
  domain            text,                         -- e.g. 'blackstone.com', optional
  active            boolean not null default true,
  created_at        timestamptz not null default now()
);

create table if not exists contacts (
  id                     serial primary key,
  first_name             text not null,
  last_name              text not null,
  firm_id                integer not null references firms(id),
  career_path            text not null check (career_path in ('IB', 'PE', 'VC')),
  title                  text not null,
  team                   text,
  focus                  text,
  seniority              text check (seniority in ('junior', 'mid', 'senior')),
  office                 text,                     -- 'LA', 'NY', 'SF', 'Chicago' or 'Other'
  location               text,
  timezone               text,
  years_at_firm          numeric,
  email                  text not null,
  email_status           text not null default 'unchecked', -- unchecked / valid / risky / invalid
  profile_url            text,
  education              text,
  past_employers         text,
  interests              text,
  headline_or_bio        text,
  source                 text,                     -- import file name
  ucla_connection        boolean not null default false,
  bain_connection        boolean not null default false,
  other_connection       text,
  personalization_tier   text check (personalization_tier in ('A', 'B', 'C', 'D', 'E')),
  personalization_source text,                     -- record field the evidence came from
  personalization_fact   text,                     -- exact quote from that field
  selected               boolean not null default false, -- inside the 20-per-firm/office quota
  send_order             integer unique,
  status                 text not null default 'new',
    -- new / ready / sent / followup1 / followup2 / replied / meeting / closed / blocked
  skip_reason            text,
  follow_up_count        integer not null default 0,
  last_contacted_at      timestamptz,
  follow_up_date         timestamptz,
  gmail_thread_id        text,
  first_message_id       text,                     -- RFC Message-ID of the first email (for threading)
  first_subject          text,
  created_at             timestamptz not null default now(),
  unique (email)
);
create index if not exists contacts_status_order on contacts (status, send_order);
create index if not exists contacts_thread on contacts (gmail_thread_id);
create index if not exists contacts_firm on contacts (firm_id);

create table if not exists drafts (
  id            serial primary key,
  contact_id    integer not null references contacts(id) on delete cascade,
  kind          text not null check (kind in ('first', 'followup1', 'followup2')),
  template      text not null,
  subject       text not null,
  body          text not null,
  personal_line text,
  evidence      jsonb,
  qa_passed     boolean not null default false,
  qa_issues     jsonb,
  attempts      integer not null default 1,
  created_at    timestamptz not null default now(),
  unique (contact_id, kind)
);

create table if not exists runs (
  id              serial primary key,
  requested_count integer not null check (requested_count between 1 and 1000),
  sent_count      integer not null default 0,
  status          text not null default 'running',
    -- running / stopping / stopped / done / auto_stopped / error
  message         text,
  started_by      text,
  started_at      timestamptz not null default now(),
  ended_at        timestamptz
);
-- Only one run can be active at a time.
create unique index if not exists runs_one_active on runs ((true)) where status in ('running', 'stopping');

create table if not exists sends (
  id               serial primary key,
  run_id           integer references runs(id),
  contact_id       integer not null references contacts(id),
  draft_id         integer references drafts(id),
  kind             text not null,
  to_email         text not null,                -- address actually used (practice inbox in practice mode)
  sent_at          timestamptz not null default now(),
  gmail_message_id text,
  gmail_thread_id  text,
  rfc_message_id   text,
  practice         boolean not null default true,
  status           text not null default 'sent', -- sent / failed / bounced
  error            text
);
create index if not exists sends_sent_at on sends (sent_at);
create index if not exists sends_run on sends (run_id);

create table if not exists suppression (
  email    text primary key,
  reason   text not null,                          -- opted_out / bounced / not_interested / manual
  added_at timestamptz not null default now()
);

create table if not exists google_tokens (
  email                   text primary key,
  encrypted_refresh_token text not null,           -- AES-256-GCM, see README "Token encryption"
  scopes                  text,
  status                  text not null default 'ok', -- ok / needs_reauth
  updated_at              timestamptz not null default now()
);

create table if not exists inbox_seen (
  gmail_message_id text primary key,
  seen_at          timestamptz not null default now()
);

create table if not exists app_state (
  key   text primary key,
  value jsonb not null
);

-- Lock everything down: only server-side code with the database password can read or write.
alter table firms         enable row level security;
alter table contacts      enable row level security;
alter table drafts        enable row level security;
alter table runs          enable row level security;
alter table sends         enable row level security;
alter table suppression   enable row level security;
alter table google_tokens enable row level security;
alter table inbox_seen    enable row level security;
alter table app_state     enable row level security;
