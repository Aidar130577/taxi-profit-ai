"""Experimental dual forecast. Both sources use the same reference tariff and extras."""
from pathlib import Path
root = Path("app/src/main/java/kz/taxiprofitai")
def edit(path, old, new):
    p = root / path
    s = p.read_text()
    assert s.count(old) == 1, (path, old[:100], s.count(old))
    p.write_text(s.replace(old, new, 1))

# Preserve direct Yandex fare and post-acceptance route selection paths.
# For an incoming offer with addresses, run BRouter even if badge is present.
edit("RadarAccessibilityService.kt",
    "} else if (newer.tripBadge != null && rate != null) {",
    "} else if (newer.tripBadge != null && rate != null && (!rememberIncoming || newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank())) {")
# Single-source Yandex is based on reference tariff, without learned time/rate changes.
edit("RadarAccessibilityService.kt",
    "val effective = profile?.rateFor(route.km) ?: rate",
    "val effective = rate")
edit("RadarAccessibilityService.kt",
    '''                    val pipeline = routePipeline ?: OfflineRoutePipeline(this).also { routePipeline = it }
                    val submit = submit@{ route: OfflineRoute ->''',
    '''                    val pipeline = routePipeline ?: OfflineRoutePipeline(this).also { routePipeline = it }
                    val badgeRoute = newer.tripBadge?.route()
                    val commonDemand = newer.demand ?: Demand(DemandType.NONE)
                    val badgeQuote = badgeRoute?.let { yr -> runCatching {
                        RouteFareEstimator.calculateWithCommission(rate, yr, commonDemand, yandex, park,
                            loyalty, newer.verifiedHighDemandDiscount, pickupExtras(newer))
                    }.getOrNull() }
                    // Show a usable Yandex estimate without waiting for road routing.
                    if (badgeQuote != null && badgeRoute != null) {
                        estimate = badgeQuote
                        routeStatus = "Время Яндекс Про"
                        if (!loggedOffer) logForecast(newer, rate, badgeQuote, 0.0,
                            CityWeather.condition(this, System.currentTimeMillis()), badgeRoute.source,
                            android.os.SystemClock.elapsedRealtime() - (offerStartedAt ?: calcStartedAt))
                        detected.trialId?.let { TrialStore.compareForecasts(this, it, badgeQuote.gross, null, null, badgeRoute, null) }
                    }
                    val submit = submit@{ route: OfflineRoute ->''')
# Use unmodified BRouter route and the same tariff as the Yandex calculation.
edit("RadarAccessibilityService.kt",
    '''                        val adjusted = if (route.provisional) route else {
                            val km = RideTimeLearning.distance(route.km, history, now)
                            val distance = route.copy(km = km)
                            distance.copy(minutes = RideTimeLearning.estimate(distance, history, now, weather))
                        }
                        val profile = learnedProfile(rate, history, now)
                        val effective = profile?.rateFor(adjusted.km) ?: rate''',
    '''                        val adjusted = route
                        val profile: LearnedRates.Profile? = null
                        val effective = rate''')
edit("RadarAccessibilityService.kt",
    '''                        estimate = quote
                        routeStatus = when {
                            route.provisional''',
    '''                        val combinedRoute = if (badgeQuote != null && badgeRoute != null)
                            DualFareMean.combinedRoute(badgeRoute, route) else null
                        val mixed = combinedRoute?.let { hybrid ->
                            RouteFareEstimator.calculateWithCommission(rate, hybrid, demand, yandex, park,
                                loyalty, newer.verifiedHighDemandDiscount, pickupExtras(newer))
                        } ?: quote
                        estimate = mixed
                        routeStatus = when {
                            badgeQuote != null -> "Км Яндекса · среднее время"
                            route.provisional''')
# Keep first quote for latency and audit, store the actual blended forecast separately.
p = root / "RadarAccessibilityService.kt"
s = p.read_text()
anchor = '''                        if (!route.provisional && loggedOffer && route.geometry.size >= 2) {'''
assert s.count(anchor) == 1
s = s.replace(anchor, '''                        detected.trialId?.let { id ->
                            TrialStore.compareForecasts(this, id, badgeQuote?.gross, quote.gross,
                                mixed.gross.takeIf { badgeQuote != null }, badgeRoute, route)
                        }
''' + anchor)
# Trace should show the actually presented price, not just road price.
s = s.replace("RouteTraceStore.savePlan(this, id, route, adjusted, quote.gross,", "RouteTraceStore.savePlan(this, id, route, combinedRoute ?: adjusted, mixed.gross,")
p.write_text(s)

# Keep diagnostics on device with existing trip history (no raw address upload).
edit("LocalFareLearning.kt", "    val provisional: Boolean = false\n)", """    val provisional: Boolean = false,
    val yandexForecast: Double? = null,
    val brouterForecast: Double? = null,
    val combinedForecast: Double? = null,
    val initialBadgeKm: Double? = null,
    val initialBadgeMinutes: Double? = null,
    val combinedMinutes: Double? = null
)""")
edit("TrialStore.kt", '                    obj.optBoolean("provisional")\n', '''                    obj.optBoolean("provisional"),
                    obj.optDouble("yandexForecast").takeIf(Double::isFinite),
                    obj.optDouble("brouterForecast").takeIf(Double::isFinite),
                    obj.optDouble("combinedForecast").takeIf(Double::isFinite),
                    obj.optDouble("initialBadgeKm").takeIf(Double::isFinite),
                    obj.optDouble("initialBadgeMinutes").takeIf(Double::isFinite),
                    obj.optDouble("combinedMinutes").takeIf(Double::isFinite)
''')
edit("TrialStore.kt", '            if (r.provisional) j.put("provisional", true)\n', '''            if (r.provisional) j.put("provisional", true)
            r.yandexForecast?.let { j.put("yandexForecast", it) }
            r.brouterForecast?.let { j.put("brouterForecast", it) }
            r.combinedForecast?.let { j.put("combinedForecast", it) }
            r.initialBadgeKm?.let { j.put("initialBadgeKm", it) }
            r.initialBadgeMinutes?.let { j.put("initialBadgeMinutes", it) }
            r.combinedMinutes?.let { j.put("combinedMinutes", it) }
''')
edit("TrialStore.kt", "    @Synchronized fun observeMetered(context: Context, id: Long) {", '''    @Synchronized fun compareForecasts(context: Context, id: Long, yandex: Double?, road: Double?,
                                        combined: Double?, yr: OfflineRoute?, br: OfflineRoute?) {
        val rows = read(context)
        val row = rows.firstOrNull { it.id == id } ?: return
        // Never overwrite the confirmed fact. Full trip badge is kept distinct
        // from BRouter distance/time, and the blended price is not used as a measured route.
        val updated = row.copy(yandexForecast = yandex ?: row.yandexForecast,
            brouterForecast = road ?: row.brouterForecast,
            combinedForecast = combined ?: row.combinedForecast,
            initialBadgeKm = row.initialBadgeKm ?: yr?.km,
            initialBadgeMinutes = row.initialBadgeMinutes ?: yr?.minutes,
            combinedMinutes = if (combined != null && yr != null && br != null) DualFareMean.mean(yr.minutes, br.minutes) else row.combinedMinutes,
            routeKm = yr?.km ?: row.routeKm,
            routeMinutes = yr?.minutes ?: row.routeMinutes,
            offlineKm = br?.km ?: row.offlineKm,
            offlineMinutes = br?.minutes ?: row.offlineMinutes)
        if (updated != row) write(context, rows.map { if (it.id == id) updated else it })
    }

    @Synchronized fun observeMetered(context: Context, id: Long) {''')
edit("MainActivity.kt",
    '                val details = listOfNotNull(forecast, gross, error, actual).joinToString(" · ")',
    '''                val comparisons = listOfNotNull(
                    row.yandexForecast?.let { "Яндекс расчёт " + FareEngine.kzt(it) },
                    row.brouterForecast?.let { "BRouter " + FareEngine.kzt(it) },
                    row.combinedForecast?.let { "Комбинированный " + FareEngine.kzt(it) },
                    row.initialBadgeMinutes?.let { "Яндекс %.1f мин".format(it) },
                    row.offlineMinutes?.takeIf { it > 0 }?.let { "BRouter %.1f мин".format(it) },
                    row.combinedMinutes?.let { "Среднее время %.1f мин".format(it) },
                    row.combinedForecast?.let { avg -> row.actualGross?.takeIf { it > 0 }?.let {
                        "Ошибка комбинированного " + "%+.1f".format((avg-it)*100/it) + "%"
                    } }
                ).joinToString(" · ").takeIf { it.isNotBlank() }
                val details = listOfNotNull(forecast, comparisons, gross, error, actual).joinToString(" · ")''')
(root / "DualFareMean.kt").write_text('''package kz.taxiprofitai

internal object DualFareMean {
    fun mean(a: Double, b: Double): Double {
        require(a.isFinite() && b.isFinite() && a >= 0.0 && b >= 0.0)
        return a / 2.0 + b / 2.0
    }
    fun combinedRoute(yandex: OfflineRoute, road: OfflineRoute): OfflineRoute {
        require(!yandex.provisional && !road.provisional && yandex.km.isFinite() && yandex.km > 0.0)
        return yandex.copy(minutes = mean(yandex.minutes, road.minutes), source = "Км Яндекса · среднее время")
    }
}
''')
p = Path("core-tests/AutoLearningCheck.kt")
s = p.read_text()
anchor = "fun main() {\n"
assert s.count(anchor) == 1
p.write_text(s.replace(anchor, anchor + '''    val hybrid = DualFareMean.combinedRoute(OfflineRoute(12.0, 80.0), OfflineRoute(15.0, 61.0))
    check(hybrid.km == 12.0 && hybrid.minutes == 70.5)
    check(DualFareMean.combinedRoute(OfflineRoute(3.0, 7.0), OfflineRoute(4.0, 5.0)).minutes == 6.0)
    check(runCatching { DualFareMean.combinedRoute(OfflineRoute(3.0, 7.0), OfflineRoute(4.0, 5.0, provisional = true)) }.isFailure)
    check(runCatching { DualFareMean.mean(Double.NaN, 1.0) }.isFailure)
'''))
print("Hybrid fare experiment: Yandex distance, mean of Yandex and BRouter minutes, same reference tariff, local per-source comparison.")
