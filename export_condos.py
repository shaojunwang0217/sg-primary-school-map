#!/usr/bin/env python3
"""
Export geocoded condo data for the school map.

Sources:
- ../condo-research/condo.db: primary SG Condo app data + geocoded coordinates
- ../condo-value-finder/condo-data.json: EdgeProp directory fallback/extra coords

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
    name = (name or "").lower().replace("&", "and").replace("@", " at ")
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


def district_prefix(value):
    m = re.search(r"D\d{1,2}", value or "")
    if not m:
        return None
    return "D" + m.group(0)[1:].zfill(2)


def table_columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})")}


def load_research_rows(db_path):
    if not db_path.exists():
        return [], []

    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    condo_cols = table_columns(con, "condos")
    optional = [
        "address", "postal", "lat", "lng", "geocode_status", "geocode_source",
        "geocode_confidence", "geocode_query", "geocoded_at"
    ]
    select_optional = [c for c in optional if c in condo_cols]
    optional_sql = ", " + ", ".join(f"c.{c}" for c in select_optional) if select_optional else ""

    rows = con.execute(
        f"""
        SELECT
          c.id, c.name, c.district, c.area, c.tenure, c.year_completed,
          c.total_units, c.developer, c.mrt_station, c.mrt_distance,
          ps.total_txns, ps.avg_annualized, ps.current_avg_psf, ps.rental_yield
          {optional_sql}
        FROM condos c
        LEFT JOIN project_stats ps ON ps.condo_id = c.id
        ORDER BY c.id
        """
    ).fetchall()
    con.close()
    return [dict(r) for r in rows], select_optional


def research_item(row):
    return {
        "id": f"sgcondo-{row['id']}",
        "name": row["name"],
        "lat": round(float(row["lat"]), 6),
        "lng": round(float(row["lng"]), 6),
        "district": row.get("district"),
        "area": row.get("area"),
        "tenure": row.get("tenure"),
        "year_completed": plausible_year(row.get("year_completed")),
        "total_units": row.get("total_units"),
        "developer": row.get("developer"),
        "mrt_station": row.get("mrt_station"),
        "mrt_distance": row.get("mrt_distance"),
        "total_txns": row.get("total_txns"),
        "avg_annualized": row.get("avg_annualized"),
        "current_avg_psf": row.get("current_avg_psf"),
        "rental_yield": row.get("rental_yield"),
        "indicative_price": None,
        "research_id": row.get("id"),
        "address": row.get("address"),
        "postal": row.get("postal"),
        "geocode_confidence": row.get("geocode_confidence"),
        "geocode_source": row.get("geocode_source"),
        "source": f"sgcondo+{row.get('geocode_source') or 'geocoded'}",
    }


def value_item(raw, research=None):
    name = display_name(raw)
    lat = raw.get("lat")
    lng = raw.get("lon", raw.get("lng"))
    district = (research or {}).get("district") or district_prefix(raw.get("district")) or raw.get("district")
    area = (research or {}).get("area") or raw.get("planning_area")
    if raw.get("district") and "/" in raw["district"] and not (research or {}).get("area"):
        area = raw["district"].split("/", 1)[1].strip()

    return {
        "id": raw.get("slug") or norm_name(name).replace(" ", "-"),
        "name": name,
        "lat": round(float(lat), 6),
        "lng": round(float(lng), 6),
        "district": district,
        "area": area,
        "tenure": (research or {}).get("tenure") or raw.get("tenure"),
        "year_completed": plausible_year((research or {}).get("year_completed")) or plausible_year(raw.get("completion")),
        "total_units": (research or {}).get("total_units") or parse_int(raw.get("units")),
        "developer": (research or {}).get("developer") or raw.get("developer"),
        "mrt_station": (research or {}).get("mrt_station"),
        "mrt_distance": (research or {}).get("mrt_distance"),
        "total_txns": (research or {}).get("total_txns"),
        "avg_annualized": (research or {}).get("avg_annualized"),
        "current_avg_psf": (research or {}).get("current_avg_psf"),
        "rental_yield": (research or {}).get("rental_yield") or parse_pct(raw.get("implied_rental_yield")),
        "indicative_price": raw.get("sold_price_range"),
        "research_id": (research or {}).get("id"),
        "address": (research or {}).get("address"),
        "postal": (research or {}).get("postal"),
        "geocode_confidence": (research or {}).get("geocode_confidence"),
        "geocode_source": (research or {}).get("geocode_source") or "edgeprop",
        "source": "sgcondo+edgeprop" if research else "edgeprop",
    }


def best_research_match(candidates, raw):
    if not candidates:
        return None
    raw_district = district_prefix(raw.get("district"))
    if raw_district:
        for row in candidates:
            if row.get("district") == raw_district:
                return row
    return max(candidates, key=lambda r: (r.get("total_txns") or 0, r.get("id") or 0))


def export_condos(value_data_path, research_db_path):
    research_rows, optional_cols = load_research_rows(research_db_path)
    has_research_coords = "lat" in optional_cols and "lng" in optional_cols

    research_by_name = {}
    for row in research_rows:
        research_by_name.setdefault(norm_name(row.get("name")), []).append(row)

    exported = []
    exported_keys = set()
    exported_names = set()
    matched_research_ids = set()
    research_geocoded = 0
    research_review_skipped = 0

    # Primary source: SG Condo app rows with accepted coordinates.
    if has_research_coords:
        for row in research_rows:
            if row.get("lat") is None or row.get("lng") is None:
                continue
            if row.get("geocode_status") and row.get("geocode_status") != "matched":
                research_review_skipped += 1
                continue
            item = research_item(row)
            key = (norm_name(item["name"]), item.get("district"))
            exported.append(item)
            exported_keys.add(key)
            exported_names.add(norm_name(item["name"]))
            matched_research_ids.add(row["id"])
            research_geocoded += 1

    # Fallback/supplement: geocoded EdgeProp directory entries.
    raw = json.loads(value_data_path.read_text(encoding="utf-8"))
    value_condos = raw.get("condos", raw if isinstance(raw, list) else [])
    edgeprop_enriched = 0
    edgeprop_only = 0
    skipped_no_coords = 0

    for raw_condo in value_condos:
        name = display_name(raw_condo)
        lat = raw_condo.get("lat")
        lng = raw_condo.get("lon", raw_condo.get("lng"))
        if not name or lat is None or lng is None:
            skipped_no_coords += 1
            continue

        research = best_research_match(research_by_name.get(norm_name(name), []), raw_condo)
        if research and research.get("id") in matched_research_ids:
            # Already exported from the primary SG Condo geocode above.
            continue

        item = value_item(raw_condo, research)
        key = (norm_name(item["name"]), item.get("district"))
        if key in exported_keys or (item.get("district") is None and norm_name(item["name"]) in exported_names):
            continue
        exported.append(item)
        exported_keys.add(key)
        if research:
            edgeprop_enriched += 1
        else:
            edgeprop_only += 1

    exported.sort(key=lambda c: (c.get("name") or "", c.get("district") or ""))
    return exported, {
        "research_total": len(research_rows),
        "research_geocoded": research_geocoded,
        "research_review_skipped": research_review_skipped,
        "edgeprop_input": len(value_condos),
        "edgeprop_enriched": edgeprop_enriched,
        "edgeprop_only": edgeprop_only,
        "skipped_no_coords": skipped_no_coords,
        "exported": len(exported),
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
        f"Exported {stats['exported']} condos "
        f"({stats['research_geocoded']} SG Condo geocoded, "
        f"{stats['edgeprop_enriched']} EdgeProp matched to SG Condo stats, "
        f"{stats['edgeprop_only']} EdgeProp-only; "
        f"{stats['research_review_skipped']} review-status skipped, "
        f"{stats['skipped_no_coords']} without coords) -> {args.output}"
    )


if __name__ == "__main__":
    main()
