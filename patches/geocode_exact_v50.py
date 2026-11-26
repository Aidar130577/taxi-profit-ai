"""v50: never price from a guessed geocoder point; guard against gross route mismatch; log OCR failures.

Root cause (ZC-002/ZC-009): OfflineRoutePipeline.resolve() falls back to the first Android Geocoder
result when no exact match exists. The 'exact' flag was computed and then dropped, so a route built on
a guess was priced like a verified one. Run from the android-project directory after tomtom_pilot_v49.py.
"""
from pathlib import Path

root = Path("app/src/main/java/kz/taxiprofitai")


def edit(path, old, new):
    s = path.read_text()
    assert s.count(old) == 1, f"{path.name}: expected exactly one match for: {old[:90]!r}"
    path.write_text(s.replace(old, new, 1))


# 1. The route carries an 'approximate' flag (appended last, default false: all existing call sites stay valid).
edit(root / "BRouterRouteResult.kt",
     "    val requestedB: RoutePoint? = null)",
     "    val requestedB: RoutePoint? = null,\n    val approximate: Boolean = false)")

# 2. The pipeline marks a route approximate when either endpoint was not an exact match.
edit(root / "OfflineRoutePipeline.kt",
     "brouter.route(from.point, to.point) { complete(key, it) }",
     "brouter.route(from.point, to.point) { routed ->\n"
     "                                    complete(key, routed.map { r ->\n"
     "                                        if (from.exact && to.exact) r else r.copy(approximate = true)\n"
     "                                    })\n"
     "                                }")

# 3. Pure-JVM guard so the rule is unit-testable in CI without Android.
(root / "RouteSanity.kt").write_text('''package kz.taxiprofitai

/** Gross-error guard between the Yandex trip distance and the independent road route. */
internal object RouteSanity {
    /** Provisional threshold: rejects only gross mismatches (wrong geocoder point), not routing-style differences. */
    const val MAX_DISTANCE_RATIO = 1.5

    fun consistent(yandexKm: Double, roadKm: Double): Boolean {
        if (!yandexKm.isFinite() || !roadKm.isFinite() || yandexKm <= 0.0 || roadKm <= 0.0) return false
        val ratio = roadKm / yandexKm
        return ratio <= MAX_DISTANCE_RATIO && ratio >= 1.0 / MAX_DISTANCE_RATIO
    }
}
''')

# 4. The overlay: approximate or grossly inconsistent road routes never produce, replace or train a price.
edit(root / "RadarAccessibilityService.kt",
     "                        val observedDemand = newer.demand\n",
     "                        if (route.approximate) {\n"
     "                            // Geocoder guess, not an exact address: keep any Yandex-only price, never price or learn from it.\n"
     "                            if (estimate == null) routeStatus = \"Уточните адрес\"\n"
     "                            render()\n"
     "                            return@submit\n"
     "                        }\n"
     "                        if (badgeRoute != null && !RouteSanity.consistent(badgeRoute.km, route.km)) {\n"
     "                            android.util.Log.w(\"ZnayTsenuService\", \"Road route rejected: yandexKm=${badgeRoute.km} roadKm=${route.km}\")\n"
     "                            routeStatus = \"Время Яндекс Про · маршрут BRouter не совпал\"\n"
     "                            render()\n"
     "                            return@submit\n"
     "                        }\n"
     "                        val observedDemand = newer.demand\n")

# 5. OCR failures were swallowed silently; log the exception class only (no text, no addresses).
edit(root / "WindowOcr.kt",
     "try { engine(badgeOnly = true) } catch (_: Exception) {} catch (_: LinkageError) {}",
     "try { engine(badgeOnly = true) } catch (e: Exception) { android.util.Log.w(\"ZnayTsenuOcr\", \"badge OCR failed: ${e.javaClass.simpleName}\") } catch (e: LinkageError) { android.util.Log.w(\"ZnayTsenuOcr\", \"OCR engine unavailable: ${e.javaClass.simpleName}\") }")
edit(root / "WindowOcr.kt",
     "}catch(e:Exception){}catch(e:LinkageError){}",
     "}catch(e:Exception){android.util.Log.w(\"ZnayTsenuOcr\",\"OCR failed: ${e.javaClass.simpleName}\")}catch(e:LinkageError){android.util.Log.w(\"ZnayTsenuOcr\",\"OCR engine unavailable: ${e.javaClass.simpleName}\")}")

# 6. Unit check for the guard (compiled and run by CI together with the other pure-JVM checks).
Path("core-tests").mkdir(exist_ok=True)
Path("core-tests/RouteSanityCheck.kt").write_text('''package kz.taxiprofitai

fun main() {
    fun check(ok: Boolean, name: String) { if (!ok) { System.err.println("FAIL: $name"); kotlin.system.exitProcess(1) } }
    check(RouteSanity.consistent(12.0, 14.0), "similar distances accepted")
    check(RouteSanity.consistent(12.0, 18.0), "ratio exactly 1.5 accepted")
    check(RouteSanity.consistent(18.0, 12.0), "ratio exactly 1/1.5 accepted")
    check(!RouteSanity.consistent(12.0, 18.5), "road much longer rejected")
    check(!RouteSanity.consistent(12.0, 7.0), "road much shorter rejected")
    check(!RouteSanity.consistent(0.0, 5.0), "zero Yandex distance rejected")
    check(!RouteSanity.consistent(12.0, Double.NaN), "NaN rejected")
    check(!RouteSanity.consistent(Double.POSITIVE_INFINITY, 5.0), "infinity rejected")
    val base = OfflineRoute(5.0, 10.0)
    check(!base.approximate, "approximate defaults to false")
    check(base.copy(approximate = true).approximate, "approximate can be set")
    println("OK route sanity / approximate flag checks")
}
''')
print("Geocode exactness guard v50 applied: approximate routes never price, gross route mismatch rejected, OCR errors logged.")
