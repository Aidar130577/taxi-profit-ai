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
s = s[:a] + "    private val logicalHeight get() = if (waiting) 38 else if (hasQuote) 82 else 104" + s[b:]
a = s.index("        line(c,78f)")
b = s.index("        c.restore()", a)
s = s[:a] + """        // Show a short explanation only while a usable fare is unavailable.
        if (!hasQuote) {
            line(c,78f)
            text(c,footer,120f,96f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)
        }
""" + s[b:]
# Width is specified in the window and also in the view's measurement.
assert s.count("(240 * density).toInt()") == 1
s = s.replace("(240 * density).toInt()", "(192 * density).toInt()")
assert "if (logicalHeight != oldHeight) requestLayout()" in s
assert s.index("hasQuote = estimate != null") < s.index("if (logicalHeight != oldHeight) requestLayout()")
p.write_text(s)

p = root / "RadarAccessibilityService.kt"
s = p.read_text()
assert s.count("minOf(dp(240), screenWidth())") == 1
s = s.replace("minOf(dp(240), screenWidth())", "minOf(dp(192), screenWidth())")
p.write_text(s)
print("Compact overlay: 192dp wide, 65.6dp fare height, 30.4dp waiting height; status only for missing fare.")
