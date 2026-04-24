#!/usr/bin/env python3
"""Forest Coffee Client Map Generator — runs on GitHub Actions twice daily."""

import os, json, math, time, requests
from datetime import datetime, timezone

HUBSPOT_KEY = os.environ.get('HUBSPOT_API_KEY', '')
HEADERS = {'Authorization': f'Bearer {HUBSPOT_KEY}', 'Content-Type': 'application/json'}
BASE = 'https://api.hubapi.com'

OWNERS = {
    '250442122': 'Pablo Corredor',
    '60495719':  'Santiago Carvajal',
    '1430814428': 'Juan David Arango',
    '85331798':  'Sebastian Carrasquilla',
}
REP_COLORS = {
    'Pablo Corredor': '#e74c3c',
    'Santiago Carvajal': '#2980b9',
    'Juan David Arango': '#f39c12',
    'Sebastian Carrasquilla': '#9b59b6',
}

def fetch_all_companies():
    """Fetch all companies with goal, revenue, rep, category."""
    props = 'name,city,state,country,hubspot_owner_id,hs_industry,clients_goal'
    url = f'{BASE}/crm/v3/objects/companies'
    results = []
    after = None
    while True:
        params = {'limit': 100, 'properties': props}
        if after:
            params['after'] = after
        r = requests.get(url, headers=HEADERS, params=params)
        r.raise_for_status()
        data = r.json()
        results.extend(data['results'])
        paging = data.get('paging', {})
        if 'next' in paging:
            after = paging['next']['after']
        else:
            break
        time.sleep(0.1)
    return results

def fetch_2026_deals():
    """Fetch all 2026 closed-won deals and compute revenue per company via associations."""
    search_url = f'{BASE}/crm/v3/objects/deals/search'
    assoc_url  = f'{BASE}/crm/v4/associations/deals/companies/batch/read'

    deal_amounts = {}  # deal_id -> amount
    after = None
    while True:
        body = {
            'filterGroups': [{'filters': [
                {'propertyName': 'closedate', 'operator': 'BETWEEN',
                 'value': '1735689600000', 'highValue': '1767225600000'},
                {'propertyName': 'dealstage', 'operator': 'EQ', 'value': '75989797'}
            ]}],
            'properties': ['amount'],
            'limit': 200,
        }
        if after:
            body['after'] = after
        r = requests.post(search_url, headers=HEADERS, json=body)
        r.raise_for_status()
        data = r.json()
        for deal in data['results']:
            did = str(deal['id'])
            amount = float(deal['properties'].get('amount') or 0)
            deal_amounts[did] = amount
        paging = data.get('paging', {})
        if 'next' in paging:
            after = paging['next']['after']
        else:
            break
        time.sleep(0.1)

    # Batch-fetch company associations for all deals (max 100 per request)
    rev = {}
    deal_ids = list(deal_amounts.keys())
    for i in range(0, len(deal_ids), 100):
        batch = deal_ids[i:i+100]
        r = requests.post(assoc_url, headers=HEADERS,
                          json={'inputs': [{'id': did} for did in batch]})
        if not r.ok:
            time.sleep(0.2)
            continue
        for result in r.json().get('results', []):
            did = str(result['from']['id'])
            amount = deal_amounts.get(did, 0)
            for to in result.get('to', []):
                cid = str(to['toObjectId'])
                rev[cid] = rev.get(cid, 0) + amount
        time.sleep(0.1)

    return rev

def goal_color(pct):
    if pct is None: return '#6c757d'
    if pct >= 100: return '#27ae60'
    if pct >= 75:  return '#82c91e'
    if pct >= 50:  return '#f1c40f'
    if pct >= 25:  return '#e67e22'
    return '#e74c3c'

def pct_bracket(pct):
    if pct is None: return 'none'
    if pct == 0:   return 'p0'
    if pct < 10:   return 'p1'
    if pct < 30:   return 'p2'
    if pct < 50:   return 'p3'
    if pct < 70:   return 'p4'
    return 'p5'

def goal_bracket(goal):
    if not goal: return 'none'
    if goal < 5000:  return 'xs'
    if goal < 15000: return 'sm'
    if goal < 30000: return 'md'
    if goal < 60000: return 'lg'
    return 'xl'

def marker_radius(goal):
    if not goal: return 7
    if goal < 10000: return 7
    if goal < 30000: return 9
    if goal < 60000: return 11
    if goal < 120000: return 14
    return 18

def generate_html(companies):
    US_VALS = {'US', 'USA', 'United States', 'Canada'}
    us_ca = [c for c in companies
             if c.get('country') in US_VALS
             and c.get('lat') and c.get('lon')]

    now = datetime.now(timezone.utc).strftime('%b %d, %Y %H:%M UTC')
    n = len(us_ca)

    rep_counts = {}
    for c in us_ca:
        r = c.get('rep', 'Other')
        rep_counts[r] = rep_counts.get(r, 0) + 1

    marker_js = []
    for c in us_ca:
        rep = c.get('rep', 'Other')
        goal = c.get('goal') or 0
        rev  = c.get('rev_2026') or 0
        pct  = round(rev / goal * 100, 1) if goal else None
        gc   = goal_color(pct)
        rc   = REP_COLORS.get(rep, '#95a5a6')
        radius = marker_radius(goal)
        pb   = pct_bracket(pct)
        gb   = goal_bracket(goal)

        name = c.get('name', '')
        city = c.get('city', '')
        state= c.get('state', '')
        cat  = c.get('category', '') or ''
        pct_str = f'{pct:.1f}%' if pct is not None else 'N/A'

        if goal:
            goal_str = f'${goal:,.0f}'
            rev_str  = f'${rev:,.0f}'
            bar_w    = min(int((pct or 0)), 100)
            bar_color= gc
            goal_html = (
                f'<div class="pm">'
                f'<div class="mrow"><span class="ml">2026 Goal</span><span class="mv">{goal_str}</span></div>'
                f'<div class="mrow"><span class="ml">2026 Revenue</span><span class="mv">{rev_str}</span></div>'
                f'<div class="mrow"><span class="ml">Achievement</span><span class="mv">{pct_str}</span></div>'
                f'<div style="margin-top:4px;height:6px;background:#eee;border-radius:3px">'
                f'<div style="width:{bar_w}%;height:100%;background:{bar_color};border-radius:3px"></div></div>'
                f'</div>'
            )
        else:
            goal_html = '<div class="pm"><div class="ng">No 2026 goal set</div></div>'

        badge_color = REP_COLORS.get(rep, '#95a5a6')
        popup = (
            f'<div class="pc">'
            f'<div class="ph">{name}</div>'
            f'<div class="ploc">{city}, {state}</div>'
            f'<div class="prep"><span class="badge" style="background:{badge_color};color:white">{rep}</span></div>'
            + goal_html +
            f'<div class="pf2"><span>{cat or "—"}</span></div>'
            f'</div>'
        )

        lat = c['lat']
        lon = c['lon']
        marker_js.append(
            f'addMarker({lat},{lon},{json.dumps(gc)},{json.dumps(rc)},{radius},'
            f'{json.dumps(rep)},{json.dumps(pb)},{json.dumps(gb)},'
            f'{json.dumps(name)},{json.dumps(popup)});'
        )

    markers_block = '\n'.join(marker_js)

    pablo_n  = rep_counts.get('Pablo Corredor', 0)
    santi_n  = rep_counts.get('Santiago Carvajal', 0)
    juan_n   = rep_counts.get('Juan David Arango', 0)
    seb_n    = rep_counts.get('Sebastian Carrasquilla', 0)

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Forest Coffee — US & Canada Clients 2026</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  body{{margin:0;padding:0;font-family:'Segoe UI',sans-serif}}#map{{height:100vh;width:100%}}
  .top-bar{{position:absolute;top:12px;left:50%;transform:translateX(-50%);z-index:1000;display:flex;flex-direction:column;gap:8px;align-items:center}}
  .row1{{background:white;border-radius:30px;padding:6px 14px;box-shadow:0 2px 12px rgba(0,0,0,0.18);display:flex;gap:8px;align-items:center;flex-wrap:wrap;justify-content:center}}
  .row2{{display:flex;gap:8px}}
  .fbtn{{border:none;border-radius:20px;padding:5px 14px;font-size:12px;font-weight:600;cursor:pointer;transition:all .18s;opacity:.4}}
  .fbtn.active{{opacity:1;color:white}}
  #btn-all{{background:#2c3e50;color:white;opacity:1}}#btn-pablo{{background:#e74c3c}}#btn-santiago{{background:#2980b9}}#btn-juan{{background:#f39c12}}#btn-sebastian{{background:#9b59b6}}
  #search-box{{border:none;border-radius:20px;padding:5px 14px;font-size:12px;width:180px;outline:none;background:#f4f4f4;color:#333}}
  #search-box::placeholder{{color:#aaa}}
  .ddrop{{border:none;border-radius:20px;padding:5px 14px;font-size:12px;font-weight:600;cursor:pointer;background:white;box-shadow:0 2px 10px rgba(0,0,0,0.15);color:#2c3e50;outline:none;appearance:none;-webkit-appearance:none;padding-right:28px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23666'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center}}
  .leaflet-popup-content-wrapper{{border-radius:10px;padding:0;overflow:hidden;min-width:260px}}.leaflet-popup-content{{margin:0;width:auto!important}}
  .pc{{font-family:'Segoe UI',sans-serif;font-size:13px}}.ph{{background:#2c3e50;color:white;padding:10px 14px;font-size:14px}}
  .ploc{{padding:6px 14px 2px;color:#666;font-size:11px}}.prep{{padding:2px 14px 6px}}
  .badge{{border-radius:12px;padding:2px 8px;font-size:11px;font-weight:600}}.pm{{padding:6px 14px;border-top:1px solid #eee}}
  .mrow{{display:flex;justify-content:space-between;padding:3px 0;font-size:12px}}.ml{{color:#888}}.mv{{font-weight:600;color:#2c3e50}}
  .ng{{color:#aaa;font-size:11px;padding:4px 0;font-style:italic}}
  .pf2{{padding:6px 14px 10px;border-top:1px solid #eee;display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#888}}
  .legend{{position:absolute;z-index:1000;background:white;border-radius:8px;padding:10px 14px;box-shadow:0 2px 8px rgba(0,0,0,0.15);font-size:11px}}
  .legend-goal{{bottom:30px;left:12px}}.legend-rep{{bottom:30px;right:12px}}
  .lrow{{display:flex;align-items:center;gap:6px;padding:2px 0}}.ldot{{width:12px;height:12px;border-radius:50%;display:inline-block}}
  .ltitle{{font-weight:700;margin-bottom:4px;font-size:12px;color:#333}}
  .title-box{{position:absolute;top:12px;left:12px;z-index:1000;background:white;border-radius:8px;padding:10px 16px;box-shadow:0 2px 8px rgba(0,0,0,0.15)}}
  .title-box h3{{margin:0;font-size:14px;color:#2c3e50}}.title-box p{{margin:2px 0 0;font-size:11px;color:#888}}
</style></head><body>
<div id="map"></div>
<div class="title-box"><h3>Forest Coffee — US & Canada</h3><p>2026 Client Map · {n} clients · Updated {now}</p></div>
<div class="top-bar">
  <div class="row1">
    <input id="search-box" type="text" placeholder="🔍 Search client..." oninput="applyFilters()">
    <button class="fbtn active" id="btn-all" onclick="setRep('all')">All ({n})</button>
    <button class="fbtn active" id="btn-pablo" onclick="setRep('Pablo Corredor')">Pablo ({pablo_n})</button>
    <button class="fbtn active" id="btn-santiago" onclick="setRep('Santiago Carvajal')">Santiago ({santi_n})</button>
    <button class="fbtn active" id="btn-juan" onclick="setRep('Juan David Arango')">Juan David ({juan_n})</button>
    <button class="fbtn active" id="btn-sebastian" onclick="setRep('Sebastian Carrasquilla')">Sebastian ({seb_n})</button>
  </div>
  <div class="row2">
    <select id="pct-filter" class="ddrop" onchange="applyFilters()">
      <option value="all">🎯 Achievement — All</option>
      <option value="none">No goal set</option>
      <option value="p0">0% achieved</option>
      <option value="p1">1% – 10%</option>
      <option value="p2">10% – 30%</option>
      <option value="p3">30% – 50%</option>
      <option value="p4">50% – 70%</option>
      <option value="p5">70% – 100%+</option>
    </select>
    <select id="goal-filter" class="ddrop" onchange="applyFilters()">
      <option value="all">💰 Goal Size — All</option>
      <option value="none">No goal</option>
      <option value="xs">Under $5,000</option>
      <option value="sm">$5,000 – $15,000</option>
      <option value="md">$15,000 – $30,000</option>
      <option value="lg">$30,000 – $60,000</option>
      <option value="xl">$60,000+</option>
    </select>
  </div>
</div>
<div class="legend legend-goal">
  <div class="ltitle">2026 Goal Progress</div>
  <div class="lrow"><span class="ldot" style="background:#27ae60"></span> ≥ 100%</div>
  <div class="lrow"><span class="ldot" style="background:#82c91e"></span> 75–99%</div>
  <div class="lrow"><span class="ldot" style="background:#f1c40f"></span> 50–74%</div>
  <div class="lrow"><span class="ldot" style="background:#e67e22"></span> 25–49%</div>
  <div class="lrow"><span class="ldot" style="background:#e74c3c"></span> < 25%</div>
  <div class="lrow"><span class="ldot" style="background:#6c757d"></span> No goal</div>
</div>
<div class="legend legend-rep">
  <div class="ltitle">Sales Rep</div>
  <div class="lrow"><span class="ldot" style="background:#e74c3c"></span> Pablo Corredor</div>
  <div class="lrow"><span class="ldot" style="background:#2980b9"></span> Santiago Carvajal</div>
  <div class="lrow"><span class="ldot" style="background:#f39c12"></span> Juan David Arango</div>
  <div class="lrow"><span class="ldot" style="background:#9b59b6"></span> Sebastian Carrasquilla</div>
</div>
<script>
const map = L.map('map', {{zoomControl:true}}).setView([39,-98],4);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png',{{
  attribution:'&copy; OpenStreetMap &copy; CARTO',maxZoom:19}}).addTo(map);

let markers=[], currentRep='all';

function addMarker(lat,lon,gc,rc,radius,rep,pb,gb,name,popup){{
  const m=L.circleMarker([lat,lon],{{
    radius:radius,fillColor:gc,color:rc,weight:2.5,
    fillOpacity:0.85,opacity:1
  }}).addTo(map);
  m.bindPopup(popup,{{maxWidth:320}});
  m.options.rep=rep; m.options.pb=pb; m.options.gb=gb; m.options.name=name;
  markers.push(m);
}}

{markers_block}

function applyFilters(){{
  const repF=currentRep;
  const pctF=document.getElementById('pct-filter').value;
  const goalF=document.getElementById('goal-filter').value;
  const q=(document.getElementById('search-box').value||'').toLowerCase().trim();
  markers.forEach(m=>{{
    const ok=(repF==='all'||m.options.rep===repF)
      &&(pctF==='all'||m.options.pb===pctF)
      &&(goalF==='all'||m.options.gb===goalF)
      &&(!q||m.options.name.toLowerCase().includes(q));
    m.setStyle({{fillOpacity:ok?0.85:0,opacity:ok?1:0}});
    ok?m.options._visible=true:m.options._visible=false;
    if(!ok&&m.isPopupOpen())m.closePopup();
  }});
}}

function setRep(rep){{
  currentRep=rep;
  document.querySelectorAll('.fbtn').forEach(b=>b.classList.remove('active'));
  const ids={{all:'btn-all','Pablo Corredor':'btn-pablo','Santiago Carvajal':'btn-santiago','Juan David Arango':'btn-juan','Sebastian Carrasquilla':'btn-sebastian'}};
  if(ids[rep])document.getElementById(ids[rep]).classList.add('active');
  applyFilters();
}}
</script></body></html>"""
    return html


def main():
    print('Fetching companies from HubSpot...')
    raw_companies = fetch_all_companies()
    print(f'  {len(raw_companies)} companies fetched')

    # Build lookup by company ID
    company_map = {}
    for c in raw_companies:
        props = c.get('properties', {})
        cid = str(c['id'])
        owner_id = props.get('hubspot_owner_id') or ''
        rep = OWNERS.get(owner_id, 'Other')
        goal_raw = props.get('clients_goal')
        try:
            goal = float(goal_raw) if goal_raw else None
        except Exception:
            goal = None
        company_map[cid] = {
            'id': cid,
            'name': props.get('name', ''),
            'city': props.get('city', ''),
            'state': props.get('state', ''),
            'country': props.get('country', ''),
            'category': props.get('hs_industry', '') or '',
            'rep': rep,
            'goal': goal,
            'rev_2026': 0,
        }

    print('Fetching 2026 deals...')
    rev_map = fetch_2026_deals()
    print(f'  Revenue computed for {len(rev_map)} companies')
    for cid, rev in rev_map.items():
        if cid in company_map:
            company_map[cid]['rev_2026'] = rev

    print('Loading geocoded coordinates...')
    with open('companies_geocoded.json') as f:
        geocoded = json.load(f)

    geo_lookup = {g['id']: g for g in geocoded}

    # Merge coordinates
    companies = []
    for cid, c in company_map.items():
        geo = geo_lookup.get(cid)
        if geo and geo.get('lat') and geo.get('lon'):
            c['lat'] = geo['lat']
            c['lon'] = geo['lon']
            US_VALS = {'US', 'USA', 'United States', 'Canada'}
            countries_ok = c.get('country') in US_VALS or geo.get('country') in US_VALS
            if countries_ok or (geo.get('lat') and 20 < geo['lat'] < 72 and -170 < geo.get('lon', 0) < -50):
                companies.append(c)

    print(f'  {len(companies)} companies with coordinates')

    print('Generating map HTML...')
    html = generate_html(companies)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print('Done — index.html written.')


if __name__ == '__main__':
    main()
