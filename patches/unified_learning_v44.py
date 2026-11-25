#!/usr/bin/env python3
"""Unified setup for learning; no permission or consent bypass."""
from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
p=base/"MainActivity.kt"
s=p.read_text()
def edit(old,new):
    global s
    assert s.count(old)==1,old[:100]
    s=s.replace(old,new,1)

# Always direct the driver through the single setup entry if consent has not
# been recorded, even if Android accessibility is already connected.
edit('if (RadarAccessibilityService.connected) startCalculator() else beginPermissionSetup()', '''if (prefs.getBoolean("learning_setup_v44", false) && RadarAccessibilityService.connected)
                    startCalculator()
                else beginPermissionSetup()''')
edit('setupButton.text = if (connected) "Включить калькулятор" else "Разрешить всё"', '''setupButton.text = if (connected && prefs.getBoolean("learning_setup_v44", false))
                "Включить калькулятор" else "Разрешить всё"''')
a=s.index("    private fun beginPermissionSetup() {")
b=s.index("    private fun openServiceSettings() {",a)
s=s[:a]+'''    private fun beginPermissionSetup() {
        setupRequested = true
        setupSettingsOpened = false
        if (prefs.getBoolean("learning_setup_v44", false)) {
            continuePermissionSetup()
            return
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Автоматическое обучение")
            .setMessage("Одно подтверждение включает локальное обучение стоимости, времени и скорости, GPS поездок, локальное распознавание карточек Яндекс Про на Android 14+ и запрос погоды MET Norway (передаётся IP-адрес и координаты центра Алматы). GPS требует системного разрешения. Адресные точки остаются на телефоне, снимки окна не сохраняются и не отправляются. Обмен дорожными данными между водителями пока не подключён. Согласие можно отозвать в разделе «Конфиденциальность».")
            .setNeutralButton("Условия погоды") { _, _ ->
                startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(CityWeather.TERMS)))
                setupRequested = false
            }
            .setNegativeButton("Не сейчас") { _, _ -> setupRequested = false }
            .setPositiveButton("Разрешить всё") { _, _ ->
                prefs.edit().putBoolean("learning_setup_v44", true)
                    .putBoolean("ride_gps_enabled", true)
                    .putBoolean("ocr_choice", true)
                    .putBoolean("ocr_allowed", android.os.Build.VERSION.SDK_INT >= 34)
                    .putBoolean(CityWeather.ENABLED, true).apply()
                getSharedPreferences("local_traffic_pilot", MODE_PRIVATE)
                    .edit().putBoolean("enabled", true).apply()
                continuePermissionSetup()
            }
            .setOnCancelListener { setupRequested = false }
            .show()
    }

    private fun continuePermissionSetup() {
        if (prefs.getBoolean("ride_gps_enabled", false) &&
            checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) !=
                android.content.pm.PackageManager.PERMISSION_GRANTED &&
            !prefs.getBoolean("gps_prompted_v44", false)) {
            prefs.edit().putBoolean("gps_prompted_v44", true).apply()
            requestPermissions(arrayOf(android.Manifest.permission.ACCESS_FINE_LOCATION,
                android.Manifest.permission.ACCESS_COARSE_LOCATION), 43)
            return
        }
        finishPermissionSetup()
    }

    private fun finishPermissionSetup() {
        if (RadarAccessibilityService.connected) {
            setupRequested = false
            setupSettingsOpened = false
            startCalculator()
        } else openServiceSettings()
    }

'''+s[b:]
edit('if (setupRequested) openServiceSettings()\n            return','if (setupRequested) finishPermissionSetup()\n            return')
edit('''        root.addView(action("GPS и погода"){ showTripSensors() })
        root.addView(action("Обучение скорости движения") { LocalTrafficPilot.show(this) })''','''        root.addView(action("Самообучение · состояние") { showLearningStatus() })
        root.addView(action("Конфиденциальность") { showLearningPrivacy() })''')
edit('''        if (android.os.Build.VERSION.SDK_INT >= 34) {
            root.addView(action("Распознавание адресов"){ showOcrSettings() })
        }''','')
a=s.index("    private fun startTripGps() {")
s=s[:a]+'''    private fun showLearningStatus() {
        val gps = prefs.getBoolean("ride_gps_enabled", false) &&
            checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED
        val traffic = getSharedPreferences("local_traffic_pilot", MODE_PRIVATE).getBoolean("enabled", false)
        val ocr = android.os.Build.VERSION.SDK_INT >= 34 && prefs.getBoolean("ocr_allowed", false)
        val weather = prefs.getBoolean(CityWeather.ENABLED, false)
        fun state(value: Boolean) = if (value) "включено" else "не включено"
        android.app.AlertDialog.Builder(this)
            .setTitle("Самообучение")
            .setMessage("Стоимость, время и адреса: автоматически при доступных данных.\\nGPS: " +
                state(gps) + "\\nСкорость: " + state(traffic) + "\\nOCR: " + state(ocr) +
                "\\nПогода: " + state(weather) + "\\nКоллективный обмен: ещё не подключён.")
            .setPositiveButton("Закрыть", null)
            .show()
    }

    private fun showLearningPrivacy() {
        android.app.AlertDialog.Builder(this)
            .setTitle("Конфиденциальность")
            .setItems(arrayOf("GPS и погода", "Распознавание адресов", "Локальная статистика скорости",
                "Повторить настройку", "Остановить сбор GPS и распознавание")) { _, index ->
                when(index) {
                    0 -> showTripSensors()
                    1 -> if (android.os.Build.VERSION.SDK_INT >= 34) showOcrSettings()
                    2 -> LocalTrafficPilot.show(this)
                    3 -> {
                        prefs.edit().remove("learning_setup_v44").remove("gps_prompted_v44").apply()
                        beginPermissionSetup()
                    }
                    4 -> {
                        prefs.edit().putBoolean("ride_gps_enabled", false)
                            .putBoolean("ocr_choice", true).putBoolean("ocr_allowed", false)
                            .putBoolean(CityWeather.ENABLED, false).apply()
                        getSharedPreferences("local_traffic_pilot", MODE_PRIVATE)
                            .edit().putBoolean("enabled", false).apply()
                        RideGpsService.stop(this)
                    }
                }
            }.setNegativeButton("Закрыть", null).show()
    }

'''+s[a:]
p.write_text(s)
