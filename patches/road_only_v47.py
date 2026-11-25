"""Remove fabricated straight-line 30 km/h offer forecasts from generated app."""
from pathlib import Path
root = Path("app/src/main/java/kz/taxiprofitai")

p = root / "BRouterRouteResult.kt"
s = p.read_text()
a = s.index("internal object FastRouteEstimate {")
b = s.index("object BRouterRouteResult {", a)
p.write_text(s[:a] + s[b:])

p = root / "OfflineRoutePipeline.kt"
s = p.read_text()
a = s.index("                                if (from.exact && to.exact) {")
b = s.index("                                brouter.route(from.point, to.point)", a)
p.write_text(s[:a] + s[b:])

p = root / "RadarAccessibilityService.kt"
s = p.read_text()
a = s.index("                    pipeline.calculate(newer.pickup, newer.destination, preview = { route ->")
b = s.index("                    }) { result ->", a) + len("                    }) { result ->")
s = s[:a] + "                    pipeline.calculate(newer.pickup, newer.destination) { result ->" + s[b:]
s = s.replace("                    var finishedRoute = false\n", "")
s = s.replace("                            finishedRoute = true\n", "")
anchor = "                    val submit = submit@{ route: OfflineRoute ->\n"
assert s.count(anchor) == 1
s = s.replace(anchor, anchor + """                        if (route.provisional) {
                            estimate = null
                            routeStatus = "Нет маршрута BRouter"
                            render()
                            return@submit
                        }
""")
p.write_text(s)

# Keep historical provisional-record exclusion tests; remove only tests of deleted estimator.
p = Path("core-tests/AutoLearningCheck.kt")
s = p.read_text()
a = s.index("    check(FastRouteEstimate.between(")
b = s.index("    check(FastRouteEstimate.SHOW_AFTER_MS < 1_000L)", a)
b = s.index("\n", b) + 1
p.write_text(s[:a] + s[b:])
assert not any("FastRouteEstimate" in f.read_text() for f in root.rglob("*.kt"))
assert "preview = { route ->" not in (root / "RadarAccessibilityService.kt").read_text()
print("Road-only check: no straight-line estimator, no preview callback; historical provisional rows retained.")


# Compact overlay: fixed small footprint, regardless of addresses and paid pickup.
p = root / "OfferPopupView.kt"
s = p.read_text()
a = s.index("    private val logicalHeight get() = ")
b = s.index("\n", a)
s = s[:a] + "    private val logicalHeight get() = if (waiting) 38 else if (hasQuote) 96 else 116" + s[b:]
a = s.index("        line(c,78f)")
b = s.index("        c.restore()", a)
s = s[:a] + """        // Show a short explanation only while a usable fare is unavailable.
        if (!hasQuote) {
            line(c,92f)
            text(c,footer,120f,108f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)
        }
""" + s[b:]
# Width is specified in the window and also in the view's measurement.
assert s.count("(240 * density).toInt()") == 1
s = s.replace("(240 * density).toInt()", "(144 * density).toInt()")
assert "if (logicalHeight != oldHeight) requestLayout()" in s
assert s.index("hasQuote = estimate != null") < s.index("if (logicalHeight != oldHeight) requestLayout()")
# Two equal columns: Yandex gross and take-home amount.
a = s.index("        line(c,29f);text(c,gross,")
b = s.index("        // Show a short explanation", a)
s = s[:a] + """        line(c,29f)
        paint.color = Color.WHITE
        paint.strokeWidth = 1f
        c.drawLine(120f, 34f, 120f, 90f, paint)
        text(c,"яндекс",60f,50f,16f,yellow,true,Paint.Align.CENTER,110f)
        text(c,"на руки",180f,50f,16f,green,true,Paint.Align.CENTER,110f)
        // Fit both amounts to the same full column width, with 3 logical
        // pixels of clearance on each side. Keep the same font height.
        fun amount(value: String, center: Float, color: Int) {
            val clean = value.replace("≈", "").trim()
            if (clean.isEmpty()) return
            compactAmountPaint.color = color
            compactAmountPaint.textScaleX = 1f
            val measured = compactAmountPaint.measureText(clean)
            if (measured > 0f && measured.isFinite()) {
                compactAmountPaint.textScaleX = 114f / measured
                c.drawText(clean, center, 82f, compactAmountPaint)
            }
            compactAmountPaint.textScaleX = 1f
        }
        amount(gross.removePrefix("СТОИМОСТЬ "),60f,yellow)
        amount(net.removePrefix("НА РУКИ "),180f,green)
""" + s[b:]
# Dedicated paint prevents horizontal fitting from affecting other text.
anchor = "    override fun onDraw(c:Canvas){"
assert s.count(anchor) == 1
s = s.replace(anchor, """    private val compactAmountPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        typeface = android.graphics.Typeface.DEFAULT_BOLD
        textAlign = Paint.Align.CENTER
        textSize = 22f
    }

""" + anchor)
# Keep the existing tariff codes, not the full English names.
import re
s, count = re.subn(r'(?m)^        title=when\(tariff\)\{[^\n]+\}$', lambda m: '''        title = "Тариф " + when (tariff.trim().uppercase(java.util.Locale.ROOT)) {
            "EK", "ЕК", "ECONOMY", "ЭКОНОМ" -> "EK"
            "K", "К", "COMFORT", "КОМФОРТ" -> "K"
            "K+", "К+", "COMFORT+", "КОМФОРТ+" -> "K+"
            "EV", "ELECTRIC", "ЭЛЕКТРО" -> "EV"
            "BS", "BUSINESS", "БИЗНЕС" -> "BS"
            "PR", "PREMIER", "ПРЕМЬЕР" -> "PR"
            else -> tariff.trim()
        }''', s)
assert count == 1, "Expected original tariff title mapping"
s, count = re.subn(r'(text\(c,title,[^,\n]+,[^,\n]+,)\d+(?:\.\d+)?f', r'\g<1>22f', s)
assert count == 1, "Expected one tariff header draw call"

# Night mode retains slate. Day mode uses pale cyan and saturated dark
# lettering for high contrast (bright yellow/green would wash out on it).
anchor = "        paint.color = Color.rgb(22, 32, 39)"
assert s.count(anchor) == 1
# Only the drawing method is themed; never modify pricing or accessibility data.
a = s.index("    override fun onDraw(c:Canvas){")
b = s.index("    fun showQuote(", a)
draw = s[a:b]
draw = draw.replace("Color.WHITE", "panelInk")
draw = re.sub(r'\byellow\b', 'panelGold', draw)
draw = re.sub(r'\bgreen\b', 'panelGreen', draw)
draw = re.sub(r'\bpurple\b', 'panelPurple', draw)
draw = draw.replace(anchor, """        val nightMap = context.getSharedPreferences("taxi_profit_settings", android.content.Context.MODE_PRIVATE)
            .getBoolean("overlay_night_map", true)
        val panelInk = if (nightMap) Color.WHITE else Color.rgb(8, 34, 78)
        val panelGold = if (nightMap) yellow else Color.rgb(151, 72, 0)
        val panelGreen = if (nightMap) green else Color.rgb(0, 104, 49)
        val panelPurple = if (nightMap) Color.rgb(221, 184, 255) else Color.rgb(112, 0, 190)
        paint.color = if (nightMap) Color.rgb(72, 86, 99) else Color.rgb(186, 242, 255)""")
# Keep the yellow outline in night mode and use vivid blue in daylight.
draw = draw.replace("        paint.color = panelGold\n        c.drawRoundRect", "        paint.color = if (nightMap) yellow else Color.rgb(0, 83, 212)\n        c.drawRoundRect")
s = s[:a] + draw + s[b:]

p.write_text(s)

p = root / "RadarAccessibilityService.kt"
s = p.read_text()
assert s.count("minOf(dp(240), screenWidth())") == 1
s = s.replace("minOf(dp(240), screenWidth())", "minOf(dp(144), screenWidth())")
p.write_text(s)

p = root / "MainActivity.kt"
s = p.read_text()
anchor = "        root.addView(setupButton,LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)))"
assert s.count(anchor) == 1
s = s.replace(anchor, '''        val nightMapButton = action(if (prefs.getBoolean("overlay_night_map", true))
            "Плашка: ночной режим" else "Плашка: дневной режим") { }
        nightMapButton.setOnClickListener {
            val night = !prefs.getBoolean("overlay_night_map", true)
            prefs.edit().putBoolean("overlay_night_map", night).apply()
            nightMapButton.text = if (night) "Плашка: ночной режим" else "Плашка: дневной режим"
        }
        root.addView(nightMapButton)
''' + anchor)
p.write_text(s)
print("Compact overlay: 144dp x 57.6dp; night-map slate / day-map pale cyan; persistent manual toggle.")
