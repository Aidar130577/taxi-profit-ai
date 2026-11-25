#!/usr/bin/env python3
"""Local, opt-in road-speed observation pilot; no network transmission."""
from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p=base/name
    s=p.read_text()
    assert s.count(old)==1, (name,old)
    p.write_text(s.replace(old,new,1))
edit("MainActivity.kt", '        root.addView(action("GPS и погода"){ showTripSensors() })', '''        root.addView(action("GPS и погода"){ showTripSensors() })
        root.addView(action("Обучение скорости движения") { LocalTrafficPilot.show(this) })''')
edit("RideGpsService.kt", '''            else if (metres >= 5 && (!location.hasSpeed() || location.speed >= 0.8f)) totalMetres += metres''', '''            else if (metres >= 5 && (!location.hasSpeed() || location.speed >= 0.8f)) totalMetres += metres
            if (seconds in 1.0..15.0 && time - startedAt >= 60_000_000_000L) {
                LocalTrafficPilot.observe(this, old, location, seconds, metres)
            }''')
(base/"LocalTrafficPilot.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.location.Location
import java.security.MessageDigest
import java.util.Calendar
import java.util.TimeZone
import kotlin.math.floor

/** Coarse directional grid measurements, NOT OSM map-matched road edges. */
internal object LocalTrafficPilot {
    private const val FILE = "local_traffic_pilot"
    private const val ENABLED = "enabled"
    private const val MAX_KEYS = 2000
    private const val EXPIRY_MS = 28L * 24 * 60 * 60 * 1000
    private fun prefs(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    fun show(activity: Activity) {
        val p = prefs(activity)
        val enabled = p.getBoolean(ENABLED, false)
        val count = p.all.keys.count { it.startsWith("g:") }
        AlertDialog.Builder(activity)
            .setTitle("Обучение скорости движения · локальный тест")
            .setMessage("Сохранено групп замеров: " + count + ". Только при активной поездке и точном GPS. Скорости группируются по приблизительному участку, направлению и часу. Сырые маршруты, адреса, сведения о пассажирах и точное время поездки не сохраняются этим модулем. Пока данные не отправляются на сервер и не изменяют цену.")
            .setNegativeButton("Закрыть", null)
            .setNeutralButton("Очистить") { _, _ -> p.edit().clear().putBoolean(ENABLED,false).apply() }
            .setPositiveButton(if (enabled) "Отключить" else "Включить") { _, _ ->
                p.edit().putBoolean(ENABLED,!enabled).apply()
            }.show()
    }
    fun observe(context: Context, old: Location, next: Location, seconds: Double, metres: Double) {
        val p=prefs(context)
        if (!p.getBoolean(ENABLED,false)) return
        if (!old.hasAccuracy() || old.accuracy > 18f || !next.hasAccuracy() || next.accuracy > 18f ||
            old.isFromMockProvider || next.isFromMockProvider) return
        val speed = metres * 3.6 / seconds
        if (!speed.isFinite() || speed !in 2.0..110.0 || metres < 10.0) return
        val lat = (old.latitude + next.latitude) / 2
        val lon = (old.longitude + next.longitude) / 2
        if (lat !in 40.0..56.0 || lon !in 45.0..88.0) return
        val direction = floor((old.bearingTo(next) + 360f + 45f) % 360f / 90f).toInt()
        val hour=Calendar.getInstance(TimeZone.getTimeZone("Asia/Almaty")).get(Calendar.HOUR_OF_DAY)
        val cell="grid-v1:" + floor(lat * 500).toInt() + ":" + floor(lon * 500).toInt() + ":" + direction
        val hash=MessageDigest.getInstance("SHA-256").digest(cell.toByteArray(Charsets.UTF_8))
            .take(8).joinToString("") { "%02x".format(it.toInt() and 255) }
        val key="g:" + hash + ":" + hour
        val now=System.currentTimeMillis()
        val existing=p.getString(key,null)?.split(":")
        val stamp=existing?.getOrNull(2)?.toLongOrNull() ?: 0L
        val fresh=now-stamp in 0..EXPIRY_MS
        val count=if (fresh) existing?.getOrNull(1)?.toIntOrNull()?.coerceIn(0,24) ?: 0 else 0
        val mean=if (fresh) existing?.getOrNull(0)?.toDoubleOrNull()?.takeIf { it.isFinite() } ?: speed else speed
        val n=count.coerceAtMost(8)
        val average=(mean*n+speed)/(n+1)
        val editor=p.edit()
        if (existing==null) {
            val entries=p.all.filterKeys { it.startsWith("g:") }
            if(entries.size>=MAX_KEYS) {
                val remove=entries.minByOrNull { (_,v) -> (v as? String)?.substringAfterLast(':')?.toLongOrNull() ?: 0L }
                if(remove!=null) editor.remove(remove.key)
            }
        }
        // Day-level retention timestamp, no individual trip or precise GPS timestamp.
        editor.putString(key,average.toString()+":"+(count+1).coerceAtMost(24)+":"+(now/86400000L*86400000L)).apply()
    }
}
''')
