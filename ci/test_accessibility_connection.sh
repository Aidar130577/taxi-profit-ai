#!/usr/bin/env bash
set -euo pipefail

package=kz.taxiprofitai
activity="$package/.MainActivity"
service="$package/$package.RadarAccessibilityService"
driver_package=ru.yandex.taximeter
log_tag=ZnayTsenuService
api=$(adb shell getprop ro.build.version.sdk)
test_dir=$(mktemp -d)
trap 'rm -rf "$test_dir"' EXIT

diagnostics() {
    adb shell settings get secure enabled_accessibility_services
    adb shell dumpsys accessibility | grep -E 'Bound services|Binding services|Enabled services|Crashed services' || true
    adb logcat -d -s "$log_tag:V" "AndroidRuntime:E" || true
}

wait_for_log() {
    local message="$1"
    for attempt in {1..25}; do
        if adb logcat -d -s "$log_tag:V" | grep -F "$message" >/dev/null; then
            return 0
        fi
        sleep 1
    done
    diagnostics
    echo "Expected app event: $message" >&2
    return 1
}

launch_driver_fixture() {
    adb shell am start -W -n "$driver_package/.FixtureActivity"
}

build_driver_fixture() {
    local sdk="$ANDROID_HOME/platforms/android-35/android.jar"
    local build="$ANDROID_HOME/build-tools/35.0.0"
    mkdir -p "$test_dir/classes"
    cat > "$test_dir/AndroidManifest.xml" <<'XML'
<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="ru.yandex.taximeter">
    <uses-sdk android:minSdkVersion="28" android:targetSdkVersion="34"/>
    <application android:label="Calculator test fixture">
        <activity android:name=".FixtureActivity" android:exported="true"/>
    </application>
</manifest>
XML
    cat > "$test_dir/FixtureActivity.java" <<'JAVA'
package ru.yandex.taximeter;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public final class FixtureActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        TextView screen = new TextView(this);
        screen.setText("Calculator test fixture");
        setContentView(screen);
    }
}
JAVA
    javac --release 8 -classpath "$sdk" -d "$test_dir/classes" "$test_dir/FixtureActivity.java"
    "$build/d8" --lib "$sdk" --min-api 28 --output "$test_dir" "$test_dir/classes/ru/yandex/taximeter/FixtureActivity.class"
    "$build/aapt2" link -I "$sdk" --manifest "$test_dir/AndroidManifest.xml" -o "$test_dir/fixture-unsigned.apk"
    (cd "$test_dir" && zip -q fixture-unsigned.apk classes.dex)
    "$build/zipalign" -f 4 "$test_dir/fixture-unsigned.apk" "$test_dir/fixture-aligned.apk"
    keytool -genkeypair -keystore "$test_dir/fixture.jks" -storepass android -keypass android \
        -alias fixture -dname CN=Fixture -keyalg RSA -validity 3
    "$build/apksigner" sign --ks "$test_dir/fixture.jks" --ks-pass pass:android \
        --out "$test_dir/fixture.apk" "$test_dir/fixture-aligned.apk"
}

enable_service() {
    adb shell settings put secure enabled_accessibility_services "$service"
    adb shell settings put secure accessibility_enabled 1
    wait_for_log "Accessibility service connected"
}

build_driver_fixture
adb install "$test_dir/fixture.apk"
adb install "$1"
# Seed an active calculator session and start the fixture. UI Automator's
# default connection temporarily suppresses installed accessibility services.
adb shell run-as "$package" mkdir -p shared_prefs
adb shell run-as "$package" sh -c \
    "'cat > shared_prefs/taxi_profit_settings.xml'" <<'XML'
<?xml version="1.0" encoding="utf-8" standalone="yes"?>
<map>
    <boolean name="shift_active" value="true" />
    <boolean name="ocr_choice" value="true" />
    <boolean name="ocr_allowed" value="false" />
</map>
XML
adb shell am start -W -n "$activity"
launch_driver_fixture
adb logcat -c
enable_service
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
echo "Service connection, overlay and reconnect verified on API $api"
