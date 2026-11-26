#!/usr/bin/env python3
"""Build a separate, auditable Overture catalog for Almaty.

Only point records with a usable name/address may be added to the lookup
index. Polygon and road names are retained as reference data, not endpoints.
"""
import argparse
import collections
import json
import math
import sqlite3
from pathlib import Path
from build_almaty_index import normalize, in_bounds

ATTRIBUTION = "https://docs.overturemaps.org/attribution/"
RELEASE = "2026-11-18.0"

def features(path):
    if not path.exists():
        return
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            line = line.strip().lstrip("\x1e").strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("type") == "Feature":
                yield obj

def names(props):
    n = props.get("names") or {}
    out = [n.get("primary")]
    common = n.get("common") or {}
    if isinstance(common, dict):
        out.extend(common.values())
    for rule in n.get("rules") or []:
        out.append(rule.get("value"))
    return sorted({v.strip() for v in out if isinstance(v, str) and 3 <= len(v.strip()) <= 200})

def point(geometry):
    if geometry.get("type") != "Point":
        return None
    coords = geometry.get("coordinates") or []
    if len(coords) < 2:
        return None
    lon, lat = coords[:2]
    if not all(isinstance(x,(int,float)) and math.isfinite(x) for x in (lat,lon)):
        return None
    if not in_bounds(lat,lon):
        return None
    return round(lat*1e6), round(lon*1e6)

def address_label(p):
    street, number = p.get("street"),p.get("number")
    if p.get("country") != "KZ" or not street or not number:
        return None
    if not isinstance(street,str) or not isinstance(number,str):
        return None
    return f"{street}, {number}"

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("osm",type=Path)
    ap.add_argument("raw",type=Path)
    ap.add_argument("catalog",type=Path)
    args=ap.parse_args()
    args.catalog.unlink(missing_ok=True)
    report={}
    with sqlite3.connect(args.catalog) as db:
        db.executescript("""
        create table points (key text, kind integer, lat integer, lon integer,
            label text, feature_id text, source_json text, primary key(key,kind,lat,lon,feature_id)) without rowid;
        create table reference_names (theme text, label text, feature_id text,
            primary key(theme,label,feature_id)) without rowid;
        create table metadata (key text primary key,value text) without rowid;
        """)
        for theme in ("place","address","building","segment"):
            seen=0
            accepted=0
            for feat in features(args.raw/(theme+".geojsonseq")):
                seen+=1
                p=feat.get("properties") or {}
                fid=str(p.get("id") or feat.get("id") or "")
                if not fid:
                    continue
                labels=names(p)
                if theme in ("building","segment"):
                    db.executemany("insert or ignore into reference_names values (?,?,?)",
                        [(theme,name,fid) for name in labels])
                    accepted+=bool(labels)
                    continue
                coords=point(feat.get("geometry") or {})
                if coords is None:
                    continue
                if theme=="place":
                    confidence=p.get("confidence")
                    if not isinstance(confidence,(int,float)) or confidence<0.8:
                        continue
                    kind=1
                else:
                    # Address licensing varies by provider. Keep as reference only
                    # until the Kazakhstan source and redistribution terms are verified.
                    label=address_label(p)
                    if label:
                        db.execute("insert or ignore into reference_names values (?,?,?)",
                            (theme,label,fid))
                        accepted+=1
                    continue
                source=json.dumps(p.get("sources") or [],ensure_ascii=False)
                rows=[(normalize(n,False),kind,*coords,n,fid,source) for n in labels
                      if 3<=len(normalize(n,False))<=200]
                db.executemany("insert or ignore into points values (?,?,?,?,?,?,?)",rows)
                accepted+=bool(rows)
            report[theme]={"features":seen,"accepted":accepted}
        db.executemany("insert into metadata values (?,?)",
          [("release",RELEASE),("attribution",ATTRIBUTION),
           ("report",json.dumps(report,ensure_ascii=False))])
        assert db.execute("pragma quick_check").fetchone()==("ok",)
    # Preserve the existing OSM lookup keys and their ambiguity checks.
    # Import only genuinely absent keys, retaining all competing coordinates.
    with sqlite3.connect(args.osm) as db:
        db.execute("attach database ? as supplement",(str(args.catalog),))
        db.execute("create temp table new_keys as select distinct key,kind from supplement.points q where not exists (select 1 from places p where p.key=q.key and p.kind=q.kind)")
        db.execute("create unique index temp.new_keys_idx on new_keys(key,kind)")
        db.execute("insert or ignore into places select q.key,q.kind,q.lat,q.lon,q.label from supplement.points q join new_keys k on q.key=k.key and q.kind=k.kind")
        added=db.execute("select changes()").fetchone()[0]
        db.execute("insert or replace into metadata values (?,?)",("overture_attribution",ATTRIBUTION))
        db.execute("insert or replace into metadata values (?,?)",("overture_report",json.dumps(report)))
        db.execute("insert or replace into metadata values (?,?)",("overture_added",str(added)))
        db.execute("insert or replace into metadata values (?,?)",("database_license","ODbL 1.0; Overture Places source licenses CDLA Permissive 2.0 / Apache 2.0"))
        assert db.execute("pragma quick_check").fetchone()==("ok",)
        db.commit()
    print("ALMATY_SUPPLEMENT",json.dumps({"themes":report,"new_lookup_rows":added}),flush=True)
    if report["place"]["features"]==0 or report["place"]["accepted"]==0:
        raise SystemExit("No usable Overture Places data; do not publish as enriched")

if __name__=="__main__":
    main()
