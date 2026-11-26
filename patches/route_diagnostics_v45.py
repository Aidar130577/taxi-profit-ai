#!/usr/bin/env python3
"""Retain the actual BRouter geometry and optional completed GPS trace locally."""
from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
def edit(name,old,new):
    p=base/name
    s=p.read_text()
    assert s.count(old)==1,(name,old[:160])
    p.write_text(s.replace(old,new,1))

edit("BRouterRouteResult.kt", '    val provisional: Boolean = false)', '''    val provisional: Boolean = false,
    val geometry: List<RoutePoint> = emptyList(),
    val requestedA: RoutePoint? = null,
    val requestedB: RoutePoint? = null)
data class RoutePoint(val lat: Double, val lon: Double)''')
edit("EmbeddedRoadRouter.kt", '        return OfflineRoute(result.distance / 1000.0, result.totalSeconds / 60.0)', '''        val points = result.nodes.map { node ->
            RoutePoint(node.getILat() / 1_000_000.0 - 90.0, node.getILon() / 1_000_000.0 - 180.0)
        }
        return OfflineRoute(result.distance / 1000.0, result.totalSeconds / 60.0,
            geometry = points, requestedA = RoutePoint(fromLat, fromLon), requestedB = RoutePoint(toLat, toLon))''')
# Store the road geometry only for the same offer after its forecast row exists.
edit("RadarAccessibilityService.kt", '''                        } else if (!route.provisional) {
                            detected.trialId?.let { TrialStore.observeRoute(this, it, adjusted, route) }
                        }
                        render()''', '''                        } else if (!route.provisional) {
                            detected.trialId?.let { TrialStore.observeRoute(this, it, adjusted, route) }
                        }
                        if (!route.provisional && loggedOffer && route.geometry.size >= 2) {
                            detected.trialId?.let { id ->
                                RouteTraceStore.savePlan(this, id, route, adjusted, quote.gross, knownSurcharge(newer))
                            }
                        }
                        render()''')
edit("RadarAccessibilityService.kt", '''            rideTiming.startVerified(id, destination, android.os.SystemClock.elapsedRealtime())
            RideGpsService.record(rideTiming.active)''', '''            rideTiming.startVerified(id, destination, android.os.SystemClock.elapsedRealtime())
            RideGpsService.traceId(id)
            RideGpsService.record(rideTiming.active)''')
edit("RadarAccessibilityService.kt", '''            TrialStore.saveActual(this, fact.rowId, minutes = fact.minutes,
                km = RideGpsService.distanceKm(fact.minutes), automatic = true)''', '''            val actualKm = RideGpsService.distanceKm(fact.minutes)
            RideGpsService.saveTrace(fact.rowId, fact.minutes, actualKm)
            TrialStore.saveActual(this, fact.rowId, minutes = fact.minutes,
                km = actualKm, automatic = true)''')
edit("RideGpsService.kt", '        fun record(active: Boolean) { current?.recordRide(active) }', '''        fun record(active: Boolean) { current?.recordRide(active) }
        fun traceId(id: Long) { current?.bindTrace(id) }
        fun clearTrace() { current?.clearTraceBuffer() }
        fun saveTrace(id: Long, minutes: Double, km: Double?) {
            current?.let { service ->
                if (service.traceRow == id && service.recording) {
                    RouteTraceStore.saveGps(service, id, service.trace.toList(), minutes, km, service.gaps || service.traceLimited)
                }
            }
        }''')
edit("RideGpsService.kt", '    private var gaps = false', '''    private var gaps = false
    private var traceRow: Long? = null
    private val trace = mutableListOf<RoutePoint?>()
    private var traceLimited = false
    private fun clearTraceBuffer() { trace.clear(); traceRow = null; traceLimited = false }
    private fun bindTrace(id: Long) {
        if (traceRow != id) {
            clearTraceBuffer()
            traceRow = id
        }
    }''')
edit("RideGpsService.kt", '''            locations.removeUpdates(this)
            return''', '''            locations.removeUpdates(this)
            clearTraceBuffer()
            return''')
edit("RideGpsService.kt", '''        prior = location
        samples++''', '''        if (!RouteTraceStore.enabled(this)) {
            trace.clear()
            traceLimited = false
        } else if (traceRow != null && !traceLimited) {
            val seconds = old?.let { (time - it.elapsedRealtimeNanos) / 1_000_000_000.0 }
            if (old != null && seconds != null && (seconds > 45 || old.distanceTo(location) / seconds > 55))
                trace.add(null)
            trace.add(RoutePoint(location.latitude, location.longitude))
            if (trace.size >= 4096) traceLimited = true
        }
        prior = location
        samples++''')
edit("MainActivity.kt", '            dialog.setItems(labels) { _, index -> confirmTrip(rows[index]) }', '''            dialog.setItems(labels) { _, index ->
                val row = rows[index]
                android.app.AlertDialog.Builder(this)
                    .setTitle(row.tariff)
                    .setItems(arrayOf("Показать маршрут BRouter и GPS", "Подтвердить факт поездки")) { _, choice ->
                        if (choice == 0) RouteTraceStore.show(this, row) else confirmTrip(row)
                    }.show()
            }''')
edit("MainActivity.kt", '        root.addView(action("История прогнозов"){ showLearningHistory() })', '''        root.addView(action("История прогнозов"){ showLearningHistory() })
        root.addView(action("Диагностика маршрутов") { RouteTraceStore.settings(this) })''')

(base/"RouteTraceStore.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.util.AtomicFile
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import kotlin.math.cos

/** Device-only diagnostics. No network, passenger identifiers or screenshot storage. */
internal object RouteTraceStore {
    private const val MAX_AGE = 7L * 86_400_000
    private const val MAX_FILES = 80
    private fun prefs(c: Context) = c.getSharedPreferences("route_diagnostics", Context.MODE_PRIVATE)
    fun enabled(c: Context) = prefs(c).getBoolean("enabled", false)
    private fun folder(c: Context) = File(c.noBackupFilesDir, "route-diagnostics")
    private fun file(c: Context, id: Long) = File(folder(c), "$id.json")
    private fun prune(c: Context) {
        val now = System.currentTimeMillis()
        val files = folder(c).listFiles()?.filter { it.name.endsWith(".json") }.orEmpty()
        files.filter { now - it.lastModified() !in 0..MAX_AGE }.forEach { AtomicFile(it).delete() }
        folder(c).listFiles()?.filter { it.name.endsWith(".json") }
            ?.sortedByDescending { it.lastModified() }?.drop(MAX_FILES)?.forEach { AtomicFile(it).delete() }
    }
    private fun read(c: Context, id: Long): JSONObject {
        if (!enabled(c)) return JSONObject()
        prune(c)
        return runCatching { JSONObject(String(AtomicFile(file(c,id)).readFully(), Charsets.UTF_8)) }
            .getOrElse { JSONObject() }
    }
    private fun write(c: Context, id: Long, data: JSONObject) {
        if (!enabled(c)) return
        runCatching {
            folder(c).mkdirs()
            val f = AtomicFile(file(c,id))
            val stream = f.startWrite()
            try { stream.write(data.toString().toByteArray(Charsets.UTF_8)); f.finishWrite(stream) }
            catch(e: Exception) { f.failWrite(stream); throw e }
            prune(c)
        }
    }
    private fun encode(points: List<RoutePoint?>): JSONArray = JSONArray().apply {
        points.forEach { p ->
            if (p == null) put(JSONObject.NULL)
            else put(JSONArray().put(p.lat).put(p.lon))
        }
    }
    private fun decode(a: JSONArray?): List<RoutePoint?> {
        if (a == null) return emptyList()
        return (0 until a.length()).map { i ->
            val point = a.optJSONArray(i)
            val lat = point?.optDouble(0) ?: Double.NaN
            val lon = point?.optDouble(1) ?: Double.NaN
            if (lat in -90.0..90.0 && lon in -180.0..180.0) RoutePoint(lat,lon) else null
        }
    }
    @Synchronized fun savePlan(c: Context, id: Long, raw: OfflineRoute, adjusted: OfflineRoute,
                               gross: Double, surcharge: Double?) {
        if (!enabled(c) || raw.provisional || raw.geometry.size < 2) return
        val d = read(c,id)
        // Keep the first real geometry, not a later recalculation under changed conditions.
        if (d.has("plan")) return
        d.put("plan", encode(raw.geometry)).put("rawKm", raw.km).put("rawMinutes",raw.minutes)
            .put("usedKm",adjusted.km).put("usedMinutes",adjusted.minutes).put("gross",gross)
        surcharge?.let { d.put("surcharge",it) }
        raw.requestedA?.let { d.put("a",encode(listOf(it))) }
        raw.requestedB?.let { d.put("b",encode(listOf(it))) }
        write(c,id,d)
    }
    @Synchronized fun saveGps(c: Context, id: Long, points: List<RoutePoint?>,
                              minutes: Double, km: Double?, incomplete: Boolean) {
        if (!enabled(c) || points.count { it != null } < 2) return
        val d = read(c,id)
        d.put("gps",encode(points)).put("gpsMinutes",minutes).put("gpsIncomplete",incomplete || km == null)
        km?.let { d.put("gpsKm",it) }
        write(c,id,d)
    }
    fun settings(activity: Activity) {
        prune(activity)
        val active = enabled(activity)
        AlertDialog.Builder(activity).setTitle("Диагностика маршрутов")
            .setMessage("По согласию сохраняются точные линии прогноза и GPS завершённых поездок только на этом телефоне, до 7 дней и 80 записей. Это отдельная диагностическая функция. Не отправляется в общую базу. Обычное самообучение работает и без неё.")
            .setPositiveButton(if(active) "Выключить и удалить" else "Разрешить сохранение") { _, _ ->
                prefs(activity).edit().putBoolean("enabled",!active).apply()
                if(active) { RideGpsService.clearTrace(); folder(activity).deleteRecursively() }
            }.setNeutralButton("Удалить маршруты") { _, _ ->
                RideGpsService.clearTrace()
                folder(activity).deleteRecursively()
            }.setNegativeButton("Закрыть",null).show()
    }
    fun show(activity: Activity,row: LocalTrial) {
        val d = read(activity,row.id)
        val plan=decode(d.optJSONArray("plan"))
        val gps=decode(d.optJSONArray("gps"))
        if(plan.isEmpty() && gps.isEmpty()) {
            AlertDialog.Builder(activity).setTitle("Маршрут не сохранён")
                .setMessage("Для старых поездок линии отсутствуют. Для новых включите диагностику маршрутов. Если построение не удалось, синей линии не будет.")
                .setPositiveButton("Настройки") { _, _ -> settings(activity) }
                .setNegativeButton("Закрыть",null).show()
            return
        }
        fun number(key:String):String = d.optDouble(key).takeIf(Double::isFinite)?.let { "%.2f".format(it) } ?: "—"
        val root = LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL; setPadding(16,12,16,12) }
        root.addView(TextView(activity).apply {
            text="Синий — BRouter; зелёный — GPS\\n" +
                "BRouter: "+number("rawKm")+" км / "+number("rawMinutes")+" мин\\n" +
                "В расчёте: "+number("usedKm")+" км / "+number("usedMinutes")+" мин\\n" +
                "Цена: "+number("gross")+" ₸; надбавка: "+number("surcharge")+" ₸\\n" +
                "GPS: "+number("gpsKm")+" км / "+number("gpsMinutes")+" мин" +
                (if(d.optBoolean("gpsIncomplete")) " (неполные данные)" else "")+
                "\\nСхема точных линий без фоновой карты улиц."
        })
        root.addView(TraceView(activity,plan,gps,decode(d.optJSONArray("a")).firstOrNull(),
            decode(d.optJSONArray("b")).firstOrNull()),LinearLayout.LayoutParams(-1,
            (260*activity.resources.displayMetrics.density).toInt()))
        AlertDialog.Builder(activity).setTitle("Маршрут поездки").setView(root)
            .setNeutralButton("Удалить линии") { _, _ -> AtomicFile(file(activity,row.id)).delete() }
            .setPositiveButton("Закрыть",null).show()
    }
}
private class TraceView(c: Context, private val plan:List<RoutePoint?>, private val gps:List<RoutePoint?>,
                        private val a:RoutePoint?,private val b:RoutePoint?): View(c) {
    private val paint=Paint(Paint.ANTI_ALIAS_FLAG)
    override fun onDraw(canvas:Canvas) {
        super.onDraw(canvas)
        canvas.drawColor(Color.rgb(242,245,247))
        val points=(plan+gps+listOf(a,b)).filterNotNull()
        if(points.isEmpty())return
        val lon0=points.minOf { it.lon }; val lat0=points.minOf { it.lat }
        val factor=cos(Math.toRadians(lat0)).coerceAtLeast(0.01)
        val dx=((points.maxOf{it.lon}-lon0)*factor).coerceAtLeast(0.0001)
        val dy=(points.maxOf{it.lat}-lat0).coerceAtLeast(0.0001)
        val margin=32f
        val scale=minOf((width-2*margin)/dx,(height-2*margin)/dy).coerceAtLeast(1.0)
        fun x(p:RoutePoint)=(width/2.0+( (p.lon-lon0)*factor-dx/2)*scale).toFloat()
        fun y(p:RoutePoint)=(height/2.0-(p.lat-lat0-dy/2)*scale).toFloat()
        fun line(list:List<RoutePoint?>,color:Int) {
            val path=Path();var first=true
            for(p in list) { if(p==null){first=true;continue};if(first)path.moveTo(x(p),y(p))else path.lineTo(x(p),y(p));first=false }
            paint.style=Paint.Style.STROKE;paint.strokeWidth=5f;paint.strokeJoin=Paint.Join.ROUND
            paint.strokeCap=Paint.Cap.ROUND;paint.color=color;canvas.drawPath(path,paint)
        }
        line(plan,Color.rgb(28,98,211));line(gps,Color.rgb(13,143,73))
        fun marker(p:RoutePoint?,label:String){ if(p==null)return
            paint.style=Paint.Style.FILL;paint.color=Color.rgb(25,37,46);canvas.drawCircle(x(p),y(p),7f,paint)
            paint.textSize=24f;canvas.drawText(label,x(p)+8f,y(p)-8f,paint)
        }
        marker(a,"А");marker(b,"Б")
    }
}
''')
p=Path("core-tests/EmbeddedRouterCheck.kt")
s=p.read_text()
old='            print("\${result.km} km / \${result.minutes} min: ")'.replace('\\$','$')
# Test actual geometry coordinate bounds, endpoints, and non-empty route.
anchor='            check(!result.provisional && result.km in row[4]..row[5] && result.minutes > 0) { result }'
assert s.count(anchor)==1
p.write_text(s.replace(anchor,anchor+'''
            check(result.geometry.size >= 2)
            check(result.geometry.all { it.lat in 42.0..44.0 && it.lon in 75.0..78.0 })
            check(result.requestedA == RoutePoint(row[0],row[1]) && result.requestedB == RoutePoint(row[2],row[3]))
            check(kotlin.math.abs(result.geometry.first().lat-row[0]) < 0.015)
            check(kotlin.math.abs(result.geometry.last().lat-row[2]) < 0.015)''',1))
