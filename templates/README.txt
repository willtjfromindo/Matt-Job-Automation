EMAIL TEMPLATES

First emails: 9 templates, one per career path (ib, pe, vc) and level (junior, mid, senior).
The file name tells the system which one to use, so keep the names as they are.

  Format:
    First line:  Subject: ...
    Then a line with only ---
    Then the email body.

Follow-ups: followup_1.txt (about 5 business days after the first email) and followup_2.txt
(about 7 business days after that). Body only. They go in the same email thread, so the subject
is automatically "Re: <first subject>".

Fill-ins about the person being emailed (copied in automatically from their record):
  {first_name}     their first name
  {firm}           their firm
  {team}           their team or group (careful: not everyone has one; if a template uses it and
                   the person has none, that person is skipped)
  {title}          their job title
  {personal_line}  one or two sentences written for each person, connecting their background to
                   the sender's. Examples:
                     "I came across your background and was excited to see that you also
                      studied Business Economics at UCLA. Your path from UCLA through investing
                      roles at Advent and CVC particularly caught my attention."
                     "I've been learning more about Houlihan Lokey's Los Angeles investment
                      banking practice and came across your path from Duke's investment club
                      and economics work into Houlihan Lokey's Financial Restructuring group."
                   It only uses facts saved on the person's record and facts from the sender's
                   profile (data/sender_profile.json). If nothing specific can be said,
                   fallback_line.txt is used instead.

Fill-ins about the sender (from the settings, so no name is written into these files):
  {sender_name}    SENDER_NAME     e.g. "Alex Rivera"
  {sender_school}  SENDER_SCHOOL   e.g. "UCLA" - used in the subject line
  {sender_tagline} SENDER_TAGLINE  the line under the name, e.g. "UCLA Economics | Class of 2027"
  {sender_intro}   SENDER_INTRO    the one-sentence introduction that opens every first email,
                                   e.g. "I'm a UCLA Economics senior graduating in June 2027,
                                   and I recently interned at Example Consulting."

If a template uses one of these and the setting is empty, nothing is sent and you get a clear
error. That is on purpose: better a loud stop than an email signed by nobody.

fallback_line.txt: the sentence used when there's nothing specific to say about someone.
It can use {firm}, {first_name}, {title}.

Resume: first emails go out with the sender's resume attached (data/resume/, set by RESUME_PATH
in .env), because the templates say "I've attached my resume". Follow-ups don't attach it again.
