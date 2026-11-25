#!/usr/bin/env python3
"""v44: user-controlled OEM setup, connected-service recovery, and exit diagnostics."""
from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p=base/name
    s=p.read_text()
    assert s.count(old)==1, (name,old)
    p.write_text(s.replace(old,new,1))

edit("MainActivity.kt", '        root.addView(action("История прогнозов"){ showLearningHistory() })', '''        root.addView(action("Стабильная работа") {
            StabilityGuide.show(this, accessibilityAllowed(), RadarAccessibilityService.connected)
        })
        root.addView(action("История прогнозов"){ showLearningHistory() })''')
edit("MainActivity.kt", 'allowed -> "Разрешение сохранено. Android пока не подключил службу чтения заказов."', '''allowed -> "Разрешение сохранено, но Android не подключил службу. В специальных возможностях выключите и снова включите «Знай цену». Перезагрузка не является первым шагом. Если сбой после очистки приложений, проверьте «Стабильная работа»."''')
edit("MainActivity.kt", '''            .setNegativeButton("Закрыть") { _, _ -> setupRequested = false }
            .setOnCancelListener { setupRequested = false }''', '''            .setNegativeButton("Закрыть") { _, _ -> setupRequested = false }
            .setNeutralButton("Стабильность") { _, _ ->
                setupRequested = false
                StabilityGuide.show(this, accessibilityAllowed(), RadarAccessibilityService.connected)
            }
            .setOnCancelListener { setupRequested = false }''')

# Retry only while the system has actually connected our service and the driver
# has enabled the calculator. No forced binding or background launch.
edit("RadarAccessibilityService.kt", '    private var overlayAttempts = 0', '''    private var overlayAttempts = 0
    private val recoveryTick = object : Runnable {
        override fun run() {
            if (!connected || !prefs.getBoolean("shift_active", false)) return
            try {
                if (!running) startShift()
                else if (android.os.SystemClock.elapsedRealtime() - lastScan > 3000L) {
                    // Normal package/window checks in scanActiveWindow remain in effect.
                    overlayAttempts = 0
                    scheduleScan(0L)
                }
            } catch (e: Exception) {
                recordFailure("Восстановление калькулятора", e)
            } finally {
                ui.removeCallbacks(this)
                if (connected && prefs.getBoolean("shift_active", false))
                    ui.postDelayed(this, 4000L)
            }
        }
    }''')
edit("RadarAccessibilityService.kt", '''            if (prefs.getBoolean("shift_active", false)) startShift()
        } catch (e: Exception) {
            recordFailure("Подключение службы", e)''', '''            prefs.edit().putLong("last_service_connected", System.currentTimeMillis()).apply()
            if (prefs.getBoolean("shift_active", false)) {
                ui.removeCallbacks(recoveryTick)
                ui.postDelayed(recoveryTick, 4000L)
                startShift()
            }
        } catch (e: Exception) {
            recordFailure("Подключение службы", e)''')
edit("RadarAccessibilityService.kt", '''                if (prefs.getBoolean("shift_active", false)) startShift() else stopShift()''', '''                if (prefs.getBoolean("shift_active", false)) {
                    ui.removeCallbacks(recoveryTick)
                    ui.postDelayed(recoveryTick, 4000L)
                    startShift()
                } else {
                    ui.removeCallbacks(recoveryTick)
                    stopShift()
                }''')
edit("RadarAccessibilityService.kt", '''    private fun disconnect() {
        connected = false''', '''    private fun disconnect() {
        ui.removeCallbacks(recoveryTick)
        prefs.edit().putLong("last_service_disconnected", System.currentTimeMillis()).apply()
        connected = false''')
edit("RadarAccessibilityService.kt", 'override fun onInterrupt(){}', '''override fun onInterrupt() {
        // Interrupt is not revocation. Retry the normal scan if still connected.
        if (connected && running) {
            overlayAttempts = 0
            scheduleScan(300L)
        }
    }''')

edit("ServiceExitDiagnostics.kt", '''                    "Системная диагностика · $label · код ${record.reason}"''', '''                    val lastConnected = context.getSharedPreferences("taxi_profit_settings", Context.MODE_PRIVATE)
                        .getLong("last_service_connected", 0L)
                    val stamp = java.text.DateFormat.getDateTimeInstance().format(java.util.Date(record.timestamp))
                    val historical = if (record.timestamp < lastConnected) " (до последнего подключения)" else ""
                    "Последнее завершение: $stamp$historical · $label · код ${record.reason}"
                ''')
(base/"StabilityGuide.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.widget.Toast

internal object StabilityGuide {
    fun show(activity: Activity, allowed: Boolean, connected: Boolean) {
        val power = activity.getSystemService(PowerManager::class.java)
        val unrestricted = power?.isIgnoringBatteryOptimizations(activity.packageName) == true
        val service = if (connected) "подключена" else if (allowed) "разрешена, не подключена" else "выключена"
        val history = ServiceExitDiagnostics.summary(activity) ?: "Нет доступной записи о завершении."
        val info = "Служба: " + service + "\\n" +
            "Исключение из Android-оптимизации: " + (if (unrestricted) "да" else "нет") + "\\n" +
            "Устройство: " + Build.MANUFACTURER + " " + Build.MODEL + ", Android " + Build.VERSION.RELEASE + "\\n" +
            history + "\\n\\n" +
            "Xiaomi: в сведениях о приложении проверьте автозапуск и батарею «Без ограничений». " +
            "Для защиты от очистки недавних приложений закрепите карточку замочком в меню недавних. " +
            "Эти настройки Xiaomi меняются только пользователем. Android не предоставляет приложению права включать их самостоятельно."
        val labels = arrayOf("Восстановить службу чтения заказов", "Открыть настройки приложения",
            "Оптимизация батареи Android", "Как закрепить замочком", "Копировать диагностику")
        AlertDialog.Builder(activity)
            .setTitle("Стабильная работа")
            .setMessage(info)
            .setPositiveButton("Настроить") { _, _ ->
                AlertDialog.Builder(activity).setTitle("Настройки стабильности")
                    .setItems(labels) { _, index ->
                        when (index) {
                            0 -> open(activity, Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
                            1 -> open(activity, Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                Uri.parse("package:" + activity.packageName)))
                            2 -> open(activity, Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                            3 -> AlertDialog.Builder(activity).setTitle("Закрепление приложения")
                                .setMessage("Откройте список недавних приложений. Удерживайте карточку «Знай цену» и нажмите замок, если он есть. На некоторых версиях Xiaomi: Безопасность → Ускорение → настройки → Закреплённые приложения. Не используйте «Очистить все», если система всё равно отключает службу.")
                                .setPositiveButton("Понятно", null).show()
                            4 -> {
                                val clip = activity.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                                clip.setPrimaryClip(android.content.ClipData.newPlainText("Знай цену", info))
                                Toast.makeText(activity,"Диагностика скопирована",Toast.LENGTH_SHORT).show()
                            }
                        }
                    }.setNegativeButton("Закрыть",null).show()
            }.setNegativeButton("Закрыть",null).show()
    }
    private fun open(activity: Activity, intent: Intent) {
        try { activity.startActivity(intent) }
        catch (_: Exception) { Toast.makeText(activity,"Откройте этот раздел в настройках телефона",Toast.LENGTH_LONG).show() }
    }
}
''')
