#!/usr/bin/env bash
set -euo pipefail

package=kz.taxiprofitai
activity="$package/.MainActivity"
service="$package/$package.RadarAccessibilityService"
adb install android-project/app/build/outputs/apk/debug/app-debug.apk
adb shell am start -W -n "$activity"

wait_for_status() {
    local status="$1"
    for attempt in {1..7}; do
        adb shell uiautomator dump /sdcard/znay-test-window.xml >/dev/null 2>&1 || true
        if adb shell cat /sdcard/znay-test-window.xml | grep -F "text=\"$status\"" >/dev/null; then
            return 0
        fi
        sleep 2
    done
    adb shell dumpsys accessibility | grep -F "$package" || true
    adb logcat -d -t 250 "*:E" | tail -50 || true
    echo "Expected Android permission status: $status" >&2
    return 1
}

wait_for_status "Не включено"
adb shell settings put secure enabled_accessibility_services "$service"
adb shell settings put secure accessibility_enabled 1
wait_for_status "Включено"
adb shell settings delete secure enabled_accessibility_services
adb shell settings put secure accessibility_enabled 0
wait_for_status "Не включено"
adb shell settings put secure enabled_accessibility_services "$service"
adb shell settings put secure accessibility_enabled 1
wait_for_status "Включено"
echo "Accessibility connection, disconnect and reconnect verified on Android 14"
