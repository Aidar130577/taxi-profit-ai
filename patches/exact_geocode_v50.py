"""P0: never route or learn from a first-match, unconfirmed geocode."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p=root/name
    s=p.read_text()
    assert s.count(old)==1,(name,old[:120],s.count(old))
    p.write_text(s.replace(old,new,1))

edit("BRouterRouteResult.kt", '    val requestedB: RoutePoint? = null)', '''    val requestedB: RoutePoint? = null,
    val approximate: Boolean = false)''')

# No fallback to a random first result, even if the input is not a POI.
edit("OfflineRoutePipeline.kt", 'val match = exact ?: matches.firstOrNull().takeUnless { named }', 'val match = exact')
edit("OfflineRoutePipeline.kt", '?: error(if (named) "Место не найдено однозначно" else "Не удалось найти адрес: $raw")', '?: throw UncertainAddressException()')
edit("OfflineRoutePipeline.kt", '        synchronized(pointCache) { pointCache[norm]=found }', '''        if (!found.exact) throw UncertainAddressException()
        synchronized(pointCache) { pointCache[norm]=found }''')
edit("OfflineRoutePipeline.kt", '                                brouter.route(from.point, to.point) { complete(key, it) }', '''                                if (!from.exact || !to.exact) {
                                    complete(key, Result.failure(UncertainAddressException()))
                                } else {
                                    brouter.route(from.point, to.point) { result ->
                                        complete(key, result.map { it.copy(approximate = false) })
                                    }
                                }''')
# GPS-learned points are not authoritative unless an exact lookup verified them.
# Old entries do not carry this provenance; retain them for local diagnostics, not routing.
edit("LearnedPlaces.kt", '            .put("count", evidence).put("date", System.currentTimeMillis())', '''            .put("count", evidence).put("date", System.currentTimeMillis())
            .put("verified", verified)''')
edit("LearnedPlaces.kt", '            ?.takeIf { it.count >= 2 }?.point', '            ?.takeIf { it.count >= 2 && it.verified }?.point')
edit("LearnedPlaces.kt", 'private data class Entry(val point: BRouterConnector.Point, val count: Int, val date: Long)', 'private data class Entry(val point: BRouterConnector.Point, val count: Int, val date: Long, val verified: Boolean)')
edit("LearnedPlaces.kt", 'json.getInt("count"), json.getLong("date"))', 'json.getInt("count"), json.getLong("date"), json.optBoolean("verified", false))')
edit("OfflineRoutePipeline.kt", '        result.onSuccess { route -> synchronized(routeCache) { routeCache[key] = System.currentTimeMillis() to route } }', '''        result.onSuccess { route ->
            if (!route.approximate && !route.provisional)
                synchronized(routeCache) { routeCache[key] = System.currentTimeMillis() to route }
        }''')

(root/"RouteQuality.kt").write_text('''package kz.taxiprofitai

internal class UncertainAddressException : IllegalArgumentException("Уточните адрес")

internal object RouteQuality {
    const val MAX_DISTANCE_GAP = 0.25
    fun valid(route: OfflineRoute): Boolean =
        !route.approximate && !route.provisional &&
            route.km.isFinite() && route.km > 0.0 &&
            route.minutes.isFinite() && route.minutes > 0.0

    // Yandex passenger-route distance is the reference, never the pickup distance.
    fun comparable(yandex: OfflineRoute, road: OfflineRoute): Boolean {
        if (!valid(yandex) || !valid(road)) return false
        return kotlin.math.abs(road.km - yandex.km) / yandex.km <= MAX_DISTANCE_GAP
    }
}
''')
edit("DualFareMean.kt", '        require(!yandex.provisional && !road.provisional && yandex.km.isFinite() && yandex.km > 0.0)', '''        require(RouteQuality.comparable(yandex, road)) { "Несопоставимые маршруты" }''')
# Validated badge price remains available; never use rejected route metrics.
edit("RadarAccessibilityService.kt", 'val badgeRoute = newer.tripBadge?.route()', 'val badgeRoute = newer.tripBadge?.route()?.takeIf(RouteQuality::valid)')
edit("RadarAccessibilityService.kt", '''                        if (route.provisional) {
                            estimate = null
                            routeStatus = "Нет маршрута BRouter"
                            render()
                            return@submit
                        }''', '''                        if (!RouteQuality.valid(route) ||
                            (badgeRoute != null && !RouteQuality.comparable(badgeRoute, route))) {
                            detected.trialId?.let { TrialStore.exclude(this, it) }
                            estimate = badgeQuote
                            routeStatus = if (route.approximate) "Уточните адрес" else
                                if (badgeQuote != null) "Время Яндекс Про" else "Нет маршрута BRouter"
                            Log.w("ZnayTsenuRoute", "BRouter rejected: invalid or distance gap > 25%")
                            render()
                            return@submit
                        }''')
edit("RadarAccessibilityService.kt", '''                            if (estimate == null) {
                                routeStatus = when {
                                    result.exceptionOrNull()?.message == "Место не найдено однозначно" -> "Уточните название места"
                                    result.exceptionOrNull()?.message?.startsWith("Не удалось найти адрес") == true -> "Адрес не найден на карте"
                                    else -> "Нет маршрута BRouter"
                                }
                                render()
                            }''', '''                            val failure = result.exceptionOrNull()
                            val uncertain = failure is UncertainAddressException ||
                                failure?.message == "Место не найдено однозначно" ||
                                failure?.message?.startsWith("Не удалось найти адрес") == true
                            if (uncertain) {
                                detected.trialId?.let { TrialStore.exclude(this, it) }
                                estimate = badgeQuote
                                routeStatus = if (badgeQuote == null) "Уточните адрес" else "Время Яндекс Про"
                                Log.w("ZnayTsenuRoute", "Address rejected: no confirmed unique point")
                                render()
                            } else if (estimate == null) {
                                routeStatus = "Нет маршрута BRouter"
                                Log.w("ZnayTsenuRoute", "Routing failed: " + (failure?.javaClass?.simpleName ?: "unknown"))
                                render()
                            }''')
edit("OfferPopupView.kt", 'status.startsWith("Адрес не найден") || status == "Уточните название места" -> status', 'status.startsWith("Адрес не найден") || status == "Уточните название места" || status == "Уточните адрес" -> status')
# Never print OCR text, raw coordinates, or exception messages containing user data.
edit("WindowOcr.kt", 'catch (_: Exception) {} catch (_: LinkageError) {}', '''catch (e: Exception) {
                    android.util.Log.w("ZnayTsenuOCR", "Prepare failed: " + e.javaClass.simpleName)
                } catch (e: LinkageError) {
                    android.util.Log.w("ZnayTsenuOCR", "Prepare linkage failed: " + e.javaClass.simpleName)
                }''')
edit("WindowOcr.kt", 'catch(e:Exception){}catch(e:LinkageError){}', '''catch(e:Exception){
                    android.util.Log.w("ZnayTsenuOCR", "Recognition failed: " + e.javaClass.simpleName)
                }catch(e:LinkageError){
                    android.util.Log.w("ZnayTsenuOCR", "Recognition linkage failed: " + e.javaClass.simpleName)
                }''')

# Keep original comparison tests only for comparable routes.
p=Path("core-tests/AutoLearningCheck.kt")
s=p.read_text()
s=s.replace('OfflineRoute(4.0, 5.0), 499.0','OfflineRoute(3.5, 5.0), 499.0')
p.write_text(s)
p=Path("core-tests/RouteQualityCheck.kt")
p.write_text('''package kz.taxiprofitai
fun main() {
    val y=OfflineRoute(10.0,20.0)
    check(RouteQuality.valid(y))
    check(RouteQuality.comparable(y, OfflineRoute(12.5,22.0)))
    check(RouteQuality.comparable(y, OfflineRoute(7.5,15.0)))
    check(!RouteQuality.comparable(y, OfflineRoute(12.51,22.0)))
    check(!RouteQuality.comparable(y, OfflineRoute(7.49,15.0)))
    check(!RouteQuality.comparable(y, OfflineRoute(10.0,20.0,approximate=true)))
    check(!RouteQuality.comparable(y, OfflineRoute(10.0,20.0,provisional=true)))
    check(!RouteQuality.valid(OfflineRoute(Double.NaN,20.0)))
    check(!RouteQuality.valid(OfflineRoute(10.0,0.0)))
    check(runCatching { DualFareMean.combinedRoute(y,OfflineRoute(14.0,22.0)) }.isFailure)
    check(runCatching { DualFareMean.combinedRoute(y,OfflineRoute(10.0,22.0,approximate=true)) }.isFailure)
    println("Route quality checks passed")
}
''')
print("v50 strict geocoding, route comparison, safe diagnostics applied.")
