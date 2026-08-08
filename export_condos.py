#!/usr/bin/env python3
"""
Export geocoded condo data for the school map.

Sources:
- ../condo-value-finder/condo-data.json: EdgeProp condo directory + coordinates
- ../condo-research/condo.db: SG Condo app stats (returns, PSF, transactions)

The output is a static condos.json consumed by app.py, so the school map does
not need direct access to either source app at runtime.
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_VALUE_DATA = ROOT.parent / "condo-value-finder" / "condo-data.json"
DEFAULT_RESEARCH_DB = ROOT.parent / "condo-research" / "condo.db"
DEFAULT_OUTPUT = ROOT / "condos.json"


def norm_name(name):
    name = (name or "").lower().replace("&", "and")
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def parse_int(value):
    if value is None:
        return None
    m = re.search(r"\d+", str(value).replace(",", ""))
    return int(m.group(0)) if m else None


def parse_pct(value):
    if value is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(m.group(0)) if m else None


def plausible_year(value, maximum=2035):
    year = parse_int(value)
    if year is None or year < 1950 or year > maximum:
        return None
    return year


def display_name(raw):
    name = raw.get("name")
    if isinstance(name, dict):
        return (name.get("display") or name.get("name") or "").strip()
    return str(name or "").strip()


def load_research_stats(db_path):
    if not db_path.exists():
        return {}

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT
          c.id, c.name, c.district, c.area, c.tenure, c.year_completed,
          c.total_units, c.developer, c.mrt_station, c.mrt_distance,
          ps.total_txns, ps.avg_annualized, ps.current_avg_psf, ps.rental_yield
        FROM condos c
        LEFT JOIN project_stats ps ON ps.condo_id = c.id
        """
    ).fetchall()
    con.close()

    by_name = {}
    for row in rows:
        key = norm_name(row["name"])
        # A few normalized names collide across districts. Keep the richer row;
        # district-specific matching below can still replace this when possible.
        current = by_name.get(key)
        if current is None or (row["total_txns"] or 0) > (current["total_txns"] or 0):
            by_name[key] = dict(row)
    return by_name


def district_prefix(value):
    m = re.search(r"D\d{1,2}", value or "")
    return m.group(0) if m else None


def export_condos(value_data_path, research_db_path):
    raw = json.loads(value_data_path.read_text(encoding="utf-8"))
    value_condos = raw.get("condos", raw if isinstance(raw, list) else [])
    research_by_name = load_research_stats(research_db_path)

    exported = []
    matched = 0
    skipped_no_coords = 0

    for raw_condo in value_condos:
        lat = raw_condo.get("lat")
        lng = raw_condo.get("lon", raw_condo.get("lng"))
        name = display_name(raw_condo)
        if not name or lat is None or lng is None:
            skipped_no_coords += 1
            continue

        research = research_by_name.get(norm_name(name))
        if research:
            matched += 1

        district = (research or {}).get("district") or district_prefix(raw_condo.get("district")) or raw_condo.get("district")
        area = (research or {}).get("area") or raw_condo.get("planning_area")
        if raw_condo.get("district") and "/" in raw_condo["district"] and not (research or {}).get("area"):
            area = raw_condo["district"].split("/", 1)[1].strip()

        item = {
            "id": raw_condo.get("slug") or norm_name(name).replace(" ", "-"),
            "name": name,
            "lat": round(float(lat), 6),
            "lng": round(float(lng), 6),
            "district": district,
            "area": area,
            "tenure": (research or {}).get("tenure") or raw_condo.get("tenure"),
            "year_completed": plausible_year((research or {}).get("year_completed")) or plausible_year(raw_condo.get("completion")),
            "total_units": (research or {}).get("total_units") or parse_int(raw_condo.get("units")),
            "developer": (research or {}).get("developer") or raw_condo.get("developer"),
            "mrt_station": (research or {}).get("mrt_station"),
            "mrt_distance": (research or {}).get("mrt_distance"),
            "total_txns": (research or {}).get("total_txns"),
            "avg_annualized": (research or {}).get("avg_annualized"),
            "current_avg_psf": (research or {}).get("current_avg_psf"),
            "rental_yield": (research or {}).get("rental_yield") or parse_pct(raw_condo.get("implied_rental_yield")),
            "indicative_price": raw_condo.get("sold_price_range"),
            "research_id": (research or {}).get("id"),
            "source": "sgcondo+edgeprop" if research else "edgeprop",
        }
        exported.append(item)

    exported.sort(key=lambda c: c["name"])
    return exported, {
        "input": len(value_condos),
        "exported": len(exported),
        "matched_sgcondo": matched,
        "skipped_no_coords": skipped_no_coords,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--value-data", type=Path, default=DEFAULT_VALUE_DATA)
    parser.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    condos, stats = export_condos(args.value_data, args.research_db)
    args.output.write_text(json.dumps(condos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Exported {stats['exported']} geocoded condos "
        f"({stats['matched_sgcondo']} matched to SG Condo stats; "
        f"{stats['skipped_no_coords']} skipped without coordinates) -> {args.output}"
    )


if __name__ == "__main__":
    main()
