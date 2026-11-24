-- Guessed emails: when a guess bounces, try the person's next likely address.
--
-- contacts.email always holds the address currently being tried.
-- email_pattern is the pattern it came from (e.g. '{first}.{last}'); null for real addresses
-- copied from a bio page, which are never swapped.
-- email_patterns_left are the patterns not tried yet, most likely first.

alter table contacts add column if not exists email_domain        text;
alter table contacts add column if not exists email_pattern       text;
alter table contacts add column if not exists email_patterns_left text[] not null default '{}';

-- Which pattern each send used, so the sender learns each firm's format from what bounces.
alter table sends add column if not exists email_pattern text;
create index if not exists sends_to_domain on sends ((split_part(to_email, '@', 2)));
