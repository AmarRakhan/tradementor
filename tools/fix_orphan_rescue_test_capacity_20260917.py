from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'cloud_api/test_short_requires_long_pairing_20260917.py'
t = p.read_text(encoding='utf-8')
t = t.replace('shortRequiresLongEnabled=True, universeTopN=1),\n        positions=[short]', 'shortRequiresLongEnabled=True, universeTopN=2),\n        positions=[short]', 1)
t = t.replace('shortRequiresLongEnabled=True, universeTopN=1),\n        positions=shorts', 'shortRequiresLongEnabled=True, universeTopN=2),\n        positions=shorts', 1)
p.write_text(t, encoding='utf-8')
print('orphan rescue test capacity corrected')
