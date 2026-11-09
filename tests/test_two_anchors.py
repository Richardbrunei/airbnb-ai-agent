# Two-anchor integration tests (2026-11-08): run standalone or via pytest.
import os, shutil, sqlite3, sys, tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path('/home/liang/.openclaw/workspace/coding/airbnb-ai-agent')
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

# 1) load_anchors
from reports import trend_report as tr
anchors = tr.load_anchors()
assert [a['name'] for a in anchors] == ['UT Dallas House', 'South Dallas House'], anchors
assert anchors[1]['profile']['lat'] == 32.5585 and anchors[1]['profile']['lng'] == -96.8466
print('1 load_anchors OK')

# 2) legacy-schema migration + backfill
tmp = Path(tempfile.mkdtemp())
db1 = tmp / 'legacy.db'
c = sqlite3.connect(db1)
c.execute('CREATE TABLE competitor_scores (id INTEGER PRIMARY KEY AUTOINCREMENT, scrape_date TEXT NOT NULL, listing_id TEXT, total_score REAL, price REAL)')
c.execute("INSERT INTO competitor_scores (scrape_date, listing_id, total_score, price) VALUES ('2026-10-01', 'L1', 0.8, 300)")
c.commit(); c.close()
from data import storage
storage.init_db(db1)
c = sqlite3.connect(db1)
cols = [r[1] for r in c.execute('PRAGMA table_info(competitor_scores)')]
assert 'anchor' in cols, cols
val = c.execute("SELECT anchor FROM competitor_scores WHERE listing_id='L1'").fetchone()[0]
assert val == 'UT Dallas House', val
c.close()
storage.init_db(db1)  # idempotent
print('2 migration + backfill OK')

# 3) store_scores per anchor: same listing, two anchors, no clobber
db2 = tmp / 'multi.db'
storage.init_db(db2)
def sl(lid, score):
    l = SimpleNamespace(listing_id=lid, title='T ' + lid, price=300.0,
                        bedrooms=4, neighborhood='X', lat=32.9, lng=-96.7)
    return SimpleNamespace(listing=l, total_score=score,
                           breakdown={'location': 0.9, 'bedrooms': 1.0,
                                      'price': 0.8, 'property_type': 1.0})
n = storage.store_scores([sl('L1', 0.8)], '2026-11-08', db2, anchor='UT Dallas House')
n += storage.store_scores([sl('L1', 0.7)], '2026-11-08', db2, anchor='South Dallas House')
assert n == 2
storage.store_scores([sl('L1', 0.85)], '2026-11-08', db2, anchor='UT Dallas House')  # upsert own row only
c = sqlite3.connect(db2)
rows = c.execute("SELECT anchor, total_score FROM competitor_scores WHERE listing_id='L1'").fetchall()
assert sorted(rows) == [('South Dallas House', 0.7), ('UT Dallas House', 0.85)], rows
c.close()
print('3 per-anchor store/upsert OK')

# 4) day_rows anchor filter (needs a listings row to join)
c = sqlite3.connect(db2)
c.row_factory = sqlite3.Row
c.execute("INSERT INTO listings (scrape_date, listing_id, title, price, bedrooms) VALUES ('2026-11-08','L1','T',300,4)")
c.commit()
assert len(tr.day_rows(c, '2026-11-08')) == 1
assert len(tr.day_rows(c, '2026-11-08', 'South Dallas House')) == 1
c.close()
print('4 day_rows filter OK')

# 5) parse_recs: labeled + legacy reports
rep = tmp / 'reports'
for d in ('2026-11-08', '2026-10-01'):
    (rep / 'text_reports' / d).mkdir(parents=True)
(rep / 'text_reports/2026-11-08/market_report_2026-11-08_0900.txt').write_text(
    'x' + chr(10) + 'Pricing Recommendation' + chr(10) +
    '  ' + chr(9656) + ' UT Dallas House' + chr(10) +
    '  Current $250 -> wrong placeholder' + chr(10) +
    '  Current $250 ' + chr(8594) + ' Suggested $350 (+40%)' + chr(10) +
    '  Confidence: 75%' + chr(10) +
    '  ' + chr(9656) + ' South Dallas House' + chr(10) +
    '  Current $250 ' + chr(8594) + ' Suggested $275 (+10%)' + chr(10) +
    '  Confidence: 60%' + chr(10))
(rep / 'text_reports/2026-10-01/market_report_2026-10-01_0900.txt').write_text(
    'Pricing Recommendation' + chr(10) +
    '  Current $250 ' + chr(8594) + ' Suggested $330 (+32%)' + chr(10) +
    '  Confidence: 70%' + chr(10))
old_dir = tr.REPORTS_DIR
tr.REPORTS_DIR = rep
recs = tr.parse_recs(['2026-11-08', '2026-10-01'])
tr.REPORTS_DIR = old_dir
assert recs['2026-11-08']['UT Dallas House'] == {'suggested': 350, 'conf': 75}, recs
assert recs['2026-11-08']['South Dallas House'] == {'suggested': 275, 'conf': 60}, recs
assert recs['2026-10-01']['UT Dallas House'] == {'suggested': 330, 'conf': 70}, recs
print('5 parse_recs labeled + legacy OK')

# 6) daily_report renders both labels into the day folder
from data import storage as _storage
_storage.store_snapshot = lambda *a, **k: 0  # render-only: never write the real DB
from reports.daily_report import DailyReportGenerator
from market_agent.price_analysis import PricingRecommendation
g = DailyReportGenerator(output_dir=str(tmp / 'out'))
analysis = {'summary': {'total_competitors': 9}, 'price_stats': {'min_price': 100, 'max_price': 500, 'median_price': 300, 'avg_price': 310}, 'recommendations': [PricingRecommendation(250, 350, '[UT Dallas House] Comp set: 9 closest', 0.75, 'UT Dallas House'), PricingRecommendation(250, 275, '[South Dallas House] Comp set: 6 closest', 0.6, 'South Dallas House')]}
txt = g.generate(analysis)
daydir = tmp / 'out' / 'text_reports'
assert any('market_report' in f.name for dd in daydir.iterdir() for f in dd.iterdir()), 'no report file in day folder'
assert 'UT Dallas House' in txt and 'South Dallas House' in txt and chr(9656) in txt, txt[-400:]
pass
print('6 daily_report two labeled recs OK')

# 7) load_data on real DB (read-only; local DB predates anchor column -> filter ignored)
days, day_stats, hist, meta, probes = tr.load_data()
assert len(days) > 30 and day_stats[-1]['count'] > 0
days2, *_ = tr.load_data(anchor='UT Dallas House')
assert days2 == days
print('7 load_data real-DB smoke OK,', len(days), 'days')

# 8) build_digest structure (real DB, read-only, no API call)
from market_agent import ai_analyst as A
digest, last = A.build_digest()
assert digest.count('=== Anchor') == 2 and 'South Dallas House' in digest, digest[:200]
assert last == days[-1], (last, days[-1])
print('8 build_digest two-anchor sections OK')

# 9) tools: bogus anchor rejected, valid one works
r1 = A.tool_comp_set('1999-01-01', 'Bogus')
assert r1.startswith('error: unknown anchor'), r1
r2 = A.tool_comp_set(None, 'south dallas house')
assert r2.startswith('comp set ') and '[South Dallas House]' in r2, r2[:80]
r3 = A.run_tool('day_diff', '{}')
assert not r3.startswith('error:'), r3[:80]
print('9 tools anchor validation OK')

# 10) _score_competitors returns one entry per configured anchor
import main as M
res = M._score_competitors([])
assert [n for n, _p, _s in res] == ['UT Dallas House', 'South Dallas House'], res
print('10 _score_competitors two anchors OK')

shutil.rmtree(tmp, ignore_errors=True)
print('ALL TWO-ANCHOR TESTS PASS')
