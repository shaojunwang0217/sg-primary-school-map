#!/usr/bin/env python3
"""Merge 2026 P1 Registration Exercise results (Phase 1, 2A, 2B) into prestige.json.

Sources (fetched 2026-07-28):
- Phase 1 taken/available: p1parents.com/2026 (MOE figures, final after 8 Jul results)
- Phase 2A final: kiasuparents.com 2026-p1-registration-phase-2a-completion
- Phase 2B final: kiasuparents.com 2026-p1-registration-phase-2b-ballot

Convention (matches existing data): ballot = (app > vac).
"""
import json, os

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tmp')

p2a = {r['id']: r for r in json.load(open(os.path.join(TMP, 'p2a.json')))}
p2b = {r['id']: r for r in json.load(open(os.path.join(TMP, 'p2b.json')))}
p1 = json.load(open(os.path.join(TMP, 'p1_mapped.json')))

path = os.path.join(BASE, 'prestige.json')
data = json.load(open(path, encoding='utf-8'))
ballots = data['ballots']

added, skipped = [], []
for sid, r2a in p2a.items():
    r2b = p2b.get(sid)
    r1 = p1.get(sid)
    if not r2b:
        skipped.append(sid)
        continue
    phases = {}
    if r1:
        phases['1'] = {'vac': r1['avail'], 'app': r1['taken'], 'ballot': False}
    phases['2A'] = {'vac': r2a['places'], 'app': r2a['day2'], 'ballot': r2a['day2'] > r2a['places']}
    phases['2B'] = {'vac': r2b['places'], 'app': r2b['day2'], 'ballot': r2b['day2'] > r2b['places']}

    entry = {'year': 2026, 'phases': phases}
    hist = ballots.setdefault(sid, [])
    hist[:] = [b for b in hist if b['year'] != 2026]
    hist.append(entry)
    added.append(sid)

json.dump(data, open(path, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
print(f"Added 2026 entries for {len(added)} schools; skipped: {skipped}")

balloted_2a = [s for s in added if p2a[s]['day2'] > p2a[s]['places']]
balloted_2b = [s for s in added if p2b[s]['day2'] > p2b[s]['places']]
print(f"2A oversubscribed: {len(balloted_2a)} | 2B oversubscribed: {len(balloted_2b)}")
