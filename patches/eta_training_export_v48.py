"""Explicitly export numeric training observations; no automatic transmission."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
p=root/"MainActivity.kt"
s=p.read_text()
anchor='        root.addView(action("Самообучение · состояние") { showLearningStatus() })'
assert s.count(anchor)==1
s=s.replace(anchor,anchor+'''
        root.addView(action("Данные для CatBoost") {
            android.app.AlertDialog.Builder(this)
                .setTitle("Обезличенная статистика")
                .setMessage("Поделиться только числовыми параметрами подтверждённых поездок для обучения вне телефона? Без адресов, координат, цены, телефона и номера заказа. Данные не отправляются автоматически.")
                .setNegativeButton("Отмена",null)
                .setPositiveButton("Поделиться"){_,_->EtaTrainingExport.share(this)}
                .show()
        })''')
p.write_text(s)
(root/"EtaTrainingExport.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.util.UUID
import java.security.MessageDigest
import kotlin.math.sin
import kotlin.math.cos

internal object EtaTrainingExport {
    fun share(activity: Activity) {
        val prefs=activity.getSharedPreferences("eta_export_private",Context.MODE_PRIVATE)
        val salt=prefs.getString("salt",null) ?: UUID.randomUUID().toString().also {
            prefs.edit().putString("salt",it).commit()
        }
        val result=JSONArray()
        for (row in TrialStore.read(activity)) {
            if (row.excluded || row.provisional || !row.hasForecast || row.priceSource != FareFactSource.RECEIPT) continue
            val rk=row.offlineKm ?: continue
            val rt=row.offlineMinutes ?: continue
            val yk=row.initialBadgeKm ?: continue
            val yt=row.initialBadgeMinutes ?: continue
            val base=row.combinedMinutes ?: continue
            val actual=row.actualMinutes ?: continue
            if (rk !in 0.05..300.0 || yk !in 0.05..300.0 ||
                listOf(rt,yt,base,actual).any { it !in 0.5..300.0 }) continue
            val whenLocal=Instant.ofEpochMilli(row.createdAtMs).atZone(ZoneId.of("Asia/Almaty"))
            val h=2.0*Math.PI*whenLocal.hour/24.0
            val d=2.0*Math.PI*(whenLocal.dayOfWeek.value-1)/7.0
            val id=MessageDigest.getInstance("SHA-256").digest((salt+":"+row.id).toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it.toInt() and 255) }
            val surcharge=row.fixedSurcharge?.takeIf { it in 0.0..100000.0 } ?: -1.0
            result.put(JSONObject().put("schema",1).put("sample_id",id)
                .put("confirmed",true).put("day",whenLocal.toLocalDate().toString())
                .put("road_km",rk).put("road_min",rt).put("yandex_km",yk).put("yandex_min",yt)
                .put("base_min",base).put("surcharge",surcharge)
                .put("hour_sin",sin(h)).put("hour_cos",cos(h))
                .put("weekday_sin",sin(d)).put("weekday_cos",cos(d)).put("actual_min",actual))
        }
        if(result.length()==0) {
            Toast.makeText(activity,"Нет подходящих подтверждённых поездок",Toast.LENGTH_LONG).show()
            return
        }
        val send=Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,result.toString())
        activity.startActivity(Intent.createChooser(send,"Передать числовую статистику"))
    }
}
''')
p=root/"TrialStore.kt"
s=p.read_text()
a='        // Never overwrite the confirmed fact. Full trip badge is kept distinct'
assert s.count(a)==1
s=s.replace(a,'        if (row.priceSource != null || row.actualGross != null || row.actualMinutes != null) return\n'+a)
p.write_text(s)
print("Voluntary numeric ETA export installed; no automatic uploads.")
