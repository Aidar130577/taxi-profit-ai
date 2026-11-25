#!/usr/bin/env bash
set -euo pipefail

project=${1:-.}
upstream=${2:-}
segment=${3:-}
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

if [[ -z "$upstream" ]]; then
    upstream="$work/brouter.tar.gz"
    curl --fail --silent --show-error --location --retry 3 --max-time 120 \
        https://codeload.github.com/abrensch/brouter/tar.gz/refs/tags/v1.7.10 -o "$upstream"
fi
echo "cb83f220332de8223476e029a9b075157fb74401c69a991ceaa013486c29760f  $upstream" | sha256sum -c -
mkdir -p "$work/src" "$work/classes" "$project/app/libs" "$project/app/src/main/assets/brouter"
tar -xzf "$upstream" -C "$work/src" --strip-components=1
find "$work/src"/brouter-{core,mapaccess,codec,expressions,util}/src/main/java -name '*.java' | sort > "$work/java-files"
javac --release 11 -encoding UTF-8 -d "$work/classes" @"$work/java-files"
jar --create --file "$project/app/libs/brouter-1.7.10.jar" -C "$work/classes" .

data="$project/app/src/main/assets/brouter"
cp "$work/src/LICENSE" "$data/LICENSE-BRouter.txt"
cp "$work/src/misc/profiles2/"{car-vario.brf,lookups.dat} "$data/"
if [[ -z "$segment" ]]; then
    segment="$work/E75_N40.rd5"
    curl --fail --silent --show-error --location --retry 3 --max-time 180 \
        https://brouter.de/brouter/segments4/E75_N40.rd5 -o "$segment"
fi
test "$(wc -c < "$segment")" -ge 1000000
cp "$segment" "$data/E75_N40.rd5"
cat > "$data/DATA-NOTICE.txt" <<'NOTICE'
E75_N40.rd5 is the unmodified BRouter routing tile covering 40–45°N, 75–80°E.
Source and a machine-readable copy: https://brouter.de/brouter/segments4/E75_N40.rd5
Road data © OpenStreetMap contributors. Open Database License (ODbL) 1.0.
https://www.openstreetmap.org/copyright
https://opendatacommons.org/licenses/odbl/1-0/
BRouter engine and profiles: https://github.com/abrensch/brouter (MIT).
NOTICE
