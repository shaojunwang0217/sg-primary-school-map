#!/usr/bin/env python3
"""
Version 2: Improved regex patterns based on actual HTML structure.

Key fixes:
- Next.js inserts <!-- --> comments between text nodes
- Proper col-span-3 class matching (no extra classes)
- Better slug handling for schools with 500 errors
- Extract ballot data for prestige.json
"""
import json
import re
import time
import urllib.request
import urllib.parse
import sys

SCHOOLS_FILE = "schools.json"
SLEEP = 0.5

def load_schools():
    with open(SCHOOLS_FILE, "r") as f:
        return json.load(f)

def save_schools(schools):
    with open(SCHOOLS_FILE, "w") as f:
        json.dump(schools, f, indent=2, ensure_ascii=False)
    print(f"  Saved {len(schools)} schools to {SCHOOLS_FILE}")

def slugify(name):
    """Convert school name to KiasuParents slug."""
    s = name.lower()
    # Handle special apostrophe cases
    s = s.replace("'", "")
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'\s+', '-', s.strip())
    return s

def fetch_page(url):
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            return html
    except urllib.error.HTTPError as e:
        print(f"    HTTP Error {e.code}: {url}")
        return None
    except Exception as e:
        print(f"    ERROR: {e}")
        return None

def extract_field_fixed(html, field_name):
    """Extract field value from the Next.js-rendered HTML structure.
    The pattern is: <div class="col-span-1 col-span-2 font-bold">FieldName<!-- -->:</div>
    <div class="col-span-3 "><p>VALUE</p> or <a href=...>VALUE</a>
    """
    # Remove <!-- --> comments for easier matching
    cleaned = html.replace("<!-- -->", "")
    
    if field_name == "region":
        m = re.search(r'font-bold">Region\s*:</div><div class="col-span-3\s*"><p>([^<]+)</p>', cleaned)
    elif field_name == "address":
        m = re.search(r'font-bold">Address\s*:</div><div class="col-span-3\s*"><p>([^<]+)</p>', cleaned)
    elif field_name == "phone":
        m = re.search(r'font-bold">Telephone\s*:</div><div class="col-span-3\s*"><a\s+href="tel:([^"]+)"', cleaned)
    elif field_name == "website":
        m = re.search(r'font-bold">Website\s*:</div><div class="col-span-3\s*"><a\s+href="([^"]+)"', cleaned)
    elif field_name == "email":
        m = re.search(r'font-bold">Email\s*:</div><div class="col-span-3\s*"><a[^>]*>([^<]+)</a>', cleaned)
    else:
        return ""
    
    return m.group(1).strip() if m else ""

def extract_description(html):
    m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', html, re.IGNORECASE)
    return m.group(1).strip() if m else ""

def parse_session_from_description(desc):
    if not desc: return ""
    d = desc.lower()
    if "single session" in d: return "Single session"
    if "full day session" in d or "fullday session" in d: return "Full day session"
    if "morning session" in d: return "Morning session"
    if "double session" in d: return "Double session"
    return ""

def extract_type_from_description(desc):
    if not desc: return ""
    m = re.search(r'(Government School|Govt-Aided School|Government-Aided School)', desc)
    if m:
        val = m.group(1)
        if "Govt-Aided" in val or "Government-Aided" in val:
            return "Govt-Aided"
        return "Government"
    return ""

def extract_gender_from_description(desc):
    if not desc: return ""
    if "Girls Only" in desc or "Girls" in desc: return "Girls"
    if "Boys Only" in desc or "Boys" in desc: return "Boys"
    if "Co-Ed" in desc: return "Co-Ed"
    return ""

def onemap_geocode(address):
    url = f"https://www.onemap.gov.sg/api/common/elastic/search?searchVal={urllib.parse.quote(address)}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("found") and data.get("results"):
            r = data["results"][0]
            lat = float(r["LATITUDE"])
            lng = float(r["LONGITUDE"])
            print(f"    OneMap: ({lat}, {lng})")
            return lat, lng
    except Exception as e:
        print(f"    OneMap ERROR: {e}")
    return None, None

def extract_ballot_data(html):
    """Extract ballot/vacancy data from the page HTML for prestige.json generation."""
    # Remove <!-- --> comments
    cleaned = html.replace("<!-- -->", "")
    
    data = {}
    
    # Extract total vacancies
    m = re.search(r'Total Vacancies\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*(\d+)', cleaned)
    if m:
        data["total_vacancies"] = int(m.group(1))
    
    # Extract year headings (2025, 2024)
    for year in ["2025", "2024"]:
        year_data = {}
        
        # Find the section for this year
        year_pattern = re.compile(
            r'<div[^>]*>\s*' + year + r'\s*</div>.*?'
            r'(?=<div[^>]*>(202[0-9]|</div>))',
            re.DOTALL
        )
        
        # Simpler approach - find ballot table rows per year
        # Look for this year's section
        year_section = cleaned[cleaned.find(f'">{year}<'):]
        if year_section == -1:
            continue
            
        # Extract phases
        for phase in ["Phase 1", "Phase 2A", "Phase 2B", "Phase 2C", "Phase 2C Supp."]:
            phase_data = {}
            
            # Find vacancies
            m_vac = re.search(
                r'<div[^>]*>Vacancies\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*(\d+)',
                cleaned
            )
            if m_vac:
                phase_data["vacancies"] = int(m_vac.group(1))
            
            # Find applicants
            m_app = re.search(
                r'<div[^>]*>Applicants\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*(\d+)',
                cleaned
            )
            if m_app:
                phase_data["applicants"] = int(m_app.group(1))
            
            # Find balloting
            m_ballot = re.search(
                r'<div[^>]*>Balloting\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*(\w+)',
                cleaned
            )
            if m_ballot:
                phase_data["balloting"] = m_ballot.group(1)
            
            # Find demand ratio
            m_ratio = re.search(
                r'<div[^>]*>Demand ratio\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*(\d+\.?\d*)%',
                cleaned
            )
            if m_ratio:
                phase_data["demand_ratio"] = float(m_ratio.group(1))
            
            if phase_data:
                year_data[phase] = phase_data
        
        # Extract balloting details
        for detail in ["Conducted for", "Vacancies for ballot", "Balloting applicants"]:
            m_detail = re.search(
                r'<div[^>]*>' + re.escape(detail) + r'\s*</div>\s*<div[^>]*>\s*<p[^>]*>\s*([^<]+)',
                cleaned
            )
            if m_detail:
                year_data[detail] = m_detail.group(1).strip()
        
        # Simpler: just find all numbers in the year section
        if year_data:
            data[year] = year_data
    
    return data

def main():
    schools = load_schools()
    print(f"Loaded {len(schools)} schools")
    
    changes = []
    errors = []
    ballot_data = {}
    
    for i, school in enumerate(schools):
        slug = slugify(school["name"])
        
        # Try different slugs for known failures
        slugs_to_try = [slug]
        
        # Try removing trailing words
        for suffix in ['-school', '-primary', '-primary-school', '-school-primary']:
            alt = slug[:-len(suffix)] if slug.endswith(suffix) else None
            if alt and alt != slug:
                slugs_to_try.append(alt)
                
        # Special cases for specific failures
        slug_overrides = {
            "anglo-chinese-junior": "acs-junior",
            "anglo-chinese-primary": "acs-primary",
            "eunos-primary": "eunos-primary-school",
            "guangyang-primary": "guangyang-primary-school",
            "juying-primary": "juying-primary-school",
            "maris-stella-high": "maris-stella-high-school",
            "st-andrews-junior": "st-andrews-junior-school",
            "st-anthonys-canossian-primary": "st-anthonys-canossian-primary-school",
            "st-anthonys-primary": "st-anthonys-primary-school",
            "st-gabriels-primary": "st-gabriels-primary-school",
            "st-hildas-primary": "st-hildas-primary-school",
            "st-josephs-institution-junior": "st-josephs-institution-junior",
            "st-margarets-primary": "st-margarets-primary-school",
            "st-stephens": "st-stephens-school",
            "stamford-primary": "stamford-primary-school",
        }
        
        if slug in slug_overrides:
            slugs_to_try.insert(0, slug_overrides[slug])
        
        html = None
        used_slug = None
        for try_slug in slugs_to_try:
            url = f"https://www.kiasuparents.com/kiasu/primary-schools/{try_slug}"
            print(f"\n[{i+1}/{len(schools)}] {school['name']}")
            print(f"  Trying slug: {try_slug}")
            
            html = fetch_page(url)
            if html and "404" not in html[:500] and "Page not found" not in html[:1000]:
                used_slug = try_slug
                print(f"  OK!")
                break
            elif html:
                print(f"  404")
                html = None
            time.sleep(0.3)
        
        if not html:
            errors.append((school["name"], "No valid slug found"))
            print(f"  SKIPPING")
            time.sleep(SLEEP)
            continue
        
        # Extract all fields
        address = extract_field_fixed(html, "address")
        region = extract_field_fixed(html, "region")
        phone = extract_field_fixed(html, "phone")
        website = extract_field_fixed(html, "website")
        desc = extract_description(html)
        session = parse_session_from_description(desc)
        type_from_desc = extract_type_from_description(desc)
        gender_from_desc = extract_gender_from_description(desc)
        email = extract_field_fixed(html, "email")
        
        # Also extract ballot data
        ballot = extract_ballot_data(html)
        if ballot:
            ballot_data[school["name"]] = ballot
        
        print(f"  Region: {region}")
        print(f"  Address: {address}")
        print(f"  Phone: {phone}")
        print(f"  Website: {website}")
        print(f"  Session: {session}")
        print(f"  Type: {type_from_desc}")
        print(f"  Gender: {gender_from_desc}")
        print(f"  Email: {email}")
        
        school_changes = []
        
        # Address
        if address and school.get("address", "") != address:
            old = school.get("address", "")
            print(f"  ADDRESS: '{old}' -> '{address}'")
            school["address"] = address
            school_changes.append(f"address: '{old}' -> '{address}'")
            # Re-geocode
            lat, lng = onemap_geocode(address)
            if lat is not None:
                school["lat"] = lat
                school["lng"] = lng
                school_changes.append(f"lat/lng: ({lat}, {lng})")
        
        # Region
        if region and school.get("region", "") != region:
            old = school.get("region", "")
            print(f"  REGION: '{old}' -> '{region}'")
            school["region"] = region
            school_changes.append(f"region: '{old}' -> '{region}'")
        
        # Phone
        if phone and school.get("phone", "") != phone:
            old = school.get("phone", "")
            print(f"  PHONE: '{old}' -> '{phone}'")
            school["phone"] = phone
            school_changes.append(f"phone: '{old}' -> '{phone}'")
        
        # Website (MOE URL)
        if website and school.get("moe_url", "") != website:
            old = school.get("moe_url", "")
            print(f"  WEBSITE: '{old}' -> '{website}'")
            school["moe_url"] = website
            school_changes.append(f"moe_url: '{old}' -> '{website}'")
        
        # Session
        if session and school.get("session", "") != session:
            old = school.get("session", "")
            print(f"  SESSION: '{old}' -> '{session}'")
            school["session"] = session
            school_changes.append(f"session: '{old}' -> '{session}'")
        
        # Lat/Lng - if address exists but coords are missing
        if address:
            lat_raw = school.get("lat")
            lng_raw = school.get("lng", "")
            if lat_raw is None or str(lat_raw) == "" or lng_raw is None or str(lng_raw) == "":
                print(f"  Missing coords, geocoding...")
                lat, lng = onemap_geocode(address)
                if lat is not None:
                    school["lat"] = lat
                    school["lng"] = lng
                    school_changes.append(f"lat/lng: ({lat}, {lng}) from OneMap")
            elif lat_raw == 0 and lng_raw == 0:
                lat, lng = onemap_geocode(address)
                if lat is not None:
                    school["lat"] = lat
                    school["lng"] = lng
                    school_changes.append(f"lat/lng: ({lat}, {lng}) from OneMap")
        
        # Type from description - update if current is generic "Government" 
        # and description says "Govt-Aided" (common pattern in our data)
        if type_from_desc and school.get("type", "") != type_from_desc:
            old = school.get("type", "")
            # Only update Govt-Aided -> Government if we have strong evidence
            if old == "Government" and type_from_desc == "Govt-Aided":
                print(f"  TYPE UPDATE: '{old}' -> '{type_from_desc}'")
                school["type"] = type_from_desc
                school_changes.append(f"type: '{old}' -> '{type_from_desc}' (from description)")
            elif not old or old == "":
                school["type"] = type_from_desc
                school_changes.append(f"type: '{old}' -> '{type_from_desc}'")
        
        # Gender from description
        if gender_from_desc and school.get("gender", "") != gender_from_desc:
            old = school.get("gender", "")
            if not old or old == "":
                school["gender"] = gender_from_desc
                school_changes.append(f"gender: '{old}' -> '{gender_from_desc}'")
        
        if school_changes:
            changes.append((school["name"], school_changes))
        
        time.sleep(SLEEP)
    
    # Save final output
    save_schools(schools)
    
    # Also save ballot data
    if ballot_data:
        with open("prestige.json", "w") as f:
            json.dump(ballot_data, f, indent=2, ensure_ascii=False)
        print(f"  Saved ballot data for {len(ballot_data)} schools to prestige.json")
    
    # Print summary
    print("\n" + "="*80)
    print("SUMMARY OF CHANGES:")
    print("="*80)
    for name, school_changes in changes:
        print(f"\n{name}:")
        for c in school_changes:
            print(f"  - {c}")
    
    print(f"\n\nTotal schools with changes: {len(changes)}")
    print(f"Total errors: {len(errors)}")
    for name, reason in errors:
        print(f"  - {name}: {reason}")

if __name__ == "__main__":
    main()
