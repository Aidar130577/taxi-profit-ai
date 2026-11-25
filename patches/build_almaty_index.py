#!/usr/bin/env python3
"""Build the Android offline address index from the Geofabrik Kazakhstan PBF."""
import argparse
from collections import Counter
from pathlib import Path
import re
import sqlite3
import unicodedata

import osmium

BOUNDS = (43.12, 76.70, 43.45, 77.17)
SOURCE = "https://download.geofabrik.de/asia/kazakhstan.html"
ATTRIBUTION = "© OpenStreetMap contributors, ODbL 1.0"
ACTIONS = re.compile(r"[^\w]+|_", re.U)
PREFIX = re.compile(r"^(?:кафе|кофейня|ресторан|магазин|трц|тц|бц|жк|здание|отель|гостиница)\s+")
STREET = re.compile(r"\b(?:улица|ул|проспект|просп|пр|микрорайон|мкр|көшесі|даңғылы|street|avenue)\b")
CORPUS = re.compile(r"(\d+[а-яa-z]?)\s*(?:корпус|корп|к|k)\s*(\d+[а-яa-z]?)\b")
POI = ("amenity", "shop", "tourism", "office", "healthcare", "leisure", "building", "public_transport", "railway", "craft", "sport")
NAME_KEYS = ("name", "name:ru", "name:kk", "name:en", "alt_name", "official_name", "short_name")


def normalize(text, is_address):
    text = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")
    if is_address:
        text = CORPUS.sub(r"\1 корпус \2", text)
        text = STREET.sub(" ", text)
    else:
        text = PREFIX.sub("", text.strip())
    return " ".join(ACTIONS.sub(" ", text).split())


def in_bounds(lat, lon):
    south, west, north, east = BOUNDS
    return south <= lat <= north and west <= lon <= east


class Extract(osmium.SimpleHandler):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.pending = []
        self.seen = Counter()

    def relevant(self, tags):
        return (tags.get("addr:housenumber") and (tags.get("addr:street") or tags.get("addr:place"))) or (
            any(tags.get(k) for k in POI) and any(tags.get(k) for k in NAME_KEYS)
        )

    def add(self, tags, lat, lon):
        x, y = round(lat * 1_000_000), round(lon * 1_000_000)
        house = tags.get("addr:housenumber")
        street = tags.get("addr:street") or tags.get("addr:place")
        if house and street:
            for number in house.split(";"):
                label = f"{street}, {number.strip()}"
                self.queue(normalize(label, True), 0, x, y, label)
        if any(tags.get(k) for k in POI):
            names = {name.strip() for k in NAME_KEYS for name in (tags.get(k) or "").split(";")}
            for name in sorted(names):
                self.queue(normalize(name, False), 1, x, y, name)

    def queue(self, key, kind, x, y, label):
        if not 3 <= len(key) <= 200 or not any(c.isalpha() for c in key):
            return
        self.pending.append((key, kind, x, y, label))
        self.seen[kind] += 1
        if len(self.pending) >= 4096:
            self.flush()

    def flush(self):
        self.db.executemany("insert or ignore into places values (?, ?, ?, ?, ?)", self.pending)
        self.pending.clear()

    def node(self, node):
        loc = node.location
        if loc.valid() and in_bounds(loc.lat, loc.lon) and self.relevant(node.tags):
            self.add(node.tags, loc.lat, loc.lon)

    def way(self, way):
        if not self.relevant(way.tags):
            return
        points = [(n.lat, n.lon) for n in way.nodes if n.location.valid()]
        if not points:
            return
        if len(points) > 1 and points[0] == points[-1]:
            points.pop()
        lat = sum(p[0] for p in points) / len(points)
        lon = sum(p[1] for p in points) / len(points)
        if in_bounds(lat, lon):
            self.add(way.tags, lat, lon)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pbf", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".building")
    temp.unlink(missing_ok=True)
    db = sqlite3.connect(temp)
    try:
        db.executescript("""
            pragma journal_mode = OFF;
            create table places (key text not null, kind integer not null, lat integer not null,
                lon integer not null, label text not null,
                primary key(key, kind, lat, lon)) without rowid;
            create table metadata (key text primary key, value text not null) without rowid;
        """)
        with osmium.io.Reader(str(args.pbf)) as source:
            source_date = source.header().get("osmosis_replication_timestamp")
        extract = Extract(db)
        extract.apply_file(str(args.pbf), locations=True)
        extract.flush()
        db.executemany("insert into metadata values (?, ?)", [
            ("source", SOURCE), ("attribution", ATTRIBUTION), ("snapshot", source_date),
            ("bounds", ",".join(str(v) for v in BOUNDS)),
        ])
        counts = dict(db.execute("select kind, count(*) from places group by kind"))
        if counts.get(0, 0) < 10_000 or counts.get(1, 0) < 1000:
            raise SystemExit(f"Incomplete Almaty extract: {counts}")
        assert db.execute("pragma quick_check").fetchone() == ("ok",)
        db.commit()
        db.execute("vacuum")
        print(f"ALMATY_OSM: {counts[0]} address rows, {counts[1]} named-place rows, snapshot {source_date}", flush=True)
    finally:
        db.close()
    temp.replace(args.output)


if __name__ == "__main__":
    main()
