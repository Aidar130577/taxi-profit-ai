"""v52 hybrid: restore an explicitly provisional road quote, not a straight-line estimate."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
def edit(name,old,new):
    p=root/name
    s=p.read_text()
    assert s.count(old)==1,(name,old[:140],s.count(old))
    p.write_text(s.replace(old,new,1))

# Keep exact and tolerant offline lookups separate. A fuzzy result is not verified.
edit("OfflineAlmatyIndex.kt", "    private fun findExact(raw: String): BRouterConnector.Point? {",
     "    internal fun findExact(raw: String): BRouterConnector.Point? {")
edit("OfflineAlmatyIndex.kt", "    private fun findTolerant(raw: String): BRouterConnector.Point? {",
     "    internal fun findTolerant(raw: String): BRouterConnector.Point? {")
# A query hitting the SQL cap may hide a second, conflicting location.
edit("OfflineAlmatyIndex.kt", "                while (cursor.moveToNext()) {\n                    if (AddressMatcher.matchesLabel(order, cursor.getString(2)) != null) {", "                if (cursor.count >= 600) return null\n                while (cursor.moveToNext()) {\n                    if (AddressMatcher.matchesLabel(order, cursor.getString(2)) != null) {")
# Prioritize the exact house over nearby house suffixes in the tolerant index.
edit("OfflineAlmatyIndex.kt", """            val found = ArrayList<BRouterConnector.Point>()
            db.rawQuery(
                "select lat, lon, label from places where kind = 0 and key like ? and key like ? limit 600",""", """            val full = ArrayList<BRouterConnector.Point>()
            val near = ArrayList<BRouterConnector.Point>()
            db.rawQuery(
                "select lat, lon, label from places where kind = 0 and key like ? and key like ? limit 600",""")
edit("OfflineAlmatyIndex.kt", """                    if (AddressMatcher.matchesLabel(order, cursor.getString(2)) != null) {
                        found.add(BRouterConnector.Point(cursor.getInt(0) / 1_000_000.0, cursor.getInt(1) / 1_000_000.0))
                    }""", """                    val level = AddressMatcher.matchesLabel(order, cursor.getString(2)) ?: continue
                    val point = BRouterConnector.Point(cursor.getInt(0) / 1_000_000.0, cursor.getInt(1) / 1_000_000.0)
                    if (level == AddressMatcher.Level.FULL) full.add(point) else near.add(point)""")
edit("OfflineAlmatyIndex.kt", """            if (found.isEmpty()) return null
            val first = found.first()
            if (found.any { kotlin.math.abs(it.lat - first.lat) > 0.003 || kotlin.math.abs(it.lon - first.lon) > 0.004 }) {""", """            val found = full.ifEmpty { near }
            if (found.isEmpty()) return null
            val first = found.first()
            if (found.any { kotlin.math.abs(it.lat - first.lat) > 0.003 || kotlin.math.abs(it.lon - first.lon) > 0.004 }) {""")
# Preserve all strong matches, not first arbitrary POI. Narrow the cluster to ~100m.
edit("OfflineAlmatyIndex.kt", "kotlin.math.abs(it.lat - first.lat) > 0.003 || kotlin.math.abs(it.lon - first.lon) > 0.004",
     "kotlin.math.abs(it.lat - first.lat) > 0.0009 || kotlin.math.abs(it.lon - first.lon) > 0.0012")

edit("OfflineRoutePipeline.kt", '''                                if (!from.exact || !to.exact) {
                                    complete(key, Result.failure(UncertainAddressException()))
                                } else {
                                    brouter.route(from.point, to.point) { result ->
                                        complete(key, result.map { it.copy(approximate = false) })
                                    }
                                }''', '''                                brouter.route(from.point, to.point) { result ->
                                    complete(key, result.map {
                                        it.copy(approximate = it.approximate || !from.exact || !to.exact)
                                    })
                                }''')
edit("OfflineRoutePipeline.kt", '''            else offlineAlmaty.find(raw) ?: LearnedPlaces.find(appContext, raw)
        val found = offline?.let { Resolved(it, exact = true) } ?: run {''', '''            else runCatching { offlineAlmaty.findExact(raw) }.getOrNull()
                ?: LearnedPlaces.find(appContext, raw)
        val tolerant = if (offline == null) runCatching { offlineAlmaty.findTolerant(raw) }.getOrNull() else null
        val found = offline?.let { Resolved(it, exact = true) }
            ?: tolerant?.let { Resolved(it, exact = false) } ?: run {''')
edit("OfflineRoutePipeline.kt", '''            var seen = 0
            var failed = false''', '''            var seen = 0
            var failed = false
            var fallback: Resolved? = null
            var conflictingFallback = false''')
# Search query variants lazily, stop on a verified address. Keep a plausible
# old-style candidate only in the absence of contrary evidence.
edit("OfflineRoutePipeline.kt", "            val queries = PlaceLookup.queries(raw)", "            val queries = PlaceLookup.queries(raw)")
edit("OfflineRoutePipeline.kt", '''                val exact = if (named) PlaceLookup.namedMatch(queries.last(), matches) else PlaceLookup.addressMatch(raw, matches)
                val match = exact
                match?.let { candidate ->
                    val point = BRouterConnector.Point(candidate.lat, candidate.lon)
                    if (exact != null) LearnedPlaces.remember(appContext, raw, point, verified = true)
                    Resolved(point, exact != null)
                }
            }.firstOrNull { it != null }''', '''                val local = matches.filter { it.lat in 42.5..44.5 && it.lon in 75.0..79.0 }
                val exact = if (named) PlaceLookup.namedMatch(queries.last(), local) else
                    PlaceLookup.verifiedAddress(raw, local)
                val candidate = if (named) null else PlaceLookup.hybridFallback(raw, local)
                if (candidate != null) {
                    val point = BRouterConnector.Point(candidate.lat, candidate.lon)
                    val prior = fallback
                    if (prior == null) fallback = Resolved(point, exact = false)
                    else if (kotlin.math.abs(prior.point.lat - point.lat) > 0.0009 ||
                        kotlin.math.abs(prior.point.lon - point.lon) > 0.0012) conflictingFallback = true
                }
                exact?.let { confirmed ->
                    val point = BRouterConnector.Point(confirmed.lat, confirmed.lon)
                    LearnedPlaces.remember(appContext, raw, point, verified = true)
                    Resolved(point, exact = true)
                }
            }.firstOrNull { it != null } ?: fallback?.takeUnless { conflictingFallback }''')
edit("OfflineRoutePipeline.kt", '''        if (!found.exact) throw UncertainAddressException()
        synchronized(pointCache) { pointCache[norm]=found }''', '''        if (found.exact) synchronized(pointCache) { pointCache[norm]=found }
        else android.util.Log.i("ZnayTsenuRoute", "Provisional endpoint; not cached")''')
# Avoid poisoning the persistent address index from a fuzzy offline result.
# Existing observeEndpoint stores unverified GPS evidence, which v50 already
# prevents from becoming a verified routing location.

edit("PlaceLookup.kt", "    private fun normalize(text: String): String =", '''    /** Full parsed address match; tolerate case and spelling variants, never a different house. */
    fun verifiedAddress(raw: String, matches: List<Match>): Match? {
        val order = AddressMatcher.parse(raw)
        val hits = matches.filter { c -> c.labels.any { label ->
            if (order != null) AddressMatcher.matchesLabel(order, label) == AddressMatcher.Level.FULL
            else OrderTextParser.samePoint(raw, label.split(',').take(2).joinToString(",").trim())
        } }
        val first = hits.firstOrNull() ?: return null
        return first.takeIf { hits.all {
            kotlin.math.abs(it.lat - first.lat) <= 0.0009 &&
                kotlin.math.abs(it.lon - first.lon) <= 0.0012
        } }
    }

    /** Plausible fallback from the old geocoder, never a verified point. */
    fun hybridFallback(raw: String, matches: List<Match>): Match? {
        val order = AddressMatcher.parse(raw)
        val local = matches.filter { it.lat in 42.5..44.5 && it.lon in 75.0..79.0 }
        if (local.isEmpty()) return null
        fun cluster(candidates: List<Match>): Match? {
            val first = candidates.firstOrNull() ?: return null
            return first.takeIf { candidates.all {
                kotlin.math.abs(it.lat - first.lat) <= 0.0009 &&
                    kotlin.math.abs(it.lon - first.lon) <= 0.0012
            } }
        }
        if (order != null) {
            val full = local.filter { c -> c.labels.any {
                AddressMatcher.matchesLabel(order, it) == AddressMatcher.Level.FULL
            } }
            if (full.isNotEmpty()) return cluster(full)
            val near = local.filter { c -> c.labels.any {
                AddressMatcher.matchesLabel(order, it) == AddressMatcher.Level.NEAR
            } }
            if (near.isNotEmpty()) return cluster(near)
            // Do not accept an explicitly different street or house.
            if (local.any { c -> c.labels.any { AddressMatcher.parse(it) != null } }) return null
        }
        // Old-style geocoder result with unstructured labels: only a unique
        // location or a tight cluster, never distant competing candidates.
        val stem = order?.let(AddressMatcher::searchStem) ?: return null
        val digits = AddressMatcher.houseDigits(order)
        if (digits.isEmpty()) return null
        val houseNumber = Regex("(?<![0-9])" + Regex.escape(digits) + "(?![0-9])")
        val candidate = cluster(local.filter { c -> c.labels.any { label ->
            label.lowercase(java.util.Locale.ROOT).contains(stem) && houseNumber.containsMatchIn(label)
        } }) ?: return null
        // An unstructured answer cannot disambiguate a distant alternative.
        return candidate.takeIf { local.all {
            kotlin.math.abs(it.lat - candidate.lat) <= 0.0009 &&
                kotlin.math.abs(it.lon - candidate.lon) <= 0.0012
        } }
    }

    private fun normalize(text: String): String =''')

edit("RouteQuality.kt", "    fun valid(route: OfflineRoute): Boolean =",
'''    fun previewUsable(route: OfflineRoute): Boolean =
        route.approximate && !route.provisional && route.km.isFinite() &&
            route.km in 0.05..300.0 && route.minutes.isFinite() && route.minutes in 0.5..300.0 &&
            route.geometry.size >= 2

    fun valid(route: OfflineRoute): Boolean =''')

# Keep badge-based fares and confirmed adaptive quotes unchanged. A weak
# BRouter route can only supply a marked preview when a full badge is absent.
edit("RadarAccessibilityService.kt", '''                        if (!RouteQuality.valid(route) ||
                            (badgeRoute != null && !RouteQuality.comparable(badgeRoute, route))) {''',
'''                        if (badgeRoute == null && estimate == null && RouteQuality.previewUsable(route)) {
                            val preview = runCatching {
                                RouteFareEstimator.calculateWithCommission(rate, route, commonDemand, yandex, park,
                                    loyalty, newer.verifiedHighDemandDiscount, pickupExtras(newer))
                            }.getOrNull()
                            if (preview != null) {
                                estimate = preview
                                routeStatus = "Предварительно · адрес"
                                if (!loggedOffer) logForecast(newer, rate, preview, 0.0,
                                    CityWeather.condition(this, System.currentTimeMillis()), routeStatus,
                                    android.os.SystemClock.elapsedRealtime() - (offerStartedAt ?: calcStartedAt),
                                    null, true)
                                detected.trialId?.let { TrialStore.exclude(this, it) }
                                Log.i("ZnayTsenuRoute", "Provisional road quote; excluded from learning")
                                render()
                                return@submit
                            }
                        }
                        if (!RouteQuality.valid(route) ||
                            (badgeRoute != null && !RouteQuality.comparable(badgeRoute, route))) {''')

# Increase dimensions uniformly, not font sizes individually.
edit("OfferPopupView.kt", "(144 * density).toInt()", "(172.8f * density).toInt()")
edit("RadarAccessibilityService.kt", "minOf(dp(144), screenWidth())", "minOf(dp(173), screenWidth())")
edit("OfferPopupView.kt", '''    private var assumedEv = false
    private val logicalHeight get() = if (waiting) 38 else (if (hasQuote) 96 else 116) + if (assumedEv) 36 else 0''',
'''    private var assumedEv = false
    private var approximateQuote = false
    private val quoteHeight get() = if (!hasQuote || approximateQuote) 116 else 96
    private val logicalHeight get() = if (waiting) 38 else quoteHeight + if (assumedEv) 36 else 0''')
edit("OfferPopupView.kt", "        this.assumedEv = assumedEv\n",
     '''        this.assumedEv = assumedEv
        approximateQuote = estimate != null && status.startsWith("Предварительно")
''')
edit("OfferPopupView.kt", '''        if (!hasQuote) {
            line(c,92f)
            text(c,footer,120f,108f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)
        }''', '''        if (!hasQuote || approximateQuote) {
            line(c,92f)
            text(c,if (approximateQuote) "≈ Неточный адрес" else footer,120f,108f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)
        }''')
edit("OfferPopupView.kt", "            val y = if (hasQuote) 96f else 116f", "            val y = quoteHeight.toFloat()")

# The existing TomTom pilot and adaptive calculation remain unchanged.
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
a="    addressMatcherChecks()"
assert s.count(a)==1
p.write_text(s.replace(a,'''    val weak=OfflineRoute(4.0,12.0,approximate=true,geometry=listOf(RoutePoint(43.2,76.9),RoutePoint(43.3,76.9)))
    check(RouteQuality.previewUsable(weak))
    check(!RouteQuality.valid(weak))
    check(!RouteQuality.previewUsable(weak.copy(geometry=emptyList())))
    check(!RouteQuality.previewUsable(weak.copy(provisional=true)))
    check(!RouteQuality.previewUsable(weak.copy(approximate=false)))
    val requested="улица Пушкина, 83"
    val unknown=PlaceLookup.Match(43.25,76.95,listOf("83 Пушкина Алматы"))
    val wrong=PlaceLookup.Match(43.25,76.95,listOf("улица Пушкина, 38"))
    val far=PlaceLookup.Match(43.28,76.95,listOf("Алматы"))
    check(PlaceLookup.hybridFallback(requested,listOf(unknown))!=null)
    check(PlaceLookup.hybridFallback(requested,listOf(PlaceLookup.Match(43.25,76.95,listOf("Алматы"))))==null)
    check(PlaceLookup.hybridFallback(requested,listOf(wrong))==null)
    check(PlaceLookup.hybridFallback(requested,listOf(unknown,far))==null)
    check(PlaceLookup.verifiedAddress("улица Байтурсынова, 103",listOf(
        PlaceLookup.Match(43.25,76.95,listOf("улица Ахмета Байтурсынова, 103")))) != null)
    check(PlaceLookup.verifiedAddress("Жетысуская улица, 17/1",listOf(
        PlaceLookup.Match(43.25,76.95,listOf("Жетысуская улица, 17")))) == null)
    check(PlaceLookup.verifiedAddress(requested,listOf(wrong)) == null)
    check(PlaceLookup.verifiedAddress(requested,listOf(
        PlaceLookup.Match(43.25,76.95,listOf("улица Пушкина, 83")),
        PlaceLookup.Match(43.28,76.95,listOf("улица Пушкина, 83")))) == null)
    // EV field screenshot: actual address strings; synthetic coordinates only.
    val evA = "улица Алиби Жангельдина, 166"
    val evB = "улица Шарипа Омарова, 9"
    val evStart = PlaceLookup.Match(43.26,76.96,listOf("улица Алиби Жангельдина 166, Алматы"))
    val evEnd = PlaceLookup.Match(43.23,76.87,listOf("улица Шарипа Омарова, 9"))
    val evNear = PlaceLookup.Match(43.24,76.88,listOf("улица Шарипа Омарова, 9А"))
    val evWrong = PlaceLookup.Match(43.25,76.89,listOf("улица Шарипа Омарова, 90"))
    check(PlaceLookup.verifiedAddress(evA,listOf(evStart)) == evStart)
    check(PlaceLookup.verifiedAddress(evB,listOf(evNear,evWrong,evEnd)) == evEnd)
    check(PlaceLookup.verifiedAddress(evB,listOf(evNear,evWrong)) == null)
    check(PlaceLookup.verifiedAddress(evB,listOf(evEnd,evEnd.copy(lat=43.29))) == null)
    addressMatcherChecks()'''))
print("v52 hybrid geocode: separate provisional road forecast, no training, overlay +20%.")
