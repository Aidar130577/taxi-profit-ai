#!/usr/bin/env bash
set -euo pipefail

package=kz.taxiprofitai
activity="$package/.MainActivity"
service="$package/$package.RadarAccessibilityService"
log_tag=ZnayTsenuService

diagnostics() {
    adb shell settings get secure enabled_accessibility_services
    adb shell dumpsys accessibility | grep -E 'Bound services|Binding services|Enabled services|Crashed services' || true
    adb logcat -d -s "$log_tag:V" "AndroidRuntime:E" || true
}

wait_for_log() {
    local message="$1"
    for attempt in {1..20}; do
        if adb logcat -d -s "$log_tag:V" | grep -F "$message" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    diagnostics
    echo "Expected app event: $message" >&2
    return 1
}

adb install "$1"
adb shell am start -W -n "$activity"
adb shell uiautomator dump /sdcard/znay-test-window.xml
adb pull /sdcard/znay-test-window.xml /tmp/znay-test-window.xml
read -r button_x button_y < <(python3 - <<'PY'
import re
from xml.etree import ElementTree

root = ElementTree.parse('/tmp/znay-test-window.xml')
assert root.find('.//node[@text="Не включено"]') is not None
button = root.find('.//node[@text="Включить калькулятор"]')
left, top, right, bottom = map(int, re.findall(r'\d+', button.attrib['bounds']))
print((left + right) // 2, (top + bottom) // 2)
PY
)

# UI Automator changes service availability while it is connected.
# After enabling the service use app logs and shell input only.
enable_service() {
    adb shell settings put secure enabled_accessibility_services "$service"
    adb shell settings put secure accessibility_enabled 1
    wait_for_log "Accessibility service connected"
}

adb logcat -c
enable_service
adb shell input tap "$button_x" "$button_y"
wait_for_log "Order overlay attached"
adb shell settings put secure accessibility_enabled 0
adb shell settings delete secure enabled_accessibility_services
for attempt in {1..15}; do
    if ! adb shell dumpsys activity services "$service" | grep -F 'ServiceRecord{' >/dev/null; then break; fi
    sleep 1
done
adb logcat -c
enable_service
wait_for_log "Order overlay attached"
echo "Service connection, overlay and reconnect verified on API $(adb shell getprop ro.build.version.sdk)"
