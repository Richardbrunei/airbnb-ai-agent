# Setting up on a new device (agent prompt)

Hand everything below the line to an AI agent on the target machine
(OpenClaw or any coding agent with shell access). It clones your fork,
configures the GitHub side, installs, and verifies a first end-to-end
run. Written for someone starting from their own GitHub account and API
key — not the original author's machine.

---

You are setting up **airbnb-ai-agent** on this machine: an Airbnb
competitor-market monitor. It scrapes Airbnb twice a day via GitHub
Actions, scores competitors against one or more anchor properties,
writes a SQLite DB + daily text reports + an HTML map/trend report, and
runs an AI anomaly analysis — all committed back to git automatically.

## 0. Prerequisites (check before starting)

- Linux, macOS, or Windows-under-WSL with git, python3 (3.10+), cron.
- A GitHub account.
- The code: **fork Richardbrunei/airbnb-ai-agent** (ask the owner for
  access or a copy if the repo is not visible to you), then work from
  YOUR fork — `github.com/<your-username>/airbnb-ai-agent` below.
- A z.ai API key with **coding-plan** access (the monitor calls
  `https://api.z.ai/api/coding/paas/v4`, model `glm-5.3`). The
  open-platform endpoint bills separately — do not switch base URLs.

## 1. After forking: GitHub side

1. **Fork:** on GitHub, open `Richardbrunei/airbnb-ai-agent` and click
   **Fork** (top-right — see docs/img/fork-button.png for the exact
   location). Your copy lands at
   `github.com/<your-username>/airbnb-ai-agent` with the full history —
   including the existing `data/market.db` (months of Dallas demo data
   anchored to the two imaginary properties). That is fine either way:
   keep the demo anchors and the pipeline simply continues, or set your
   own anchor (§3) and reset the DB per README.md.
2. On the fork: **Actions tab > enable workflows** — scheduled workflows
   stay disabled on forks until you do this.
3. **Settings > Secrets and variables > Actions > New repository
   secret:** name `ZAI_API_KEY`, value = your z.ai key. Secrets never
   copy from the original repo.
4. Schedule: two runs per day (about 7:17 and 11:17 AM US Central in
   winter; edit the `cron` lines in
   `.github/workflows/daily-scrape.yml` to change).

## 2. Local setup

```bash
git clone git@github.com:<your-username>/airbnb-ai-agent.git ~/airbnb-ai-agent
cd ~/airbnb-ai-agent

# optional: keep a link to the original for future improvements
git remote add upstream git@github.com:Richardbrunei/airbnb-ai-agent.git
# to adopt them later: git fetch upstream && git merge upstream/main

python3 -m venv venv                # bare venv: bootstrap pip first
./venv/bin/python3 -m ensurepip
./venv/bin/python3 -m pip install -r requirements.txt
# optional, for local testing:
./venv/bin/python3 -m pip install pytest pyairbnb

# consumer sync job — this clone NEVER writes data, it only pulls
crontab -e   # add:
*/20 * * * * cd ~/airbnb-ai-agent && git pull -q --ff-only origin main >> /tmp/airbnb-pull.log 2>&1
```

## 3. Pick your anchor property(ies)

Out of the box the config tracks TWO IMAGINARY 4BR homes in Dallas
(listed $250 each) — a demo setup. If you keep them, always disclose
they are hypothetical when quoting numbers.

To watch your own area: edit `config/areas.json` (search_areas):

- Entry 1 is the **primary anchor** (the long history the trend report
  charts); each extra entry with a `property_profile` is scored too.
- Set `location`, `property_profile` (lat/lng/bedrooms/price), filters,
  `radius_km`, `max_competitor_distance_km`.
- **Replacing an anchor requires a DB reset** — follow "Tracking Your
  Own Property" in README.md (stored scores are anchor-relative).
- Adding a new anchor later needs no reset; its rows start that day.

## 4. First run + verification

Force an immediate end-to-end run: bump the `# rev <date>` comment near
the top of `.github/workflows/daily-scrape.yml`, commit, push. Watch
the Actions run finish, then:

```bash
git pull -q --ff-only origin main
ls reports/text_reports/           # new dated folder = success
ls reports/text_reports/<today>/   # market_report_*.txt + ai_analysis_*.txt
```

The analysis header must not say SKIPPED/ERROR (SKIPPED usually means
the ZAI_API_KEY secret is missing or wrong). Open
`reports/market_trend_map.html` in a browser — one colored pin per
competitor, anchors marked with house icons. See USER_MANUAL.md to read
everything.

## 5. Operating rules (the important part)

1. **GitHub Actions is the only writer.** Never scrape or write
   `data/market.db` locally — the clone is a read-only mirror;
   `git pull --ff-only` only. Read queries use
   `sqlite3.connect("file:data/market.db?mode=ro", uri=True)`.
2. **Always `git fetch` before committing/pushing** — bot commits land
   between your commands; after pushing verify that
   `git ls-remote origin main` equals local HEAD.
3. Any scoring/filter/config/pipeline change needs a dated CHANGELOG.md
   entry plus an update to skill/SKILL.md.
4. `reports/daily_report.py`'s generator stores a DB snapshot as a side
   effect — stub `storage.store_snapshot` before running it locally.
5. Reports are pruned after 31 days (whole day-folders in
   `reports/text_reports/`); git keeps the history.

## 6. Daily check (about 2 min)

1. `git fetch && git status` — two bot commits per day should appear.
2. Today's `reports/text_reports/<date>/` has both files; analysis is
   not SKIPPED/ERROR.
3. Skim the analysis for churn/repricing flags; a missing day folder
   means check the Actions log first (Airbnb sometimes blocks runner
   IPs).

## 7. Gotchas

- Local pytest has 8 pre-existing failures (2 scorer weight-drift,
  6 async) — not regressions. The live suite is
  `tests/test_two_anchors.py`.
- `data/market.db-{wal,shm}` are gitignored; after local read-only runs
  `git status` must still show the DB clean.
- A missing `/tmp/airbnb-pull.log` just means the machine rebooted —
  not evidence of failure.

First task once the run lands: summarize today's comp sets (count,
median, suggested price per anchor) — and if the anchors are still the
defaults, say plainly that they are imaginary demo properties.
