# firms.csv: sources and notes

Built 2026-10-05. The file has **174 rows**: one row per firm, with a firm on two lists merged into one row.

| Career path | Firms with this path | Target | Gap |
|---|---|---|---|
| IB | 25 | 25 | none |
| PE | 55 | 300 | **245 missing** (see "PE gap" below) |
| VC | 100 | 100 | none |

- **Merged rows:** Goldman Sachs is IB|PE. Andreessen Horowitz, Insight Partners, Sequoia Capital, Tiger Global Management and ICONIQ Capital are PE|VC.
- **per_office = true** for 40 rows: all 25 banks plus 15 PE firms (listed under PE below).
- **Row order:** banks (by league-table rank), then PE (in the order described below), then VC (by AUM). A merged row sits in its first section.
- **Blank domain:** 13 VC firms, where the domain could not be confirmed: Greenoaks, DFJ Growth, Gigafund, NFDG, B Capital, Eclipse, Frazier Life Sciences, TCG Crossover, Valar Ventures, Glade Brook Capital, MPM BioImpact, Apple Tree Partners and Tribe Capital.

---

## IB: top 25 banks, U.S. M&A league table, full year 2025

- **Source:** LSEG Deals Intelligence, *Global Mergers & Acquisitions Review, Full Year 2025: Financial Advisors*. The table used is "Any U.S. Involvement Announced M&A (AD41)", ranked by deal value for 1 Jan to 31 Dec 2025.
  - Report: https://thesource.lseg.com/thesource/getfile/index/0b984eae-41d3-4993-a360-4ff6c5a03ddf
  - Linked from: https://www.lseg.com/en/data-analytics/products/deals-intelligence/mergers-acquisitions
  - The LSEG *US Investment Banking Review FY2025* repeats the same top 10: https://thesource.lseg.com/thesource/getfile/index/3447f2c0-157f-4144-bc90-040ffea022a3
- **Cross-check:** Mergermarket FY2025 "US rankings by value" (top 20), via BDO's copy: https://www.bdo.fi/getmedia/3eea8893-923a-4ad8-82d9-c2cbe37aa584/Global_and_Regional_MA_Rankings_2025__Financial_Advisors-1.pdf. Its top 17 are the same firms as LSEG's.
- **Changes from the LSEG table:**
  - **Removed RedBird BD LLC (tied #18).** It is the advisory arm of the PE firm RedBird Capital Partners and ranks on a single deal, so the banks below it each move up one place.
  - **Added Qatalyst Partners as #25.** It is the highest firm not already listed in the same report's "Any U.S. Involvement Completed M&A (AF48)" table: same provider, region, year and value measure.
- **Why deal value and not fees:** no public U.S.-only M&A fee ranking deep enough for 25 banks was found for 2025. LSEG's public fee table is global and covers only the top 20.
- **Banks to double-check:**
  - **Allen & Company (#13) and M. Klein and Company (#18)** rank on a few very large deals and are very small firms. M. Klein's place comes from one deal.
  - **Houlihan Lokey** is missing. It is the strongest alternate: #3 in the U.S. by number of deals (Mergermarket) and #10 globally by M&A fees (LSEG). Swap it in for M. Klein if the list should favor firms with real analyst classes.
- **Domains:**
  - Confidence is lower for allenco.com, mkleinandcompany.com, mizuhogroup.com (Mizuho Americas, which includes Greenhill) and guggenheimpartners.com.
  - BMO's email domain bmo.com is used; its website is bmocm.com.
  - Some TD Cowen staff may still use tdcowen.com.
- **"ibusleaguetables":** the plan names this as a source, but no such site exists. ibusleaguetables.com is not registered, and no .net, .org or hosted variant was found.

## PE: PEI 300, 2026 edition (published 1 June 2026)

**Coverage:** 55 firms, against 300 on the full ranking. PEI's ranking page shows only the top 10 to the public: https://www.privateequityinternational.com/pei-300/. The full 300 needs a PEI account, which is **free to register**.

**Sources:**
1. **2026 ranks #1–30:** Wikipedia, "List of private equity firms", which reproduces the 2026 PEI 300 top 30 (revision of 2 June 2026): https://en.wikipedia.org/wiki/List_of_private_equity_firms. Ranks 1–10 match PEI's own public page exactly. Ranks 11–30 could not be checked against PEI directly.
2. **2025 PEI 300 top 50:** Visual Capitalist, 12 June 2025: https://www.visualcapitalist.com/worlds-top-50-private-equity-firms-in-2025/. Its ranks 1–30 match the June 2025 Wikipedia revision.
   - 19 U.S.-present firms from this top 50 are not in the 2026 top 30. They are included with their **2025** rank, for example "PEI 300 2025 #24".
   - These firms raised $16bn or more over 2020–24, and the 2026 cutoff was about $2.8bn, so they are almost certainly on the 2026 list. Their exact 2026 rank is not public.
3. **Other firms with public 2026 evidence:**
   - Investindustrial #102 and CBC Group #122: RankiaPro, 1 June 2026: https://rankiapro.com/it/notizie/ranking-maggiori-societa-private-equity-globale/
   - Ridgemont Equity Partners #119: the firm's LinkedIn page, "climbed to No. 119 from No. 210"
   - Great Hill Partners "top 75": https://www.greathillpartners.com/media/great-hill-partners-ranks-on-pei-300-list
   - Triton Partners "top 100": https://www.triton-partners.com/news/triton-partners-featured-among-top-100-in-private-equity-internationals-pei-300-ranking
   - Thoma Bravo's #5 is confirmed by its own press release.

**PE row order:** 2026 ranks #1–30, then the 2025 top-50 firms in 2025-rank order, then Great Hill, Triton, Investindustrial, Ridgemont and CBC Group.

**PE gap: 245 firms.** No public, reputable copy of 2026 ranks 31–300 was found. Firm-by-firm searches (this session used its full allowance of about 200 web searches) turned up only the handful of firms listed above.
- **Best fix:** Will registers for free at privateequityinternational.com, opens the full 2026 table, and the remaining rows are added from it.
- **Third-party copy, not used:** an unofficial copy of PEI's June 2026 magazine section, with the full table, turned up on a third-party file host. It was **not used**. It looks like an unauthorized copy of PEI content (each page says "personal, non-commercial use only"), and Claude's permission checks blocked its use. Will can decide whether to use it.
- **Older full lists that are public:**
  - 2022 edition (10X EBITDA): https://www.10xebitda.com/wp-content/uploads/2022/11/Private-Equity-Firms-Ranking_-2022-Full-List.pdf
  - 2021 edition (on PEI's own site): https://media.privateequityinternational.com/uploads/2021/06/PEI-300-2021.pdf
  - These were not used, because they are four or more editions old.

**Non-U.S. firms excluded:**
- China Merchants Capital (2025 #44, Shenzhen, no U.S. office)
- Ambienta SGR (2026 #291, Italy, no U.S. office)

**Included non-U.S. firms that have U.S. offices:** EQT, Hg, CVC, Partners Group, Bridgepoint, Cinven, Apax, Nordic Capital, Permira, Ardian, Brookfield, Hillhouse (New York office), Triton (New York), Investindustrial (New York) and CBC Group (New York).

**per_office = true for 15 PE firms.** The rule is a 2026 rank in the top 30, real offices in at least two of LA, New York, SF Bay Area and Chicago, and not mainly a VC firm. The 15 firms:
- KKR, EQT (New York, Chicago), Blackstone, TPG, Thoma Bravo (Chicago, SF, New York)
- Bain Capital, General Atlantic (New York, SF), Advent (New York, Palo Alto)
- Hellman & Friedman (SF, New York), Warburg Pincus (New York, SF), Vista (Chicago, New York, SF)
- Carlyle, Apollo, Blue Owl (New York, Chicago, SF, Menlo Park), Silver Lake (Menlo Park, SF, New York)

Goldman Sachs is also true, as a bank.

**Judgment calls to review:**
- **Set to false although they could qualify:**
  - Insight Partners (#17: New York and Palo Alto) and Andreessen Horowitz (#16), because they are mainly VC/growth firms.
  - Partners Group (#29) and Neuberger Berman (#26), whose PE teams are concentrated in a single location.
- **Set to false because they have a single major office:** CVC (New York only), CD&R (New York only), Clearlake (LA only), Leonard Green (LA only) and Hg (New York only).
- **Name changes:**
  - "Goldman Sachs Asset Management" (#10) is merged into the Goldman Sachs row.
  - "Neuberger Berman Private Markets" is listed as Neuberger Berman.
  - "The Jordan Company" is listed as TJC (The Jordan Company), domain tjclp.com.

## VC: top 100 U.S.-active VC firms by AUM

**No single public ranking covers 100 VC firms.** The public lists checked (DealRoom, Affinity, altss.com, Wikipedia) stop at about 10–20 firms. So this list was **built and ranked from SEC Form ADV filings**, looked up through https://adviserinfo.sec.gov.

**What the figures are:**
- Filings are dated March–October 2026, with figures mostly as of 31 Dec 2025.
- **Registered advisers:** the figure is "regulatory AUM", which is gross and includes uncalled commitments.
- **Exempt venture advisers:** they report no total, so the figure is the sum of the private-fund values in the filing, with feeder funds skipped.
- **Firms filing under several entities** were added together: Accel, Menlo, IVP, Atlas, DCVC, Venrock, DST, Qiming and Valar.

**Cross-check:** DealRoom.net "Top VC Firms 2026" (updated 11 Sep 2026), also built from Form ADV: https://dealroom.net/blog/top-venture-capital-firms. All 18 of its firms match these figures.

**Firm-stated figures (2 rows):**
- GV, "over $13B": https://www.gv.com/about
- Norwest, $15.5B (April 2024): https://www.prnewswire.com/news-releases/norwest-announces-3-billion-global-fund-to-partner-with-the-next-generation-of-enduring-companies-302126935.html

**Firms that are not pure VC and should be reviewed:**
- **Crossover or hedge funds** (figures include public funds): Coatue, Tiger Global, Altimeter, Deerfield, RA Capital, OrbiMed, Pantera.
- **Growth, corporate or accelerator:** Valor, TCV, Dragoneer, Greenoaks, Y Combinator, SoftBank Vision Fund, GV.
- **Figures mostly SpaceX holdings:** DFJ Growth and Gigafund.
- **Partial or derived figures:**
  - ICONIQ Growth is $31.1B (press says about $26B). It is merged into the ICONIQ Capital row.
  - F-Prime is taken from a Fidelity-related filing.
  - Bain Capital Life Sciences comes from Bain's PE filing.
  - SoftBank covers Vision Fund 1 only.
- **Other notes:**
  - NFDG's founders joined Meta in 2025.
  - Foundry Group says it is not raising new funds.
  - Peak XV, Vy Capital, Qiming and DST Global are foreign-focused firms with small U.S. offices. DST's filing lists no U.S. office; Wikipedia gives Menlo Park and New York.
- **Bain Capital Ventures and Bain Capital Life Sciences** are kept as rows separate from Bain Capital (PE). They are separately branded firms with their own SEC filings and domains. Merge them if one row per parent company is wanted.

**Excluded for having no U.S. office:** HongShan (~$57B), IDG Capital (~$19B), Balderton, Kaszek, Atomico, Eight Roads, Georgian (Toronto) and Partech.

**Excluded as outside VC scope:**
- General Atlantic: PE/growth, already in the PE section.
- D1 Capital: hedge fund.
- Draper Fisher Jurvetson: legacy funds only.
- Industry Ventures: fund of funds.
- Growth-equity firms: Stripes, WestCap, Lead Edge, Level Equity and Five Elms.

**Coverage risk near the bottom:**
- Firms were found by looking up names one by one, not by scanning every SEC filer, so a few $3–5B firms may be missing.
- Next in line (#101 onward): Foresite, Union Square Ventures, Initialized, Primary, Fifth Wall, Scale, Polychain, Nexus, Electric and Wing.
