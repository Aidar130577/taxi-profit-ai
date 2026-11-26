"""Add an opt-in public-route TomTom pilot, never change production offer pricing."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
p=root/"MainActivity.kt"
s=p.read_text()
anchor='        root.addView(action("Самообучение · состояние") { showLearningStatus() })'
assert s.count(anchor)==1
p.write_text(s.replace(anchor,anchor+'\n        root.addView(action("TomTom · тест пробок") { TomTomPilot.show(this) })',1))
p=Path("app/build.gradle.kts")
s=p.read_text()
assert s.count("dependencies {")==1
if 'com.squareup.okhttp3:okhttp' not in s:
    s=s.replace("dependencies {",'dependencies { implementation("com.squareup.okhttp3:okhttp:4.12.0"); ',1)
p.write_text(s)
p=Path("app/src/main/AndroidManifest.xml")
s=p.read_text()
if 'android.permission.INTERNET' not in s:
    s=s.replace("<application ",'<uses-permission android:name="android.permission.INTERNET"/>\n    <application ',1)
p.write_text(s)
(root/"TomTomMetrics.kt").write_text('''package kz.taxiprofitai

internal data class TomTomMetrics(
    val km: Double, val minutes: Double,
    val noTrafficMinutes: Double?, val historicMinutes: Double?,
    val liveMinutes: Double?, val trafficDelayMinutes: Double?
) {
    companion object {
        fun from(meters: Double, seconds: Double, noTraffic: Double?,
                 historic: Double?, live: Double?, delay: Double?): TomTomMetrics? {
            if (!meters.isFinite() || !seconds.isFinite() || meters !in 1.0..300000.0 ||
                seconds !in 1.0..18000.0) return null
            fun time(value: Double?) = value?.takeIf { it.isFinite() && it in 0.0..18000.0 }?.div(60.0)
            return TomTomMetrics(meters/1000.0, seconds/60.0, time(noTraffic),
                time(historic), time(live), time(delay))
        }
    }
}
''')
(root/"TomTomRouter.kt").write_text('''package kz.taxiprofitai

import android.os.SystemClock
import android.util.Log
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import org.json.JSONObject
import java.io.IOException
import java.util.Locale
import java.util.concurrent.TimeUnit

internal object TomTomRouter {
    data class Point(val lat: Double,val lon: Double)
    data class Answer(val metrics: TomTomMetrics?, val status: String, val latencyMs: Long)
    private val client=OkHttpClient.Builder()
        .callTimeout(2,TimeUnit.SECONDS)
        .connectTimeout(1200,TimeUnit.MILLISECONDS)
        .readTimeout(1500,TimeUnit.MILLISECONDS)
        .retryOnConnectionFailure(false)
        .followRedirects(false).followSslRedirects(false).build()

    fun request(key:String,points:List<Point>,done:(Answer)->Unit):Call? {
        // No secret in the build or logs. Caller supplies a session key, never an address.
        if (!key.matches(Regex("[A-Za-z0-9_-]{12,128}")) ||
            points.size !in 2..10 || points.any { it.lat !in -90.0..90.0 || it.lon !in -180.0..180.0 }) return null
        val locations=points.joinToString(":") { String.format(Locale.US,"%.6f,%.6f",it.lat,it.lon) }
        val url=HttpUrl.Builder().scheme("https").host("api.tomtom.com")
            .addPathSegments("routing/1/calculateRoute").addPathSegment(locations).addPathSegment("json")
            .addQueryParameter("key",key)
            .addQueryParameter("traffic","true")
            .addQueryParameter("travelMode","car")
            .addQueryParameter("routeType","fastest")
            .addQueryParameter("routeRepresentation","summaryOnly")
            .addQueryParameter("computeTravelTimeFor","all")
            .build()
        val start=SystemClock.elapsedRealtime()
        fun finish(metrics:TomTomMetrics?,status:String) {
            val ms=SystemClock.elapsedRealtime()-start
            Log.i("ZnayTsenuTomTom","status="+status+" latencyMs="+ms)
            done(Answer(metrics,status,ms))
        }
        val call=client.newCall(Request.Builder().url(url).get().build())
        call.enqueue(object:Callback {
            override fun onFailure(call:Call,e:IOException) = finish(null,if(call.isCanceled()) "Отменено" else "Сеть / тайм-аут")
            override fun onResponse(call:Call,response:Response) {
                response.use { r ->
                    if(!r.isSuccessful) {
                        val status=when(r.code){401,403->"Ключ или доступ";429->"Лимит запросов";else->"HTTP "+r.code}
                        finish(null,status);return
                    }
                    val metrics=runCatching {
                        val source=r.body?.source() ?: error("empty")
                        if(source.request(65537L)) error("large response")
                        val summary=JSONObject(source.readUtf8()).getJSONArray("routes")
                            .getJSONObject(0).getJSONObject("summary")
                        fun optional(k:String)=summary.optDouble(k).takeIf(Double::isFinite)
                        TomTomMetrics.from(summary.getDouble("lengthInMeters"),summary.getDouble("travelTimeInSeconds"),
                            optional("noTrafficTravelTimeInSeconds"),optional("historicTrafficTravelTimeInSeconds"),
                            optional("liveTrafficIncidentsTravelTimeInSeconds"),optional("trafficDelayInSeconds"))
                    }.getOrNull()
                    finish(metrics,if(metrics==null)"Некорректный ответ" else "OK")
                }
            }
        })
        return call
    }
}
''')
(root/"TomTomPilot.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.app.AlertDialog
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale
import okhttp3.Call

/** Only predetermined non-personal test coordinates. No live order data or training exports. */
internal object TomTomPilot {
    fun show(activity:Activity) {
        val panel=LinearLayout(activity).apply { orientation=LinearLayout.VERTICAL;setPadding(24,12,24,12) }
        panel.addView(TextView(activity).apply {
            text="Эксперимент: публичные тестовые точки Алматы. Плашка заказа не изменяется. Ключ действует только в этом окне. Отправляются только тестовые координаты; результаты не сохраняются."
        })
        val key=EditText(activity).apply {
            hint="Личный ключ TomTom Freemium"
            inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setSaveEnabled(false)
        }
        panel.addView(key)
        val report=TextView(activity).apply { text="Ввод ключа и запуск — только на остановке." }
        panel.addView(report)
        var call:Call?=null
        var pipeline:OfflineRoutePipeline?=null
        var active=false
        var count=0
        var alive=true
        val dialog=AlertDialog.Builder(activity).setTitle("TomTom · сравнение маршрутов")
            .setView(panel).setPositiveButton("Проверить",null).setNegativeButton("Закрыть",null).create()
        dialog.setOnDismissListener { alive=false;call?.cancel();pipeline?.close();key.text.clear() }
        dialog.setOnShowListener {
            val button=dialog.getButton(AlertDialog.BUTTON_POSITIVE)
            button.setOnClickListener {
                if(active || count>=20)return@setOnClickListener
                val token=key.text.toString().trim()
                if(!token.matches(Regex("[A-Za-z0-9_-]{12,128}"))){report.text="Проверьте ключ";return@setOnClickListener}
                active=true;button.isEnabled=false;count++
                val a=TomTomRouter.Point(43.238300,76.945700)
                val b=TomTomRouter.Point(43.256700,76.928600)
                val route=if(count%2==1)listOf(a,b) else listOf(b,a)
                var left="BRouter: расчёт..."
                var right="TomTom: запрос..."
                var roadDone=false;var tomDone=false
                fun refresh() {
                    if(!alive)return
                    report.text=left+"\\n\\n"+right+"\\n\\nЗапросы в окне: "+count+"/20"
                    if(roadDone&&tomDone){active=false;button.isEnabled=count<20}
                }
                fun fmt(v:Double?)=v?.let{String.format(Locale.US,"%.1f",it)}?:"—"
                refresh()
                call=TomTomRouter.request(token,route) { answer -> activity.runOnUiThread {
                    if(!alive)return@runOnUiThread
                    val m=answer.metrics
                    right=if(m==null) "TomTom: "+answer.status+" ("+answer.latencyMs+" мс)"
                    else "TomTom: "+fmt(m.km)+" км / "+fmt(m.minutes)+" мин\\n"+
                        "Без пробок: "+fmt(m.noTrafficMinutes)+" мин\\nИстория: "+fmt(m.historicMinutes)+
                        " мин\\nТекущая дорожная задержка: "+fmt(m.trafficDelayMinutes)+" мин\\nЗапрос: "+answer.latencyMs+" мс"
                    tomDone=true;refresh()
                } }
                if(call==null){right="Некорректный запрос";tomDone=true;refresh()}
                pipeline?.close()
                pipeline=OfflineRoutePipeline(activity).also { p ->
                    val start=android.os.SystemClock.elapsedRealtime()
                    fun coordinate(point:TomTomRouter.Point)=String.format(Locale.US,"%.6f,%.6f",point.lat,point.lon)
                    p.calculate(coordinate(route[0]),coordinate(route[1])) { result ->
                        if(alive) {
                            val r=result.getOrNull()
                            left=if(r==null||r.provisional)"BRouter: нет подтверждённого маршрута"
                            else "BRouter: "+fmt(r.km)+" км / "+fmt(r.minutes)+" мин ("+
                                (android.os.SystemClock.elapsedRealtime()-start)+" мс)"
                            roadDone=true;refresh()
                        }
                    }
                }
            }
        }
        dialog.show()
    }
}
''')
p=Path("core-tests/TomTomMetricsCheck.kt")
p.write_text('''package kz.taxiprofitai
fun main() {
    val route=TomTomMetrics.from(12500.0,1800.0,1200.0,1500.0,1750.0,600.0)!!
    check(route.km==12.5 && route.minutes==30.0 && route.noTrafficMinutes==20.0 && route.trafficDelayMinutes==10.0)
    check(TomTomMetrics.from(0.0,60.0,null,null,null,null)==null)
    check(TomTomMetrics.from(Double.NaN,60.0,null,null,null,null)==null)
    check(TomTomMetrics.from(100.0,-1.0,null,null,null,null)==null)
    check(TomTomMetrics.from(100.0,60.0,null,null,null,-2.0)!!.trafficDelayMinutes==null)
    println("TomTom route metric validation passed")
}
''')
print("TomTom public-route pilot added; production offer calculations untouched.")
