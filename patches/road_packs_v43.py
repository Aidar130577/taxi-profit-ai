#!/usr/bin/env python3
"""Add an explicit offline-road download action; retain files across upgrades."""
from pathlib import Path
base = Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p = base / name
    s = p.read_text()
    assert s.count(old) == 1, (name, old)
    p.write_text(s.replace(old, new, 1))

edit("BRouterConnector.kt", '''            val root = File(context.noBackupFilesDir, "offline-roads")
            @Suppress("DEPRECATION")
            val revision = context.packageManager.getPackageInfo(context.packageName, 0).lastUpdateTime
            val folder = File(root, revision.toString())''', '''            val folder = KazakhstanRoadPacks.directory(context)''')
edit("BRouterConnector.kt", '            root.listFiles()?.filter { it != folder }?.forEach { it.deleteRecursively() }\n', '')
edit("EmbeddedRoadRouter.kt", '    private fun covers(lat: Double, lon: Double) = lat >= 40.0 && lat < 45.0 && lon >= 75.0 && lon < 80.0', '''    private fun covers(lat: Double, lon: Double): Boolean {
        val name = KazakhstanRoadTiles.name(lat, lon) ?: return false
        return File(data, name).let { it.isFile && it.length() > 0 }
    }''')
edit("EmbeddedRoadRouter.kt", "Точка вне офлайн-карты Алматы", "Нет дорожного квадрата для одной из точек")
edit("MainActivity.kt", '        root.addView(action("Данные карты © OpenStreetMap") {', '''        root.addView(action("Офлайн-карты Казахстана") { KazakhstanRoadPacks.show(this) })
        root.addView(action("Данные карты © OpenStreetMap") {''')
edit("MainActivity.kt", "Дорожный сегмент Алматы и окрестностей включён в приложение.", "Карта Алматы встроена. Остальные дорожные квадраты можно загрузить отдельно. Адреса и тарифы других городов требуют проверки.")
edit("RouteTestActivity.kt", "Встроенная карта покрывает Алматы и окрестности.", "Проверь загруженные дорожные квадраты и адреса.")
(base / "KazakhstanRoadTiles.kt").write_text('''package kz.taxiprofitai

internal object KazakhstanRoadTiles {
    val names = (40..55 step 5).flatMap { south ->
        (45..85 step 5).map { west -> "E" + west + "_N" + south + ".rd5" }
    }
    fun name(lat: Double, lon: Double): String? {
        if (!lat.isFinite() || !lon.isFinite() || lat < 40 || lat >= 60 || lon < 45 || lon >= 90) return null
        return "E" + (kotlin.math.floor(lon / 5).toInt() * 5) +
            "_N" + (kotlin.math.floor(lat / 5).toInt() * 5) + ".rd5"
    }
}
''')
(base / "KazakhstanRoadPacks.kt").write_text('''package kz.taxiprofitai

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.widget.Toast
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.atomic.AtomicBoolean

internal object KazakhstanRoadPacks {
    private val busy = AtomicBoolean(false)
    fun directory(context: Context) = File(context.noBackupFilesDir, "offline-roads-shared")
    private fun present(context: Context, name: String) =
        name == "E75_N40.rd5" || File(directory(context), name).let { it.isFile && it.length() > 0 }

    fun show(activity: Activity) {
        val context = activity.applicationContext
        val missing = KazakhstanRoadTiles.names.filterNot { present(context, it) }
        val labels = (listOf("Загрузить все недостающие") + missing).toTypedArray()
        AlertDialog.Builder(activity)
            .setTitle("Дорожные квадраты: " + (36 - missing.size) + " / 36")
            .setItems(labels) { _, index ->
                if (missing.isEmpty()) return@setItems
                val selected = if (index == 0) missing else listOf(missing[index - 1])
                AlertDialog.Builder(activity)
                    .setTitle("Загрузка " + selected.size + " квадратов")
                    .setMessage("Файлы OpenStreetMap / BRouter могут занимать много места. Используйте Wi-Fi. Адресный индекс и тарифы других городов ещё не проверены.")
                    .setNegativeButton("Отмена", null)
                    .setPositiveButton("Загрузить") { _, _ -> download(activity, selected) }
                    .show()
            }.setNegativeButton("Закрыть", null).show()
    }
    private fun download(activity: Activity, names: List<String>) {
        if (!busy.compareAndSet(false, true)) return
        val context = activity.applicationContext
        val cancelled = AtomicBoolean(false)
        val dialog = AlertDialog.Builder(activity)
            .setTitle("Загрузка дорог")
            .setMessage("Подготовка…")
            .setNegativeButton("Остановить") { _, _ -> cancelled.set(true) }
            .setOnCancelListener { cancelled.set(true) }.show()
        Thread {
            var status = "Загрузка завершена"
            try {
                val folder = directory(context)
                check(folder.isDirectory || folder.mkdirs())
                for ((i, name) in names.withIndex()) {
                    if (cancelled.get()) break
                    if (present(context, name)) continue
                    activity.runOnUiThread {
                        if (!activity.isDestroyed && dialog.isShowing)
                            dialog.setMessage((i + 1).toString() + " / " + names.size + " · " + name)
                    }
                    val target = File(folder, name)
                    val part = File(folder, name + ".part")
                    val c = URL("https://brouter.de/brouter/segments4/" + name).openConnection() as HttpURLConnection
                    c.connectTimeout = 15000
                    c.readTimeout = 30000
                    try {
                        check(c.responseCode == 200) { "HTTP " + c.responseCode + ": " + name }
                        val expected = c.contentLengthLong
                        if (expected > 0) check(folder.usableSpace > expected + 33554432) { "Недостаточно места" }
                        c.inputStream.use { input ->
                            part.outputStream().use { output ->
                                val buffer = ByteArray(65536)
                                while (!cancelled.get()) {
                                    val n = input.read(buffer)
                                    if (n < 0) break
                                    output.write(buffer, 0, n)
                                }
                            }
                        }
                        if (cancelled.get()) break
                        check(part.length() > 0 && (expected < 0 || expected == part.length())) { "Неполный файл" }
                        check(part.renameTo(target)) { "Не удалось сохранить файл" }
                    } finally { c.disconnect(); part.delete() }
                }
                if (cancelled.get()) status = "Загрузка остановлена"
            } catch (e: Exception) { status = e.message ?: "Ошибка загрузки" }
            finally {
                busy.set(false)
                activity.runOnUiThread {
                    if (!activity.isDestroyed) {
                        if (dialog.isShowing) dialog.dismiss()
                        Toast.makeText(activity, status, Toast.LENGTH_LONG).show()
                    }
                }
            }
        }.apply { name = "kazakhstan-road-download"; start() }
    }
}
''')
