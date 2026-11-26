#!/usr/bin/env python3
"""Precompute bounded indexed multilingual candidate keys, preserving house and type."""
import sqlite3
import sys
import re
import unicodedata

LATIN = dict(zip("абвгдежзийклмнопрстуфхцчшщыэюяьъәғқңөұүһі",
    "a b v g d e zh z i y k l m n o p r s t u f kh ts ch sh shch y e yu ya _ _ a g k ng o u u h i".split()))
TYPES = {
    "street":"улица ул көшесі street st",
    "avenue":"проспект просп пр даңғылы avenue ave",
    "lane":"переулок пер lane",
    "boulevard":"бульвар бул boulevard",
    "drive":"проезд drive",
    "highway":"шоссе highway",
    "district":"микрорайон мкр мкрн ықшамаудан microdistrict",
    "square":"площадь пл square",
}
DROP = set("город г алматы almaty казахстан kazakhstan".split()) | {w for s in TYPES.values() for w in s.split()}
# Full name variants, not arbitrary shared prefixes.
ALIASES = {
 "baitursyn": "байтурсын байтурсынова байтурсынов байтурсынулы байтұрсынұлы baitursyn baitursynov baitursynova baitursynuly baytursynov baytursynuly",
 "abay": "абай абая abay abai",
 "satpayev": "сатпаев сатпаева сәтбаев satpayev satpaev satbayev satbaev",
 "dostyk": "достык достық dostyk dostyq",
}
ALIASES = {word: key for key, values in ALIASES.items() for word in values.split()}
HOUSE = re.compile(r"^\d{1,4}[а-яa-z]?(?:[/\-]\d{1,4}[а-яa-z]?)?(?:к\d{1,3})?$")
HMAP = str.maketrans("abcehkmoptxy","авсенкморtху".replace("t","т"))
def tokens(s):
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFKC",s).lower().replace("ё","е"))
def canon(s):
    if s in ALIASES: return ALIASES[s]
    return "".join(LATIN.get(c,c) for c in s).replace("_","")
def street_type(s):
    t=set(tokens(s))
    hits=[k for k,v in TYPES.items() if t.intersection(v.split())]
    return hits[0] if len(hits)==1 else ""
def key(s, address):
    t=tokens(s)
    if address: t=[w for w in t if w not in DROP]
    else:
        # Only generic prefixes; meaningful terminal/branch qualifiers stay.
        if t and t[0] in "кафе кофейня ресторан магазин трц тц бц жк здание отель гостиница".split(): t=t[1:]
    k=[canon(w) for w in t]
    if address and "baitursyn" in k:
        k=[w for w in k if w not in ("akhmet","akhmeta","ahmet","ahmeta")]
    return " ".join(sorted(set(w for w in k if w)))
def house(s):
    h=re.sub(r"\s*(?:блок|корпус|корп|стр|строение)\s*","к",s.lower())
    h=re.sub(r"\s+","",h).translate(HMAP).replace("-","/")
    return h if HOUSE.fullmatch(h) else None
def main(path):
    with sqlite3.connect(path) as db:
        db.execute("drop table if exists smart_candidates")
        db.execute("""create table smart_candidates (
          kind integer, sig text, house text, roadtype text, lat integer, lon integer, label text,
          primary key(kind,sig,house,roadtype,lat,lon,label)) without rowid""")
        rows=[]
        for old,kind,lat,lon,label in db.execute("select key,kind,lat,lon,label from places"):
            if kind==0:
                name,sep,num=label.rpartition(",")
                h=house(num) if sep else None
                if not h: continue
                typ=street_type(name)
                sigs={key(name,True)}
                # Index aliases derived from real OSM street-name tags. Keep the
                # original house identity and road type, even if the alias lacks it.
                from build_almaty_index import normalize
                suffix=normalize(num,True)
                if suffix and old.endswith(" "+suffix):
                    sigs.add(key(old[:-(len(suffix)+1)],True))
                rows.extend((0,s,h,typ,lat,lon,label) for s in sigs if s)
            elif kind==1:
                sig=key(label,False)
                if sig: rows.append((1,sig,"","",lat,lon,label))
            if len(rows)>=4096:
                db.executemany("insert or ignore into smart_candidates values (?,?,?,?,?,?,?)",rows);rows.clear()
        db.executemany("insert or ignore into smart_candidates values (?,?,?,?,?,?,?)",rows)
        assert db.execute("pragma quick_check").fetchone()==("ok",)
        counts=dict(db.execute("select kind,count(*) from smart_candidates group by kind"))
        assert counts.get(0,0)>10000 and counts.get(1,0)>1000, counts
        print("SMART_INDEX",counts,flush=True)
if __name__=="__main__": main(sys.argv[1])
