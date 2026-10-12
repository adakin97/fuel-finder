"""Clean the Fuel Finder E10 extract and build the data behind the petrol tracker.

Usage: python pipeline.py <folder containing e10.csv and stations.csv>

Steps
1. Prices: drop pre-2026 dates, exact duplicates, and prices outside 0.75x-1.40x
   that day's national median (catches prices typed in pounds, 999.9 placeholders).
2. Stations: normalise brands, fix coordinates (flipped longitude signs, points
   far from their postcode district), derive postcode district and area.
3. Daily panel: each station's last price of the day, carried forward until its
   next report (for at most 30 days), so a station that did not re-report still
   counts. Medians are taken across stations, not across raw rows.
4. Write data/series.json, data/stations.json and data/findings.json.
"""
import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT = Path(__file__).parent / "data"
OUT.mkdir(exist_ok=True)

START, END = "2026-02-01", "2026-10-01"   # national coverage is near-complete from 1 Feb
CARRY_DAYS = 30
TANK_LITRES = 55                           # RAC's standard family-car tank
LOCAL_KM = 3 * 1.609                       # "within three miles"

AREA_NAMES = {
    "AB": "Aberdeen", "AL": "St Albans", "B": "Birmingham", "BA": "Bath", "BB": "Blackburn", "BD": "Bradford",
    "BH": "Bournemouth", "BL": "Bolton", "BN": "Brighton", "BR": "Bromley", "BS": "Bristol",
    "BT": "Northern Ireland", "CA": "Carlisle", "CB": "Cambridge", "CF": "Cardiff", "CH": "Chester",
    "CM": "Chelmsford", "CO": "Colchester", "CR": "Croydon", "CT": "Canterbury", "CV": "Coventry",
    "CW": "Crewe", "DA": "Dartford", "DD": "Dundee", "DE": "Derby", "DG": "Dumfries", "DH": "Durham",
    "DL": "Darlington", "DN": "Doncaster", "DT": "Dorchester", "DY": "Dudley", "E": "East London",
    "EC": "Central London", "EH": "Edinburgh", "EN": "Enfield", "EX": "Exeter", "FK": "Falkirk",
    "FY": "Blackpool", "G": "Glasgow", "GL": "Gloucester", "GU": "Guildford", "HA": "Harrow",
    "HD": "Huddersfield", "HG": "Harrogate", "HP": "Hemel Hempstead", "HR": "Hereford",
    "HS": "Outer Hebrides", "HU": "Hull", "HX": "Halifax", "IG": "Ilford", "IP": "Ipswich",
    "IV": "Inverness", "KA": "Kilmarnock", "KT": "Kingston upon Thames", "KW": "Kirkwall",
    "KY": "Kirkcaldy", "L": "Liverpool", "LA": "Lancaster", "LD": "Llandrindod Wells", "LE": "Leicester",
    "LL": "Llandudno", "LN": "Lincoln", "LS": "Leeds", "LU": "Luton", "M": "Manchester", "ME": "Medway",
    "MK": "Milton Keynes", "ML": "Motherwell", "N": "North London", "NE": "Newcastle", "NG": "Nottingham",
    "NN": "Northampton", "NP": "Newport", "NR": "Norwich", "NW": "North West London", "OL": "Oldham",
    "OX": "Oxford", "PA": "Paisley", "PE": "Peterborough", "PH": "Perth", "PL": "Plymouth",
    "PO": "Portsmouth", "PR": "Preston", "RG": "Reading", "RH": "Redhill", "RM": "Romford",
    "S": "Sheffield", "SA": "Swansea", "SE": "South East London", "SG": "Stevenage", "SK": "Stockport",
    "SL": "Slough", "SM": "Sutton", "SN": "Swindon", "SO": "Southampton", "SP": "Salisbury",
    "SR": "Sunderland", "SS": "Southend", "ST": "Stoke-on-Trent", "SW": "South West London",
    "SY": "Shrewsbury", "TA": "Taunton", "TD": "Galashiels", "TF": "Telford", "TN": "Tonbridge",
    "TQ": "Torquay", "TR": "Truro", "TS": "Teesside", "TW": "Twickenham", "UB": "Southall",
    "W": "West London", "WA": "Warrington", "WC": "Central London", "WD": "Watford", "WF": "Wakefield",
    "WN": "Wigan", "WR": "Worcester", "WS": "Walsall", "WV": "Wolverhampton", "YO": "York", "ZE": "Shetland",
}

con = duckdb.connect()
con.execute(f"create table raw as select * from read_csv_auto('{(SRC / 'e10.csv').as_posix()}')")
con.execute(f"create table st_raw as select * from read_csv_auto('{(SRC / 'stations.csv').as_posix()}', all_varchar=true)")
q = lambda sql: con.execute(sql).df()

# ---------- 1. prices ----------
con.execute("""
create table e0 as
select distinct on (site_id, datetime) site_id, price, date, datetime
from raw where date >= date '2026-01-01'
order by site_id, datetime""")
con.execute("""
create table daymed as
select date, median(price) m from e0 where price between 50 and 400 group by 1""")
con.execute("""
create table e1 as
select e0.* from e0 join daymed using (date)
where price between 0.75 * m and 1.40 * m""")

cleaning = {
    "raw_rows": int(q("select count(*) n from raw").n[0]),
    "pre_2026_rows": int(q("select count(*) n from raw where date < date '2026-01-01'").n[0]),
    "duplicate_rows": int(q("select (select count(*) from raw where date >= date '2026-01-01') - (select count(*) from e0) n").n[0]),
    "outlier_rows": int(q("select (select count(*) from e0) - (select count(*) from e1) n").n[0]),
    "clean_rows": int(q("select count(*) n from e1").n[0]),
}

# ---------- 2. stations ----------
st = q("select * from st_raw")
st["lat"] = pd.to_numeric(st["lat"], errors="coerce")
st["lon"] = pd.to_numeric(st["lon"], errors="coerce")
st["motorway"] = st["motorway"].fillna("0").astype(int)
st["supermarket"] = st["supermarket"].fillna("0").astype(int)
pc = st["postcode"].fillna("").str.upper().str.replace(r"\s+", "", regex=True)
st["postcode"] = np.where(pc.str.len() >= 5, pc.str[:-3] + " " + pc.str[-3:], pc)
st["district"] = np.where(pc.str.len() >= 5, pc.str[:-3], None)
st["area"] = pc.str.extract(r"^([A-Z]{1,2})")[0]
st["brand"] = st["brand_name"].fillna("").str.strip().str.upper().replace({"": "UNBRANDED"})
st["members_only"] = (st["brand"].str.contains("COSTCO") | st["trading_name"].fillna("").str.upper().str.contains("COSTCO")).astype(int)
st.loc[st.brand.str.startswith("COSTCO"), "brand"] = "COSTCO"
KEEP_CASE = {"ST": "St", "RD": "Rd", "LTD": "Ltd", "DR": "Dr"}


def tidy(name):
    """Title-case names stored in all capitals or all lower case; leave mixed case alone."""
    if not (name.isupper() or name.islower()):
        return name
    out = []
    for w in name.split():
        u = w.upper()
        if u in KEEP_CASE:
            out.append(KEEP_CASE[u])
        elif any(ch.isdigit() for ch in w) or not any(v in u for v in "AEIOUY"):
            out.append(u)                      # road numbers and abbreviations: A1, M6, BP, PFS, MFG
        else:
            out.append("-".join(part[:1].upper() + part[1:].lower() for part in w.split("-")))
    return " ".join(out)


st["name"] = st["trading_name"].fillna("").str.strip().map(tidy)


def km(lat1, lon1, lat2, lon2):
    p = np.pi / 180
    a = (np.sin((lat2 - lat1) * p / 2) ** 2
         + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2)
    return 12742 * np.arcsin(np.sqrt(a))


in_uk = lambda la, lo: la.between(49.8, 60.95) & lo.between(-8.7, 1.8)
ok = in_uk(st.lat, st.lon)
cent = st[ok].groupby("district")[["lat", "lon"]].median()
c = st[["district"]].join(cent, on="district", rsuffix="_c")
d_now = km(st.lat, st.lon, c.lat, c.lon)
d_flip = km(st.lat, -st.lon, c.lat, c.lon)
st["coord_fix"] = ""
flip = (~ok | (d_now > 30)) & (d_flip < 30)
st.loc[flip, "lon"] = -st.loc[flip, "lon"]
st.loc[flip, "coord_fix"] = "lon sign flipped"
bad = ~in_uk(st.lat, st.lon) | ((km(st.lat, st.lon, c.lat, c.lon) > 30) & c.lat.notna())
use_c = bad & c.lat.notna()
st.loc[use_c, ["lat", "lon"]] = c.loc[use_c, ["lat", "lon"]].values
st.loc[use_c, "coord_fix"] = "moved to postcode district centre"
still = ~in_uk(st.lat, st.lon)
st.loc[still, ["lat", "lon"]] = np.nan
st.loc[still, "coord_fix"] = "no usable location"
cleaning["coords_flipped"] = int(flip.sum())
cleaning["coords_to_district"] = int(use_c.sum())
cleaning["coords_dropped"] = int(still.sum())
con.register("st_df", st[["site_id", "name", "brand", "motorway", "supermarket", "members_only", "postcode",
                          "district", "area", "lat", "lon"]])
con.execute("create table st as select * from st_df")

# ---------- 3. daily panel ----------
con.execute("""
create table eday as
select site_id, date, arg_max(price, datetime) price from e1 group by 1, 2""")
con.execute(f"""
create table spans as
select site_id, date d0, lead(date) over (partition by site_id order by date) d1, price from eday""")
con.execute(f"""
create table panel as
select s.site_id, g.d, s.price
from spans s
join (select unnest(generate_series(date '{START}', date '{END}', interval 1 day))::date d) g
  on g.d >= s.d0 and g.d < coalesce(s.d1, date '{END}' + 1) and g.d <= s.d0 + {CARRY_DAYS}""")

series = q("""
select p.d, count(*) n,
       avg(price) mean, median(price) med,
       quantile_cont(price, 0.1) p10, quantile_cont(price, 0.9) p90,
       avg(price) filter (where st.supermarket = 1 and st.motorway = 0) sm,
       avg(price) filter (where st.supermarket = 0 and st.motorway = 0) other,
       avg(price) filter (where st.motorway = 1) mw
from panel p left join st using (site_id)
group by 1 order by 1""")

# ---------- current snapshot (prices as at 1 Oct) ----------
snap = q(f"""
select st.*, p.price, l.last_report
from panel p join st using (site_id)
join (select site_id, max(date) last_report from e1 group by 1) l using (site_id)
where p.d = date '{END}' and st.lat is not null""")

# local spread: cheapest station within three miles of each forecourt
la, lo, pr = snap.lat.values, snap.lon.values, snap.price.values
local_min = np.empty(len(snap)); local_n = np.empty(len(snap), int)
for i in range(0, len(snap), 500):
    dd = km(la[i:i + 500, None], lo[i:i + 500, None], la[None, :], lo[None, :])
    near = dd <= LOCAL_KM
    local_min[i:i + 500] = np.where(near, pr[None, :], np.inf).min(axis=1)
    local_n[i:i + 500] = near.sum(axis=1) - 1
snap["local_gap"] = snap.price - local_min
has_rival = local_n > 0
gap = snap.local_gap[has_rival]

s = series.set_index("d")
day = lambda x: s.loc[pd.Timestamp(x)]
uk_now = float(day(END)["mean"])
road = snap[snap.motorway == 0]
areas = (road.groupby("area").agg(n=("price", "size"), mean=("price", "mean"))
         .query("n >= 20").sort_values("mean"))
areas["name"] = areas.index.map(AREA_NAMES)
gb_road = road[road.area != "BT"]
brands = (gb_road.groupby("brand").agg(n=("price", "size"), mean=("price", "mean"))
          .query("n >= 80").sort_values("mean"))
brands.loc["MOTORWAY SERVICES"] = [int((snap.motorway == 1).sum()), float(snap[snap.motorway == 1].price.mean())]
brands["vs_uk"] = brands["mean"] - uk_now
spring = s.loc["2026-03-01":"2026-06-30", "mean"]
summer = s.loc["2026-05-01":"2026-08-15", "mean"]
monthly = s["mean"].resample("MS").mean()

findings = {
    "cleaning": cleaning,
    "as_at": END,
    "stations_now": int(len(snap)),
    "uk_start": float(day(START)["mean"]), "uk_now": uk_now,
    "rise_p": uk_now - float(day(START)["mean"]),
    "rise_pct": uk_now / float(day(START)["mean"]) - 1,
    "mean_1mar": float(day("2026-03-01")["mean"]), "mean_31mar": float(day("2026-03-31")["mean"]),
    "spring_peak": float(spring.max()), "spring_peak_date": str(spring.idxmax().date()),
    "summer_low": float(summer.min()), "summer_low_date": str(summer.idxmin().date()),
    "tank_start": float(day(START)["mean"]) * TANK_LITRES / 100, "tank_now": uk_now * TANK_LITRES / 100,
    "sm_now": float(day(END).sm), "other_now": float(day(END).other), "mw_now": float(day(END).mw),
    "sm_start": float(day(START).sm), "other_start": float(day(START).other),
    "p10_now": float(day(END).p10), "p90_now": float(day(END).p90),
    "share_with_rival": float(has_rival.mean()),
    "local_gap_median": float(gap.median()), "share_gap_5p": float((gap >= 5).mean()),
    "share_gap_10p": float((gap >= 10).mean()),
    "ni_now": float(road[road.area == "BT"].price.mean()), "gb_road_now": float(gb_road.price.mean()),
    "cheapest_areas": areas.head(6).round(1).reset_index().to_dict("records"),
    "dearest_areas": areas.tail(6).round(1).reset_index().to_dict("records"),
    "brands": brands.round(2).reset_index().rename(columns={"index": "brand"}).to_dict("records"),
    "monthly": {k.strftime("%Y-%m"): round(v, 1) for k, v in monthly.items()},
    "mw_median": float(snap[snap.motorway == 1].price.median()),
    "road_median": float(road.price.median()),
    "cheapest_station": snap.nsmallest(1, "price")[["name", "brand", "postcode", "price"]].to_dict("records"),
    "dearest_station": snap.nlargest(1, "price")[["name", "brand", "postcode", "price"]].to_dict("records"),
}

# ---------- outputs ----------
series_out = {
    "d": [x.strftime("%Y-%m-%d") for x in series.d],
    **{k: [round(v, 1) for v in series[k]] for k in ["mean", "p10", "p90", "sm", "other", "mw"]},
    "n": series.n.tolist(),
}
brand_list = sorted(snap.brand.unique())
bix = {b: i for i, b in enumerate(brand_list)}
stations_out = {
    "brands": brand_list,
    "cols": ["lat", "lon", "price_x10", "brand", "name", "postcode", "flags", "last_report"],
    "rows": [[round(r.lat, 4), round(r.lon, 4), int(round(r.price * 10)), bix[r.brand], r.name,
              r.postcode, int(r.supermarket) + 2 * int(r.motorway) + 4 * int(r.members_only), r.last_report.strftime("%m-%d")]
             for r in snap.itertuples()],
}
districts = {k: [round(v.lat, 3), round(v.lon, 3)] for k, v in
             st.dropna(subset=["lat"]).groupby("district")[["lat", "lon"]].median().iterrows()}
(OUT / "districts.json").write_text(json.dumps(districts, separators=(",", ":")))
(OUT / "series.json").write_text(json.dumps(series_out, separators=(",", ":")))
(OUT / "stations.json").write_text(json.dumps(stations_out, separators=(",", ":"), ensure_ascii=False))
(OUT / "findings.json").write_text(json.dumps(findings, indent=1, default=str))

# ---------- 5. render the page: one self-contained HTML file ----------
RAC_1MAR = 132.83   # RAC Fuel Watch, unleaded, 1 March 2026 (media.rac.co.uk, 2 Apr 2026)
f = findings
gb_areas = [a for a in f["cheapest_areas"] if a["area"] != "BT"]
mw_gap = f["mw_median"] - f["road_median"]
brand_spread = f["brands"][[b["brand"] for b in f["brands"]].index("SHELL")]["mean"] - f["brands"][0]["mean"]
cl = f["cleaning"]
f["as_at_long"] = pd.Timestamp(END).strftime("%-d %B %Y") if sys.platform != "win32" else pd.Timestamp(END).strftime("%#d %B %Y")
text = {
    "rise_p": f"{f['rise_p']:.0f}",
    "tank_now": f"£{f['tank_now']:.2f}", "tank_start": f"£{f['tank_start']:.2f}",
    "tank_rise": f"£{f['tank_now'] - f['tank_start']:.2f}",
    "stations_now": f"{f['stations_now']:,}", "as_at_long": f["as_at_long"],
    "uk_now": f"{f['uk_now']:.1f}", "uk_start": f"{f['uk_start']:.1f}",
    "mw_gap": f"{mw_gap:.0f}", "mw_median": f"{f['mw_median']:.1f}", "mw_tank": f"£{mw_gap * TANK_LITRES / 100:.0f}",
    "march_rise": f"{f['mean_31mar'] - f['mean_1mar']:.1f}",
    "mean_1mar": f"{f['mean_1mar']:.1f}", "mean_31mar": f"{f['mean_31mar']:.1f}",
    "rac_diff": f"{abs(f['mean_1mar'] - RAC_1MAR):.1f}", "rac_1mar": f"{RAC_1MAR:.2f}",
    "spring_peak": f"{f['spring_peak']:.1f}", "summer_low": f"{f['summer_low']:.1f}",
    "second_rise": f"{f['uk_now'] - f['summer_low']:.1f}",
    "brand_spread": f"{brand_spread:.1f}", "brand_tank": f"£{brand_spread * TANK_LITRES / 100:.2f}",
    "ni_now": f"{f['ni_now']:.1f}", "ni_gap": f"{f['gb_road_now'] - f['ni_now']:.0f}",
    "cheap_area": gb_areas[0]["name"], "cheap_area_p": f"{gb_areas[0]['mean']:.1f}",
    "dear_area": f["dearest_areas"][-1]["name"], "dear_area_p": f"{f['dearest_areas'][-1]['mean']:.1f}",
    "dropped_rows": f"{cl['raw_rows'] - cl['clean_rows']:,}", "raw_rows": f"{cl['raw_rows']:,}",
    "coords_fixed": f"{cl['coords_flipped'] + cl['coords_to_district']:,}",
}
html = (Path(__file__).parent / "src" / "template.html").read_text(encoding="utf-8")
for k, v in text.items():
    html = html.replace("{{" + k + "}}", v)
assert "{{" not in html, "unfilled placeholder"
for name, path in [("SERIES", "series.json"), ("STATIONS", "stations.json"),
                   ("DISTRICTS", "districts.json"), ("FINDINGS", None)]:
    payload = json.dumps(f, default=str) if path is None else (OUT / path).read_text(encoding="utf-8")
    html = html.replace(f"/*__{name}__*/null", payload.replace("</", r"<\/"))
(Path(__file__).parent / "index.html").write_text(html, encoding="utf-8", newline="\n")
print(json.dumps(text, indent=1, ensure_ascii=False))
print(f"index.html: {len(html.encode()) / 1024:.0f} KB")
