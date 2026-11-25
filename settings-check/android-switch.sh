#!/usr/bin/env bash
set -euo pipefail

temp_dir=$(mktemp -d)
trap 'rm -rf "$temp_dir"' EXIT
package=kz.taxiprofitai
service="$package/$package.RadarAccessibilityService"

capture_settings() {
    local remote=/sdcard/znay-system-settings.xml
    for attempt in {1..6}; do
        adb shell rm -f "$remote"
        adb shell uiautomator dump "$remote" >/dev/null 2>&1 || true
        if adb shell test -s "$remote" && adb pull "$remote" "$temp_dir/settings.xml" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    adb shell dumpsys activity activities | grep -E 'ResumedActivity|topResumedActivity' || true
    return 1
}

find_target() {
    python3 - "$temp_dir/settings.xml" "$@" <<'PY'
import re
import sys
from xml.etree import ElementTree

root = ElementTree.parse(sys.argv[1])
nodes = list(root.iter('node'))
for query in sys.argv[2:]:
    kind, value = query.split('=', 1)
    for node in nodes:
        if kind == 'class' and node.get('class') != value:
            continue
        if kind == 'text' and node.get('text', '').casefold() != value.casefold():
            continue
        if kind == 'prefix' and not node.get('text', '').casefold().startswith(value.casefold()):
            continue
        left, top, right, bottom = map(int, re.findall(r'\d+', node.get('bounds', '')))
        if right > left and bottom > top:
            print((left + right) // 2, (top + bottom) // 2)
            sys.exit(0)
sys.exit(1)
PY
}

show_labels() {
    python3 - "$temp_dir/settings.xml" <<'PY'
import sys
from xml.etree import ElementTree
for node in ElementTree.parse(sys.argv[1]).iter('node'):
    if node.get('text'):
        print(node.get('text'))
PY
}

tap_target() {
    local xy x y
    xy=$(find_target "$@") || return 1
    read -r x y <<< "$xy"
    adb shell input tap "$x" "$y"
    sleep 1
}

adb install "$1"
adb shell am start -W -n "$package/.MainActivity"
adb logcat -c
adb shell am start -W -a android.settings.ACCESSIBILITY_SETTINGS
for attempt in {1..5}; do
    capture_settings
    if tap_target 'prefix=Знай цену'; then break; fi
    if tap_target 'text=Downloaded apps' 'text=Installed apps' 'text=Downloaded services'; then continue; fi
    if (( attempt == 5 )); then show_labels; exit 1; fi
    read -r width height < <(adb shell wm size | tail -n1 | sed -E 's/.* ([0-9]+)x([0-9]+).*/\1 \2/')
    adb shell input swipe "$((width / 2))" "$((height * 4 / 5))" "$((width / 2))" "$((height / 3))" 280
done
capture_settings
tap_target 'prefix=Use Знай цену' 'class=android.widget.Switch' 'class=android.widget.CompoundButton' || { show_labels; exit 1; }
capture_settings
tap_target 'text=Allow' 'text=Yes' 'text=OK' 'text=Start now' || { show_labels; exit 1; }

for attempt in {1..20}; do
    enabled=$(adb shell settings get secure enabled_accessibility_services)
    if [[ "$enabled" == *"$service"* ]] &&
        adb logcat -d -s 'ZnayTsenuService:V' | grep -F 'Accessibility service connected' >/dev/null; then
        adb shell dumpsys accessibility | grep 'Bound services:' | grep 'Знай цену'
        echo 'APK accessibility service enabled through Android 14 Settings and bound successfully'
        exit 0
    fi
    sleep 1
done
adb shell dumpsys accessibility | grep -E 'Bound services|Binding services|Enabled services|Crashed services' || true
adb logcat -d -s 'ZnayTsenuService:V' 'AndroidRuntime:E' || true
exit 1
