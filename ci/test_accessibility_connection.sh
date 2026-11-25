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
import android.content.Intent;
import android.os.Bundle;
import android.widget.TextView;

public final class FixtureActivity extends Activity {
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        show(getIntent());
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        show(intent);
    }

    private void show(Intent intent) {
        TextView screen = new TextView(this);
        if (intent.getBooleanExtra("accepted", false)) {
            screen.setText("Б: Центральная улица, 8 04:43\nОплата картой 4090т\n"
                + "Стоимость поездки с учетом пробок\nПассажир\nКомфорт+\nОжидание\nЗавершить\n"
                + intent.getIntExtra("frame", 0));
        } else {
            screen.setText("Пропустить\nБ 12 км 1 ч 20 мин\n500 м · 4 мин\nБлижняя подача\nКомфорт+\n"
                + "А: улица Тестовая, 135\nБ: Центральная улица, 8\nПассажир\nПринять ×1.00");
        }
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
    <boolean name="ocr_allowed" value="true" />
</map>
XML
adb shell am start -W -n "$activity"
launch_driver_fixture
adb logcat -c
enable_service
wait_for_log "Order overlay attached"
wait_for_log "First offer quote drawn"
wait_for_log "Almaty lookup prepared"
latency=$(adb logcat -d -s "$log_tag:V" | sed -n 's/.*First offer quote drawn in \([0-9][0-9]*\)ms.*/\1/p' | head -n1)
test "$latency" -le 4000
echo "Native test order rendered in ${latency}ms from first detection on Android API $api"

if (( api >= 34 )); then
    main_pid=$(adb shell pidof "$package" | tr -d '\r')
    worker_pid=""
    for attempt in {1..25}; do
        worker_pid=$(adb shell pidof "$package:ocr" | tr -d '\r' || true)
        if [[ -n "$worker_pid" ]]; then break; fi
        sleep 1
    done
    test -n "$worker_pid"
    test "$worker_pid" != "$main_pid"
    adb shell run-as "$package" kill -9 "$worker_pid"
    sleep 2
    test "$(adb shell pidof "$package" | tr -d '\r')" = "$main_pid"
    adb shell dumpsys accessibility | grep 'Bound services:' | grep 'Знай цену' >/dev/null
    echo "Accessibility remained bound after OCR process was terminated on API $api"
fi

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


adb shell am start -W -n "$driver_package/.FixtureActivity" --activity-single-top --ez accepted true
wait_for_log "Accepted fare opened once"
wait_for_log "Accepted fare returned to waiting"
adb shell am start -W -n "$driver_package/.FixtureActivity" --activity-single-top --ez accepted true --ei frame 1
sleep 2
count=$(adb logcat -d -s "$log_tag:V" | grep -c 'Accepted fare opened once')
test "$count" -eq 1
echo "Accepted price displayed once, then stayed collapsed after refresh on Android API $api"
