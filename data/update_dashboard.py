#!/usr/bin/env python3
"""Apply March 3, 2026 situational awareness updates to Gulf AOR dashboard data."""

import json
import os
from datetime import datetime, timezone

BASE = "/Users/jc/.openclaw/workspace/projects/iran-aor/artifacts/data"

def load(path):
    with open(path) as f:
        return json.load(f)

def save(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"  Saved: {path}")

# ─── 1. ACTIVITY FEED ───────────────────────────────────────────────────────

activity_path = os.path.join(BASE, "activity.json")
activity = load(activity_path)

# Get existing IDs to avoid duplication
existing_ids = {e.get('id') for e in activity}
print(f"Existing activity events: {len(activity)}")

# New events to add
new_events = [
    {
        "id": "evt-mar3-001",
        "ts_utc": "2026-03-03T18:00:00Z",
        "countries": ["uae"],
        "category": "strike",
        "title": "US Consulate Dubai struck by Iranian drone",
        "summary": "Iranian drone struck US Consulate Dubai — fire in parking lot and chancellery. All personnel accounted for. Significant diplomatic escalation as Iranian weapons reach US sovereign territory.",
        "severity": "critical",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-002",
        "ts_utc": "2026-03-03T14:00:00Z",
        "countries": ["saudi"],
        "category": "strike",
        "title": "US Embassy Riyadh struck by 2 Iranian drones",
        "summary": "Two Iranian drones struck US Embassy compound in Riyadh. Limited fire; minor material damage. Building was relatively empty at time of strike. Diplomatic Quarter targeted.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-003",
        "ts_utc": "2026-03-02T06:00:00Z",
        "countries": ["qatar"],
        "category": "infrastructure",
        "title": "QatarEnergy force majeure — ALL LNG production halted",
        "summary": "QatarEnergy declared force majeure and halted all LNG production at Ras Laffan and Mesaieed (Mar 2). Expanded to all downstream products Mar 3: urea, polymers, methanol, aluminum. 20% of global LNG supply now offline. Dutch/British wholesale gas +50-52%; Asian LNG +39%.",
        "severity": "critical",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-004",
        "ts_utc": "2026-03-02T12:00:00Z",
        "countries": ["qatar"],
        "category": "military",
        "title": "Qatar Air Force shoots down 2 Iranian SU-24 bombers",
        "summary": "Qatar Air Force intercepted and shot down 2 Iranian SU-24 bomber aircraft heading for Doha — first Gulf state to shoot down Iranian military aircraft in this conflict. Significant escalation in rules of engagement.",
        "severity": "critical",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-005",
        "ts_utc": "2026-03-02T08:00:00Z",
        "countries": ["regional"],
        "category": "escalation",
        "title": "Hezbollah opens Lebanon front — rockets at Haifa, Israel authorizes ground incursion",
        "summary": "Hezbollah launched rockets and drone swarms at Ramat David airbase near Haifa — first cross-border attack since Nov 2024 ceasefire. Israel launched massive airstrikes on Beirut suburbs (52+ killed, 154 wounded) and authorized ground incursion into southern Lebanon. Conflict now multi-front.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-006",
        "ts_utc": "2026-03-03T00:00:00Z",
        "countries": ["regional"],
        "category": "strike",
        "title": "Iranian drone strikes RAF Akrotiri, Cyprus — conflict reaches European territory",
        "summary": "Iranian drone struck RAF Akrotiri sovereign base area in Cyprus. Conflict has now expanded beyond the Middle East to European territory. Significant NATO implications.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-007",
        "ts_utc": "2026-03-02T02:00:00Z",
        "countries": ["bahrain"],
        "category": "strike",
        "title": "MT Stena Imperative struck by Iranian missile at Mina Salman Port, Bahrain",
        "summary": "US oil tanker MT Stena Imperative struck by Iranian missile at Mina Salman Port, Bahrain (~02:00 UTC Mar 2). Vessel ablaze. 1 worker killed by debris. Direct strike on vessel within port perimeter.",
        "severity": "critical",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-008",
        "ts_utc": "2026-03-02T10:00:00Z",
        "countries": ["bahrain"],
        "category": "military",
        "title": "US 5th Fleet HQ Juffair evacuated — NAVCENT declares area unsafe",
        "summary": "US 5th Fleet headquarters at Juffair evacuated after NAVCENT assessed area 'no longer safe for US personnel.' Radar dome took direct Shahed hit. Entire district evacuated — major loss of US naval command presence in Gulf.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-009",
        "ts_utc": "2026-03-03T10:00:00Z",
        "countries": ["oman"],
        "category": "strike",
        "title": "Duqm Port struck second time — fuel storage tank hit, port suspended",
        "summary": "Duqm Port struck for second time (Mar 3). Fuel storage tank hit; no casualties. Port operations suspended. Duqm served as backup logistics hub outside Hormuz — now also offline.",
        "severity": "medium",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-010",
        "ts_utc": "2026-03-03T08:00:00Z",
        "countries": ["oman"],
        "category": "strike",
        "title": "MKD VYOM container vessel struck by drone boat 52nm from Muscat — 1 Indian killed",
        "summary": "MKD VYOM container vessel struck by kamikaze drone boat approximately 52 nautical miles from Muscat. 1 Indian crew member killed — first Indian national casualty of the conflict. Illustrates threat extends well beyond Hormuz.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-011",
        "ts_utc": "2026-03-02T14:00:00Z",
        "countries": ["saudi"],
        "category": "infrastructure",
        "title": "Ras Tanura oil refinery (550k bbl/day) targeted — operations halted",
        "summary": "Ras Tanura oil refinery (550,000 bbl/day capacity) targeted by 5 drones Mar 2. Two debris impacts within perimeter; fire started. Operations halted as precaution. Brent crude $81-84/bbl (+15-20%). Analysts warn $100/bbl if disruptions persist; $120+ if sustained 3+ weeks.",
        "severity": "high",
        "source": "AOR Sitrep Mar 3 2026"
    },
    {
        "id": "evt-mar3-012",
        "ts_utc": "2026-03-02T18:00:00Z",
        "countries": ["regional"],
        "category": "maritime",
        "title": "Strait of Hormuz effectively closed — 150+ tankers at anchor, all major lines suspended",
        "summary": "IRGC declared Strait of Hormuz 'closed' Mar 2. 150+ tankers now at anchor in Gulf. All major shipping lines suspended transits: Maersk, MSC, Hapag-Lloyd, CMA CGM, COSCO. Marine war risk insurance withdrawn effective Mar 5. GPS jamming affected 1,100+ ships in 24hrs.",
        "severity": "critical",
        "source": "AOR Sitrep Mar 3 2026"
    },
]

# Filter out any that already exist
added = 0
for evt in new_events:
    if evt['id'] not in existing_ids:
        activity.append(evt)
        existing_ids.add(evt['id'])
        added += 1
        print(f"  + Added: {evt['id']} — {evt['title'][:60]}")
    else:
        print(f"  SKIP (exists): {evt['id']}")

save(activity_path, activity)
print(f"\nActivity feed: {added} events added ({len(activity)} total)")

# ─── 2. BORDER CROSSINGS ───────────────────────────────────────────────────

borders_path = os.path.join(BASE, "borders.json")
borders = load(borders_path)

now = "2026-03-03T22:00:00Z"

for country_group in borders:
    country = country_group.get('country', '')
    for crossing in country_group.get('crossings', []):
        name = crossing.get('crossing', '')
        
        if 'King Fahd Causeway' in name:
            crossing['status'] = 'RESTRICTED'
            crossing['notes'] = (
                "Unconfirmed reports of drone strike and security cordon as of Mar 3. "
                "Was confirmed OPEN Mar 1. Peninsula Shield Force military movement reported "
                "across causeway. Assess extremely high risk for civilian use. "
                "Do not use for civilian evacuation."
            )
            crossing['last_updated'] = now
            print(f"  Updated: King Fahd Causeway → RESTRICTED")
        
        elif 'Ghuwaifat' in name or 'Silaa' in name:
            crossing['notes'] = (
                "Active. Abu Dhabi to border ~300km/3hrs. Saudi Eastern Province is active "
                "target zone — assess HIGH RISK at destination."
            )
            crossing['last_updated'] = now
            print(f"  Updated: Al Ghuwaifat/Silaa notes")
        
        elif 'Wajajah' in name or 'Hatta' in name:
            crossing['notes'] = (
                "Safest corridor in region. Multiple country evacuation buses using this route. "
                "Security-related delays. Dubai to Muscat ~4-5 hours. "
                "Avoid Dibba/Tibat crossings (Musandam — Strait of Hormuz area extremely dangerous)."
            )
            crossing['last_updated'] = now
            print(f"  Updated: Hatta/Al Wajajah notes")

save(borders_path, borders)

# ─── 3. AREA KEY_POINTS ────────────────────────────────────────────────────

# UAE
uae_path = os.path.join(BASE, "areas", "uae.json")
uae = load(uae_path)
uae['key_points'] = [
    "186 ballistic missiles fired at UAE (172 intercepted, 1 landed on territory, 13 fell into sea); 812 drones (755 intercepted, 57 struck within country)",
    "3 foreign nationals killed (Pakistani, Nepali, Bangladeshi); 58-70 injured across multiple nationalities",
    "DXB Terminal 3 struck ~01:30 Mar 1; 4 staff injured. Fairmont Hotel Palm Jumeirah hit by drone (major fire). Burj Al Arab facade damaged by interception fragments.",
    "US Consulate Dubai struck Mar 3 — fire in parking lot and chancellery; all personnel accounted for",
    "Jebel Ali Port fire from debris; DP World briefly suspended then resumed. AWS data center fire caused cloud-service disruptions.",
    "Al Dhafra Air Base and Al Minhad Air Base (RAF/Australian forces) both targeted",
    "Interceptor depletion projected ~7 days at current consumption rate. UAE has THAAD, Patriot PAC-3, Pantsir-S1, Cheongung II, Skynight.",
    "~20,000 passengers stranded; 80%+ of Dubai flights cancelled. Emirates suspended until 23:59 Mar 4. EASA advised European carriers to avoid UAE airspace.",
    "Panic buying Mar 1 widespread; shelves restocked by Mar 3. Price controls imposed by Ministry of Economy.",
    "US State Dept Level 3 Reconsider Travel; non-emergency staff ordered depart Mar 2; DEPART NOW advisory Mar 3",
]
uae['last_updated'] = now
save(uae_path, uae)
print(f"  UAE key_points: {len(uae['key_points'])} items")

# Bahrain
bah_path = os.path.join(BASE, "areas", "bahrain.json")
bah = load(bah_path)
bah['key_points'] = [
    "73 missiles and 91 drones intercepted since Feb 28; multiple weapons penetrated defenses",
    "5th Fleet HQ Juffair: radar dome direct Shahed hit; NAVCENT evacuated entire district — area assessed 'no longer safe for US personnel'",
    "MT Stena Imperative (US oil tanker) struck by Iranian missile at Mina Salman Port Mar 2 ~02:00 UTC; ablaze; 1 worker killed",
    "Residential towers in Hoora (Era View Tower) and Seef commercial district took direct drone hits. Crowne Plaza Hotel struck.",
    "BAH airport drone hit causing material damage (terminal pre-evacuated)",
    "1 confirmed death, 4+ injuries from Iranian strikes. No US/UK military casualties confirmed.",
    "Civil unrest: Shia protests erupting in Sitra Island Mar 3; GCC Peninsula Shield Force units reportedly entering from Saudi Arabia — echoing 2011 precedent",
    "King Fahd Causeway: status uncertain. Was OPEN Mar 1; unconfirmed drone strike and security cordon reports Mar 2-3. Military movements across causeway.",
    "US Embassy Manama CLOSED. Non-emergency personnel ordered depart. Warning that hotels may be targets.",
    "Most dangerous Gulf location: compound threat of Iranian strikes + Shia unrest + small island nation + import dependency via closed Strait",
]
bah['last_updated'] = now
save(bah_path, bah)
print(f"  Bahrain key_points: {len(bah['key_points'])} items")

# Saudi
sa_path = os.path.join(BASE, "areas", "saudi.json")
sa = load(sa_path)
sa['key_points'] = [
    "No confirmed casualties in Saudi Arabia — extensive air defense experience from years of Houthi attacks; deep Patriot/THAAD inventory",
    "Ras Tanura refinery (550,000 bbl/day) targeted Mar 2 by 5 drones; 2 debris hits within perimeter; fire started; operations halted. Juaymah LPG terminal also offline since Feb 23 (pre-conflict structural collapse).",
    "US Embassy Riyadh struck by 2 Iranian drones Mar 3; limited fire, minor material damage; Diplomatic Quarter targeted",
    "King Khalid International Airport (RUH) and Prince Sultan Air Base (Al-Kharj) targeted Mar 1; Saudi intercepted 5 drones near air base",
    "Brent crude $81-84/bbl (+15-20% from pre-conflict). Analysts warn $100/bbl if disruptions persist; $120+ if sustained 3+ weeks.",
    "Saudi retains East-West pipeline routing oil to Yanbu (Red Sea), bypassing Hormuz",
    "IndiGo ran 10 dedicated evacuation flights from JED to India Mar 3. 58,000+ Indonesian pilgrims stranded during Ramadan.",
    "Houthis have NOT launched confirmed attacks on Saudi Arabia but announced resumption of Red Sea shipping attacks and strikes on Israel",
    "Crown Prince MBS reportedly vowed military force against further Iranian incursions",
]
sa['last_updated'] = now
save(sa_path, sa)
print(f"  Saudi key_points: {len(sa['key_points'])} items")

# ─── 4. MACRO INDICATORS ────────────────────────────────────────────────────

macro_path = os.path.join(BASE, "macro_indicators.json")
macro = load(macro_path)

updates_applied = []
has_regional_widening = False

for ind in macro:
    slug = ind.get('slug', '')
    name = ind.get('name', '').lower()
    
    if slug == 'hormuz' or 'hormuz' in name or 'strait' in name:
        ind['status'] = 'MET'
        ind['notes'] = "IRGC declared Strait 'closed' Mar 2. 150+ tankers at anchor. All major shipping lines suspended transits. Marine war risk insurance withdrawn effective Mar 5. GPS jamming affected 1,100+ ships in 24hrs."
        ind['last_updated'] = now
        updates_applied.append(f"Hormuz ({slug})")
    
    elif slug == 'bm-depletion' or 'depletion' in name or 'interceptor' in name:
        ind['status'] = 'MET'
        ind['notes'] = "UAE: ~7 days at current rate. Qatar: possibly 4 days. All Gulf states have 'shot several years of production in days' per former US official. US resupply request reportedly rebuffed."
        ind['last_updated'] = now
        updates_applied.append(f"BM Depletion ({slug})")
    
    elif slug == 'proxy-escalation' or 'proxy' in name:
        ind['status'] = 'MET'
        ind['notes'] = "Hezbollah opened Lebanon front Mar 2 (rockets at Haifa, Israel ground incursion authorized). Iraqi militia coalition claimed 16 operations Feb 28. Houthi resumption of Red Sea attacks announced but not yet executed."
        ind['last_updated'] = now
        updates_applied.append(f"Proxy Escalation ({slug})")
    
    elif slug == 'regional-widening' or 'regional' in name and 'widen' in name:
        ind['status'] = 'MET'
        ind['notes'] = "RAF Akrotiri Cyprus struck. Lebanon front opened. Iraqi militia escalation. Houthi resumption announced. Gulf states considering offensive action against Iranian launch sites."
        ind['last_updated'] = now
        updates_applied.append(f"Regional Widening ({slug})")
        has_regional_widening = True

if not has_regional_widening:
    # Add Regional Widening as new indicator
    new_id = max((ind.get('id', 0) for ind in macro), default=0) + 1
    macro.append({
        "id": new_id,
        "slug": "regional-widening",
        "name": "Regional widening / multi-front escalation",
        "status": "MET",
        "description": "Conflict spreading beyond Gulf to Lebanon, Iraq proxy networks, and now European territory (RAF Akrotiri).",
        "notes": "RAF Akrotiri Cyprus struck. Lebanon front opened. Iraqi militia escalation. Houthi resumption announced. Gulf states considering offensive action against Iranian launch sites.",
        "last_updated": now
    })
    updates_applied.append("Regional Widening (NEW)")

save(macro_path, macro)
print(f"  Macro indicators updated: {', '.join(updates_applied)}")

# ─── 5. QATAR & OMAN AREA FILES ─────────────────────────────────────────────

qatar_path = os.path.join(BASE, "areas", "qatar.json")
if not os.path.exists(qatar_path):
    qatar_data = {
        "slug": "qatar",
        "name": "Qatar",
        "country": "QA",
        "key_points": [
            "98 of 101 ballistic missiles intercepted; 24 of 39 drones intercepted; 2 Iranian SU-24 aircraft shot down Mar 2",
            "No fatalities; 16 injured by shrapnel/debris",
            "QatarEnergy declared force majeure Mar 2; ALL LNG production halted at Ras Laffan and Mesaieed; expanded to all downstream products Mar 3; 20% of global LNG supply offline",
            "Dutch/British wholesale gas +50-52%; Asian LNG +39% following halt",
            "DOH closed 4 consecutive days; Qatar Airways all flights suspended; 8,000 stranded; next update expected 09:00 Mar 4",
            "Hamad International Airport targeted by Iranian missiles — all intercepted",
            "QRF water tank at Mesaieed power plant and QatarEnergy Ras Laffan facility struck by drones",
            "Qatar Patriot interceptor sustainability: Bloomberg reported 4-day depletion timeline (Qatar denied, called report 'deeply irresponsible')",
            "Qatar-Saudi border (Salwa/Abu Samra) likely open under enhanced security — critical for food imports",
            "No panic buying reported; Ministry of Commerce took strategic actions for supply availability; Qatar's 2017 blockade preparations provide resilience"
        ],
        "airports": [],
        "borders": [],
        "domestic_unrest": {"level": "LOW", "notes": "No significant unrest reported; population compliance with government guidance."},
        "energy_infra": {"status": "CRITICAL", "notes": "ALL LNG production halted — force majeure declared. 20% of global supply offline."},
        "evac_routes": [],
        "iw_matrix": [],
        "last_updated": now
    }
    save(qatar_path, qatar_data)
    print(f"  Qatar area file CREATED")
else:
    qatar = load(qatar_path)
    qatar['key_points'] = [
        "98 of 101 ballistic missiles intercepted; 24 of 39 drones intercepted; 2 Iranian SU-24 aircraft shot down Mar 2",
        "No fatalities; 16 injured by shrapnel/debris",
        "QatarEnergy declared force majeure Mar 2; ALL LNG production halted at Ras Laffan and Mesaieed; expanded to all downstream products Mar 3; 20% of global LNG supply offline",
        "Dutch/British wholesale gas +50-52%; Asian LNG +39% following halt",
        "DOH closed 4 consecutive days; Qatar Airways all flights suspended; 8,000 stranded; next update expected 09:00 Mar 4",
        "Hamad International Airport targeted by Iranian missiles — all intercepted",
        "QRF water tank at Mesaieed power plant and QatarEnergy Ras Laffan facility struck by drones",
        "Qatar Patriot interceptor sustainability: Bloomberg reported 4-day depletion timeline (Qatar denied, called report 'deeply irresponsible')",
        "Qatar-Saudi border (Salwa/Abu Samra) likely open under enhanced security — critical for food imports",
        "No panic buying reported; Ministry of Commerce took strategic actions for supply availability; Qatar's 2017 blockade preparations provide resilience"
    ]
    qatar['last_updated'] = now
    save(qatar_path, qatar)
    print(f"  Qatar area file UPDATED (already existed)")

oman_path = os.path.join(BASE, "areas", "oman.json")
if not os.path.exists(oman_path):
    oman_data = {
        "slug": "oman",
        "name": "Oman",
        "country": "OM",
        "key_points": [
            "ONLY GCC country not directly targeted by Iran — Tehran preserving neutral mediator status",
            "Duqm Port struck twice (Mar 1: 1 expat injured; Mar 3: fuel storage tank hit); port SUSPENDED. Salalah Port also suspended under security restrictions.",
            "Tanker Skylight attacked near Khasab (Musandam); MKD VYOM struck by kamikaze drone boat 52nm from Muscat — 1 Indian crew member killed",
            "MCT airspace remains OPEN — sole Gulf state in this position; primary regional evacuation hub",
            "Multiple countries routing evacuations through Oman: UK charter flights Muscat; Germany aircraft; Ireland/Italy/Armenia bus transfers UAE→Oman",
            "Strait of Hormuz effectively closed — 150+ tankers at anchor; IRGC declared strait 'closed' Mar 2",
            "Oman FM Al-Busaidi: 'off-ramps are available — let's use them'; mediation channel suspended but not dead",
            "Avoid Dibba/Tibat crossings to Musandam — Strait of Hormuz area extremely dangerous",
            "UAE-Oman land border is safest evacuation corridor in region; Dubai to Muscat ~4-5 hours; expect security delays",
            "Supply chain vulnerability: Oman import-dependent; Duqm (backup port outside Hormuz) now suspended"
        ],
        "airports": [],
        "borders": [],
        "domestic_unrest": {"level": "LOW", "notes": "No domestic unrest. Oman maintaining neutral diplomatic stance."},
        "energy_infra": {"status": "WATCH", "notes": "Not a major producer. Port infrastructure disrupted (Duqm, Salalah suspended)."},
        "evac_routes": [],
        "iw_matrix": [],
        "last_updated": now
    }
    save(oman_path, oman_data)
    print(f"  Oman area file CREATED")
else:
    oman = load(oman_path)
    oman['key_points'] = [
        "ONLY GCC country not directly targeted by Iran — Tehran preserving neutral mediator status",
        "Duqm Port struck twice (Mar 1: 1 expat injured; Mar 3: fuel storage tank hit); port SUSPENDED. Salalah Port also suspended under security restrictions.",
        "Tanker Skylight attacked near Khasab (Musandam); MKD VYOM struck by kamikaze drone boat 52nm from Muscat — 1 Indian crew member killed",
        "MCT airspace remains OPEN — sole Gulf state in this position; primary regional evacuation hub",
        "Multiple countries routing evacuations through Oman: UK charter flights Muscat; Germany aircraft; Ireland/Italy/Armenia bus transfers UAE→Oman",
        "Strait of Hormuz effectively closed — 150+ tankers at anchor; IRGC declared strait 'closed' Mar 2",
        "Oman FM Al-Busaidi: 'off-ramps are available — let's use them'; mediation channel suspended but not dead",
        "Avoid Dibba/Tibat crossings to Musandam — Strait of Hormuz area extremely dangerous",
        "UAE-Oman land border is safest evacuation corridor in region; Dubai to Muscat ~4-5 hours; expect security delays",
        "Supply chain vulnerability: Oman import-dependent; Duqm (backup port outside Hormuz) now suspended"
    ]
    oman['last_updated'] = now
    save(oman_path, oman)
    print(f"  Oman area file UPDATED (already existed)")

print("\n✅ All updates complete.")
