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
    '''                        val mixed = if (badgeQuote != null && badgeRoute != null) {
                            val gross = DualFareMean.mean(badgeQuote.gross, quote.gross)
                            val yandexParts = FareEngine.detailed(rate, RouteEstimate(badgeRoute.km, badgeRoute.minutes), demand, pickupExtras(newer))
                            val roadParts = FareEngine.detailed(rate, RouteEstimate(route.km, route.minutes), demand, pickupExtras(newer))
                            val commission = CommissionCatalog.calculate(gross, DualFareMean.mean(yandexParts.ride, roadParts.ride),
                                yandex, park, loyalty, newer.verifiedHighDemandDiscount)
                            badgeQuote.copy(gross = gross, net = commission.net, commission = commission,
                                source = "Среднее Яндекс + BRouter")
                        } else quote
                        estimate = mixed
                        routeStatus = when {
                            badgeQuote != null -> "Среднее Яндекс + BRouter"
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
s = s.replace("RouteTraceStore.savePlan(this, id, route, adjusted, quote.gross,", "RouteTraceStore.savePlan(this, id, route, adjusted, mixed.gross,")
p.write_text(s)

# Keep diagnostics on device with existing trip history (no raw address upload).
edit("LocalFareLearning.kt", "    val provisional: Boolean = false\n)", """    val provisional: Boolean = false,
    val yandexForecast: Double? = null,
    val brouterForecast: Double? = null,
    val averageForecast: Double? = null
)""")
edit("TrialStore.kt", '                    obj.optBoolean("provisional")\n', '''                    obj.optBoolean("provisional"),
                    obj.optDouble("yandexForecast").takeIf(Double::isFinite),
                    obj.optDouble("brouterForecast").takeIf(Double::isFinite),
                    obj.optDouble("averageForecast").takeIf(Double::isFinite)
''')
edit("TrialStore.kt", '            if (r.provisional) j.put("provisional", true)\n', '''            if (r.provisional) j.put("provisional", true)
            r.yandexForecast?.let { j.put("yandexForecast", it) }
            r.brouterForecast?.let { j.put("brouterForecast", it) }
            r.averageForecast?.let { j.put("averageForecast", it) }
''')
edit("TrialStore.kt", "    @Synchronized fun observeMetered(context: Context, id: Long) {", '''    @Synchronized fun compareForecasts(context: Context, id: Long, yandex: Double?, road: Double?,
                                        average: Double?, yr: OfflineRoute?, br: OfflineRoute?) {
        val rows = read(context)
        val row = rows.firstOrNull { it.id == id } ?: return
        // Never overwrite the confirmed fact. Full trip badge is kept distinct
        // from BRouter distance/time, and the blended price is not used as a measured route.
        val updated = row.copy(yandexForecast = yandex ?: row.yandexForecast,
            brouterForecast = road ?: row.brouterForecast,
            averageForecast = average ?: row.averageForecast,
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
                    row.averageForecast?.let { "Среднее " + FareEngine.kzt(it) },
                    row.averageForecast?.let { avg -> row.actualGross?.takeIf { it > 0 }?.let {
                        "Ошибка среднего " + "%+.1f".format((avg-it)*100/it) + "%"
                    } }
                ).joinToString(" · ").takeIf { it.isNotBlank() }
                val details = listOfNotNull(forecast, comparisons, gross, error, actual).joinToString(" · ")''')
(root / "DualFareMean.kt").write_text('''package kz.taxiprofitai

internal object DualFareMean {
    fun mean(a: Double, b: Double): Double {
        require(a.isFinite() && b.isFinite() && a >= 0.0 && b >= 0.0)
        return a / 2.0 + b / 2.0
    }
}
''')
p = Path("core-tests/AutoLearningCheck.kt")
s = p.read_text()
anchor = "fun main() {\n"
assert s.count(anchor) == 1
p.write_text(s.replace(anchor, anchor + '''    check(DualFareMean.mean(2360.0, 2888.0) == 2624.0)
    check(DualFareMean.mean(1000.0, 1000.0) == 1000.0)
    check(DualFareMean.mean(1150.0, 2150.0) == 1650.0)
    check(runCatching { DualFareMean.mean(Double.NaN, 1.0) }.isFailure)
'''))
print("Dual fare experiment enabled: independent reference-tariff calculations, equal weighting, local per-source comparison.")
