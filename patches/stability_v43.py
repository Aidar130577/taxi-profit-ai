#!/usr/bin/env python3
"""v43: guided, explicitly consented setup; preserve existing local history."""
from pathlib import Path
p = Path("app/src/main/java/kz/taxiprofitai/MainActivity.kt")
s = p.read_text()
def replace(old, new):
    global s
    if s.count(old) != 1:
        raise SystemExit("Unexpected v42 source anchor: " + old[:100])
    s = s.replace(old, new, 1)

replace("    private val statusHandler = Handler(Looper.getMainLooper())", """    private lateinit var setupButton: Button
    private var setupRequested = false
    private var setupSettingsOpened = false
    private var setupDeadline = 0L
    private val statusHandler = Handler(Looper.getMainLooper())""")
replace("            statusHandler.postDelayed(this, 750L)", """            if (setupRequested && setupSettingsOpened) {
                if (RadarAccessibilityService.connected) {
                    setupRequested = false
                    setupSettingsOpened = false
                    startCalculator()
                } else if (setupDeadline > 0L &&
                    android.os.SystemClock.elapsedRealtime() > setupDeadline) {
                    setupRequested = false
                    setupSettingsOpened = false
                }
            }
            statusHandler.postDelayed(this, 750L)""")
replace("        val connected = RadarAccessibilityService.connected\n        val label = when {", """        val connected = RadarAccessibilityService.connected
        if (::setupButton.isInitialized) {
            setupButton.text = if (connected) "Включить калькулятор" else "Разрешить всё"
        }
        val label = when {""")
replace("        super.onResume()\n        statusHandler.post(refreshServiceStatus)", """        super.onResume()
        if (setupRequested && setupSettingsOpened) {
            setupDeadline = android.os.SystemClock.elapsedRealtime() + 20_000L
        }
        statusHandler.removeCallbacks(refreshServiceStatus)
        statusHandler.post(refreshServiceStatus)""")
replace('''        root.addView(action("Включить калькулятор",true){
            if(save()){
                if (RadarAccessibilityService.connected) startCalculator() else openServiceSettings()
            }
        },LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)))''', '''        setupButton = action(if (RadarAccessibilityService.connected) "Включить калькулятор" else "Разрешить всё",true){
            if(save()){
                if (RadarAccessibilityService.connected) startCalculator() else beginPermissionSetup()
            }
        }
        root.addView(setupButton,LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)))''')
replace("    private fun openServiceSettings() {", """    private fun beginPermissionSetup() {
        setupRequested = true
        setupSettingsOpened = false
        if (checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
            android.content.pm.PackageManager.PERMISSION_GRANTED) {
            openServiceSettings()
            return
        }
        android.app.AlertDialog.Builder(this)
            .setTitle("Разрешить всё")
            .setMessage("Для калькулятора нужно разрешение Android на чтение карточки заказа Яндекс Про. GPS поездок необязателен: он измеряет километраж и помогает запоминать адреса на телефоне. Подтверждения выдаются только владельцем телефона.")
            .setNegativeButton("Без GPS") { _, _ -> openServiceSettings() }
            .setPositiveButton("Разрешить GPS") { _, _ ->
                requestPermissions(arrayOf(android.Manifest.permission.ACCESS_FINE_LOCATION,
                    android.Manifest.permission.ACCESS_COARSE_LOCATION), 43)
            }
            .setOnCancelListener { setupRequested = false }
            .show()
    }

    private fun openServiceSettings() {""")
replace('''            .setNegativeButton("Закрыть", null)
            .setPositiveButton("Открыть настройки"){ _, _ ->
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }''', '''            .setNegativeButton("Закрыть") { _, _ -> setupRequested = false }
            .setOnCancelListener { setupRequested = false }
            .setPositiveButton("Открыть настройки"){ _, _ ->
                if (setupRequested) {
                    setupSettingsOpened = true
                    setupDeadline = 0L
                }
                startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            }''')
replace("        super.onRequestPermissionsResult(requestCode, permissions, grantResults)", """        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 43) {
            if (checkSelfPermission(android.Manifest.permission.ACCESS_FINE_LOCATION) ==
                android.content.pm.PackageManager.PERMISSION_GRANTED) {
                prefs.edit().putBoolean("ride_gps_enabled", true).apply()
            }
            if (setupRequested) openServiceSettings()
            return
        }""")
p.write_text(s)

# Bound route work to avoid an ever-growing queue after repeated offer refreshes.
# Do not change map coverage or tariff calibration in this stability patch.
p = Path("app/src/main/java/kz/taxiprofitai/BRouterConnector.kt")
s = p.read_text()
s = s.replace("    private var closed = false", "    @Volatile private var closed = false")
# All route results still use the existing main-thread callback and existing router worker.
p.write_text(s)
