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

# Unknown passenger orders: hide EV proxy, display a broad experimental range.
# Exact prices from the order itself always keep priority. No official Fasten
# tariff is assumed; the initial +/-20% band is explicitly uncalibrated.
p=root/"RouteQuality.kt"
p.write_text(p.read_text()+'''
internal object UnknownPassengerRange {
    fun format(value: Double): String {
        require(value.isFinite() && value >= 0.0)
        val low = (kotlin.math.floor(value * 0.8 / 50.0) * 50.0).toLong()
        val high = (kotlin.math.ceil(value * 1.2 / 50.0) * 50.0).toLong()
        return "$low–$high"
    }
}
''')
edit("OfferPopupView.kt", '        demandText = demand.filterNot { it == \'₸\' || it.isWhitespace() || Character.isSpaceChar(it) }',
     '''        if (assumedEv) title = "Fasten / корп."
        demandText = demand.filterNot { it == '₸' || it.isWhitespace() || Character.isSpaceChar(it) }''')
edit("OfferPopupView.kt", '''        net="НА РУКИ ${quote.takeHomeText}"''', '''        net="НА РУКИ ${quote.takeHomeText}"
        if (assumedEv && estimate != null && !estimate.fromOrder) {
            gross = "СТОИМОСТЬ " + UnknownPassengerRange.format(estimate.gross)
            net = "НА РУКИ " + (estimate.net?.let(UnknownPassengerRange::format) ?: "—")
        }''')
edit("OfferPopupView.kt", '''            text(c,"Возможно корпоративный",120f,y+15f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)
            text(c,"или Fasten",120f,y+30f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)''', '''            text(c,"Fasten / корпоративный",120f,y+15f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)
            text(c,if (hasQuote) "Цена или оценка по маршруту" else "Тариф не указан",120f,y+30f,13f,Color.WHITE,false,Paint.Align.CENTER,228f)''')
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
    check(UnknownPassengerRange.format(4000.0) == "3200–4800")
    check(UnknownPassengerRange.format(1001.0) == "800–1250")
    check(UnknownPassengerRange.format(0.0) == "0–0")
    check(runCatching { UnknownPassengerRange.format(Double.NaN) }.isFailure)
    addressMatcherChecks()'''))
print("v52 hybrid geocode: separate provisional road forecast, no training, overlay +20%.")


# v53 card-first: preserve exact text read from the offer, never derive addresses
# from map markers/driver coordinates. Use full Yandex metrics for hidden stops.
edit("Engine.kt", "val assumedEv: Boolean = false)", "val assumedEv: Boolean = false, val hiddenStops: Boolean = false)")
edit("Engine.kt", "    private fun isRouteLine(line: String): Boolean =",
r'''    private val stopCount = Regex("""(?iu)^\s*\d+\s+останов(?:ка|ки|ок)\b.*$""")
    private fun isRouteLine(line: String): Boolean =''')
edit("Engine.kt", "        !offerMetadata.containsMatchIn(line) && !driverLocation.containsMatchIn(line) &&",
'''        !stopCount.matches(line) && !offerMetadata.containsMatchIn(line) && !driverLocation.containsMatchIn(line) &&''')
edit("Engine.kt", 'assumedEv = isOrder && !unsupported && explicitTariff == null && tariff == "Электро")',
'''assumedEv = isOrder && !unsupported && explicitTariff == null && tariff == "Электро",
            hiddenStops = isOrder && addresses.take(acceptIndex.coerceAtLeast(0)).any(stopCount::matches))''')
# An isolated card may be incomplete: prefer a complete enclosing card over it.
edit("RadarAccessibilityService.kt", "if (depth > 0 && card == null && texts.size - start >= 3 && rootBounds.height() > 0) {",
     "if (depth > 0 && texts.size - start >= 3 && rootBounds.height() > 0) {")
edit("RadarAccessibilityService.kt", "                    if (candidate.order) card = candidate",
'''                    fun coverage(o: OrderTextParser.Detected?) =
                        (if (o?.pickup != null) 1 else 0) + (if (o?.destination != null) 1 else 0)
                    if (candidate.order && (card == null || coverage(candidate) > coverage(card))) card = candidate''')
# Keep all card tariff, addresses and extras, and only take the map measurement
# from the screen. A card-only parse can intentionally have no trip badge.
edit("RadarAccessibilityService.kt", '''            isolatedCard != null && screen.order -> screen.copy(
                pickup = isolatedCard.pickup, destination = isolatedCard.destination)''',
'''            isolatedCard != null && screen.order -> isolatedCard.copy(
                tripBadge = screen.tripBadge, demand = isolatedCard.demand ?: screen.demand)''')
# Recalculate when stop information changes; do not treat 2 unknown stop
# locations as a complete A-to-B route.
edit("RadarAccessibilityService.kt", 'val key="${newer.pickup}|${newer.destination}|${newer.tariff}|',
     'val key="${newer.hiddenStops}|${newer.pickup}|${newer.destination}|${newer.tariff}|')
edit("RadarAccessibilityService.kt", '(!rememberIncoming || newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank())) {',
     '(!rememberIncoming || newer.hiddenStops || newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank())) {')
edit("RadarAccessibilityService.kt", '''                } else if (newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank() || rate == null) {''',
'''                } else if (newer.hiddenStops) {
                    routeStatus = "Не считаны остановки"
                } else if (newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank() || rate == null) {''')
edit("OfferPopupView.kt", 'status.startsWith("Уточните адрес") -> status',
     'status.startsWith("Уточните адрес") || status == "Не считаны остановки" -> status')
# Distinguish card extraction from routing in privacy-preserving logs.
edit("RadarAccessibilityService.kt", '                    val calcStartedAt = android.os.SystemClock.elapsedRealtime()',
'''                    Log.i("ZnayTsenuRoute", "Card addresses present; geocoding started")
                    val calcStartedAt = android.os.SystemClock.elapsedRealtime()''')
edit("RadarAccessibilityService.kt", '                    val submit = submit@{ route: OfflineRoute ->',
'''                    val submit = submit@{ route: OfflineRoute ->
                        Log.i("ZnayTsenuRoute", "Road route received; validating fare inputs")''')
# Keep stop information and explicit tariff when OCR supplements native text.
edit("RadarAccessibilityService.kt", '                    tariff = original.tariff ?: candidate.tariff,',
'''                    tariff = if (original.assumedEv && !candidate.assumedEv && candidate.tariff != null)
                        candidate.tariff else original.tariff ?: candidate.tariff,
                    hiddenStops = original.hiddenStops || candidate.hiddenStops,
                    assumedEv = if (original.tariff == null) candidate.assumedEv else
                        original.assumedEv && (candidate.tariff == null || candidate.assumedEv),''')
edit("RadarAccessibilityService.kt", 'if(original.tariff!=null && original.tariff!=merged.tariff)return@post',
     'if(original.tariff!=null && !original.assumedEv && original.tariff!=merged.tariff)return@post')
edit("RadarAccessibilityService.kt", 'if(detected.order && detected.tariff!=null && detected.tariff!=merged.tariff)return@post',
     'if(detected.order && detected.tariff!=null && !detected.assumedEv && detected.tariff!=merged.tariff)return@post')
# Regression tests from the two field screenshots (literal text, no fabricated route).
p=Path("core-tests/OfferDemandCheck.kt")
s=p.read_text()
import re
m=re.search(r'(?m)^fun main\s*\([^)]*\)\s*\{',s)
assert m is not None
a=m.group(0)
# Kotlin literals in generated source need escaped newlines.
checks=r'''
    val fieldEv = OrderTextParser.parse("Пропустить\n3,1 км · 6 мин\nДальняя подача\nЭлектро\nА: улица Алиби Жангельдина, 166\nБ: улица Шарипа Омарова, 9\nПассажир\nПринять +100 ₸", cardOnly = true)
    check(fieldEv.pickup == "улица Алиби Жангельдина, 166")
    check(fieldEv.destination == "улица Шарипа Омарова, 9")
    check(fieldEv.tariff == "Электро" && !fieldEv.assumedEv && !fieldEv.hiddenStops)
    check(fieldEv.tripBadge == null && fieldEv.pickupKm == 3.1)
    val fieldFasten = OrderTextParser.parse("Пропустить\nБ 27 км 45 мин\n800 м · 3 мин\nБлижняя подача\nА: улица Абдуллы Розыбакиева, 247А\n2 остановки\nБ: проспект Назарбаева, 179\nПассажир\nПринять ×1.00")
    check(fieldFasten.pickup == "улица Абдуллы Розыбакиева, 247А")
    check(fieldFasten.destination == "проспект Назарбаева, 179")
    check(fieldFasten.assumedEv && fieldFasten.hiddenStops)
    check(fieldFasten.tripBadge == TripBadge(27.0,45))
    check(fieldFasten.pickupKm == 0.8)
'''
p.write_text(s.replace(a,a+checks,1))
print("Card-first and hidden-stop regressions applied.")


# Owner 27 Nov: unknown passenger orders use Comfort / Comfort+ bounds.
# assumedEv remains solely a legacy unknown-class compatibility flag.
edit("Engine.kt", "val fromOrder: Boolean = false)", 
     "val fromOrder: Boolean = false, val upperGross: Double? = null, val upperNet: Double? = null)")
edit("RadarAccessibilityService.kt", "val rate = TarifCatalog.forName(newer.tariff)",
     'val rate = TarifCatalog.forName(if (newer.assumedEv) "Комфорт" else newer.tariff)')
edit("RadarAccessibilityService.kt", "                val shown = newer.displayedGross",
'''                fun quoteFor(reference: TariffRate, route: OfflineRoute, demand: Demand): LiveFareEstimate {
                    val lower = RouteFareEstimator.calculateWithCommission(reference, route, demand, yandex, park,
                        loyalty, newer.verifiedHighDemandDiscount, pickupExtras(newer))
                    if (!newer.assumedEv) return lower
                    val upperRate = requireNotNull(TarifCatalog.forName("Комфорт+"))
                    val upper = RouteFareEstimator.calculateWithCommission(upperRate, route, demand,
                        CommissionSettings.percent(prefs, upperRate.title), park,
                        loyalty, newer.verifiedHighDemandDiscount, pickupExtras(newer))
                    return lower.copy(upperGross = upper.gross, upperNet = upper.net)
                }
                val shown = newer.displayedGross''')
p=root/"RadarAccessibilityService.kt"
s=p.read_text()
import re
pattern=r'RouteFareEstimator\.calculateWithCommission\((effective|rate),\s*(route|yr|adjusted|hybrid),\s*(demand|commonDemand),\s*yandex,\s*park,\s*loyalty,\s*newer\.verifiedHighDemandDiscount,\s*pickupExtras\(newer\)\)'
s,n=re.subn(pattern,r'quoteFor(\1, \2, \3)',s)
assert n==5,("fare paths",n)
p.write_text(s)
edit("OfferPopupView.kt", '''            gross = "СТОИМОСТЬ " + UnknownPassengerRange.format(estimate.gross)
            net = "НА РУКИ " + (estimate.net?.let(UnknownPassengerRange::format) ?: "—")''',
'''            gross = "СТОИМОСТЬ " + UnknownPassengerRange.bounds(estimate.gross, estimate.upperGross)
            net = "НА РУКИ " + UnknownPassengerRange.bounds(estimate.net, estimate.upperNet)''')
edit("OfferPopupView.kt", 'if (assumedEv) title = "Fasten / корп."', 'if (assumedEv) title = "Тариф не указан"')
edit("OfferPopupView.kt", 'text(c,"Fasten / корпоративный",120f,y+15f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)',
     'text(c,"Возможно корпоративный",120f,y+15f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)')
edit("OfferPopupView.kt", 'text(c,if (hasQuote) "Цена или оценка по маршруту" else "Тариф не указан",120f,y+30f,13f,Color.WHITE,false,Paint.Align.CENTER,228f)',
     'text(c,"или Fasten",120f,y+30f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)')
p=root/"RouteQuality.kt"
s=p.read_text()
a=s.index("internal object UnknownPassengerRange {")
s=s[:a]+'''internal object UnknownPassengerRange {
    fun bounds(a: Double?, b: Double?): String {
        if (a == null || b == null || !a.isFinite() || !b.isFinite() || a < 0 || b < 0) return "—"
        val low = kotlin.math.round(minOf(a,b)).toLong()
        val high = kotlin.math.round(maxOf(a,b)).toLong()
        return "$low–$high"
    }
}
'''
p.write_text(s)
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
a=s.index("    check(UnknownPassengerRange.format(4000.0)")
b=s.index("    addressMatcherChecks()",a)
s=s[:a]+'''    check(UnknownPassengerRange.bounds(3000.0,3500.0) == "3000–3500")
    check(UnknownPassengerRange.bounds(3500.0,3000.0) == "3000–3500")
    check(UnknownPassengerRange.bounds(null,3000.0) == "—")
    check(UnknownPassengerRange.bounds(Double.NaN,3000.0) == "—")
    val cRoute = OfflineRoute(12.0,25.0)
    val cDemand = Demand(DemandType.FIXED_ADD,100.0)
    val comfort = RouteFareEstimator.calculate(TarifCatalog.forName("Комфорт")!!, cRoute, cDemand, 19.2, 1.0)
    val comfortPlus = RouteFareEstimator.calculate(TarifCatalog.forName("Комфорт+")!!, cRoute, cDemand, 19.2, 1.0)
    check(comfort.gross < comfortPlus.gross)
    check(comfort.net!! < comfortPlus.net!!)
'''+s[b:]
p.write_text(s)
print("Unknown passenger: Comfort to Comfort+ range, no EV rate.")


# Owner requests persistent card-address diagnostics during field trials.
# Show raw extracted address text even when routing or pricing fails.
edit("OfferPopupView.kt", "    private val logicalHeight get() = if (waiting) 38 else quoteHeight + if (assumedEv) 36 else 0",
'''    private val addressTop get() = quoteHeight + if (assumedEv) 36 else 0
    private val logicalHeight get() = if (waiting) 38 else addressTop + 48''')
edit("OfferPopupView.kt", '''        c.restore()
        if (hasQuote) onPriceDrawn?.invoke()''',
'''        val addressY = addressTop.toFloat()
        line(c,addressY)
        fun addressRow(label: String, address: String?, baseline: Float) {
            val raw = address?.trim()?.takeIf { it.isNotEmpty() }
            text(c, "$label: " + (raw ?: "Не считан"), 9f, baseline, 16f,
                if (raw == null) Color.rgb(255, 100, 100) else Color.WHITE,
                false, Paint.Align.LEFT, 222f)
        }
        addressRow("А", pickup, addressY + 19f)
        addressRow("Б", destination, addressY + 39f)
        c.restore()
        if (hasQuote) onPriceDrawn?.invoke()''')
edit("OfferPopupView.kt", '''        val route = if (showAddresses) "А: ${pickup ?: "—"}. Б: ${destination ?: "—"}." else ""''',
'''        val route = "А: ${pickup?.takeIf { it.isNotBlank() } ?: "Не считан"}. Б: ${destination?.takeIf { it.isNotBlank() } ?: "Не считан"}."''')
print("Address diagnostic rows: always visible on order, no map-coordinate substitution.")


# Stable diagnostics for screenshots; do not conflate missing text with failed geocoding.
p=root/"RouteQuality.kt"
p.write_text(p.read_text()+'''
internal object OfferErrorCodes {
    fun address(point: String, raw: String?): String =
        raw?.trim()?.takeIf { it.isNotEmpty() } ?: "E-$point-01"

    fun status(status: String, pickup: String?, destination: String?): String? = when {
        status.startsWith("Не считаны остановки") -> "E-R02"
        status.startsWith("Не считан") ->
            listOfNotNull("E-A-01".takeIf { pickup.isNullOrBlank() },
                "E-B-01".takeIf { destination.isNullOrBlank() })
                .joinToString(" / ").ifBlank { "E-T01" }
        status == "Тариф не считан" -> "E-T01"
        status.startsWith("Уточните адрес") -> "E-G01 " + status.removePrefix("Уточните адрес").trim()
        status.startsWith("Адрес не найден") -> "E-G01"
        status == "Уточните название места" -> "E-G01"
        status.startsWith("Нет маршрута") -> "E-R01"
        status == "Ошибка тарифной модели" -> "E-P01"
        status == "База комиссии неизвестна" -> "E-C01"
        status == "За 4 сек цена не готова" -> "E-TIME"
        status.startsWith("Предварительно") -> "W-G01"
        else -> null
    }
}
''')
edit("OfferPopupView.kt", '            text(c, "$label: " + (raw ?: "Не считан"), 9f, baseline, 16f,',
     '            text(c, "$label: " + OfferErrorCodes.address(if (label == "А") "A" else "B", raw), 9f, baseline, 16f,')
edit("OfferPopupView.kt", '''        val route = "А: ${pickup?.takeIf { it.isNotBlank() } ?: "Не считан"}. Б: ${destination?.takeIf { it.isNotBlank() } ?: "Не считан"}."''',
'''        val route = "А: ${OfferErrorCodes.address("A",pickup)}. Б: ${OfferErrorCodes.address("B",destination)}."''')
edit("OfferPopupView.kt", '''        val route = "А: ${OfferErrorCodes.address("A",pickup)}. Б: ${OfferErrorCodes.address("B",destination)}."''',
'''        val diagnosticCode = OfferErrorCodes.status(status, pickup, destination)
        if (diagnosticCode != null) footer = diagnosticCode.trim()
        val route = "А: ${OfferErrorCodes.address("A",pickup)}. Б: ${OfferErrorCodes.address("B",destination)}."''')
edit("OfferPopupView.kt", 'text(c,if (approximateQuote) "≈ Неточный адрес" else footer,120f,108f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)',
     'text(c,if (approximateQuote) "W-G01" else footer,120f,108f,14f,Color.rgb(255,100,100),false,Paint.Align.CENTER,228f)')
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
a="    addressMatcherChecks()"
assert s.count(a)==1
p.write_text(s.replace(a,'''    check(OfferErrorCodes.address("A",null) == "E-A-01")
    check(OfferErrorCodes.address("B"," ") == "E-B-01")
    check(OfferErrorCodes.address("B","ул. Абая, 10") == "ул. Абая, 10")
    check(OfferErrorCodes.status("Уточните адрес А+ Б2","А","Б") == "E-G01 А+ Б2")
    check(OfferErrorCodes.status("Нет маршрута BRouter","А","Б") == "E-R01")
    check(OfferErrorCodes.status("Ошибка тарифной модели","А","Б") == "E-P01")
    check(OfferErrorCodes.status("Не считаны остановки","А","Б") == "E-R02")
    check(OfferErrorCodes.status("За 4 сек цена не готова","А","Б") == "E-TIME")
    check(OfferErrorCodes.status("Время Яндекс Про","А","Б") == null)
'''+a))
print("Stable screenshot diagnostics enabled; no raw address logging added.")


# Owner: missing-address codes appear ONLY in their corresponding A/B row.
# Suppress the generic footer entirely for missing-address states, reclaim space.
edit("RouteQuality.kt", '''        status.startsWith("Не считан") ->
            listOfNotNull("E-A-01".takeIf { pickup.isNullOrBlank() },
                "E-B-01".takeIf { destination.isNullOrBlank() })
                .joinToString(" / ").ifBlank { "E-T01" }''',
'''        status.startsWith("Не считан") ->
            if (pickup.isNullOrBlank() || destination.isNullOrBlank()) null else "E-T01"''')
edit("RouteQuality.kt", "    fun status(status: String, pickup: String?, destination: String?): String? = when {",
'''    fun addressFailureOnly(status: String, pickup: String?, destination: String?): Boolean =
        status.startsWith("Не считан") && !status.startsWith("Не считаны остановки") &&
            (pickup.isNullOrBlank() || destination.isNullOrBlank())

    fun status(status: String, pickup: String?, destination: String?): String? = when {''')
edit("OfferPopupView.kt", "    private val quoteHeight get() = if (!hasQuote || approximateQuote) 116 else 96",
'''    private var addressFailureOnly = false
    private val showDiagnostic get() = approximateQuote || (!hasQuote && !addressFailureOnly)
    private val quoteHeight get() = if (showDiagnostic) 116 else 96''')
edit("OfferPopupView.kt", '        approximateQuote = estimate != null && status.startsWith("Предварительно")',
'''        approximateQuote = estimate != null && status.startsWith("Предварительно")
        addressFailureOnly = OfferErrorCodes.addressFailureOnly(status, pickupAddress, destinationAddress)''')
edit("OfferPopupView.kt", "        if (!hasQuote || approximateQuote) {", "        if (showDiagnostic) {")
edit("OfferPopupView.kt", "        if (diagnosticCode != null) footer = diagnosticCode.trim()",
'''        if (addressFailureOnly) footer = ""
        else if (diagnosticCode != null) footer = diagnosticCode.trim()''')
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
a="    addressMatcherChecks()"
assert s.count(a)==1
p.write_text(s.replace(a,'''    check(OfferErrorCodes.addressFailureOnly("Не считан адрес Б","Жангельдина, 166",null))
    check(OfferErrorCodes.status("Не считан адрес Б","Жангельдина, 166",null) == null)
    check(OfferErrorCodes.addressFailureOnly("Не считаны адреса А и Б",null,null))
    check(OfferErrorCodes.status("Не считаны адреса А и Б",null,null) == null)
    check(!OfferErrorCodes.addressFailureOnly("Не считаны остановки","А","Б"))
    check(!OfferErrorCodes.addressFailureOnly("Нет маршрута BRouter","А","Б"))
'''+a))
print("Missing-address codes appear only in A/B rows.")


# Field defect: both card addresses read, but named airport terminal rejected.
# The airport site calls the international terminal T2; do not substitute
# the airport reference point, domestic terminal, VIP, or runway.
edit("PlaceLookup.kt", "    fun queries(raw: String): List<String> {",
r'''    private val terminal2Names = listOf(
        "Алматы Аэропорт, Международный терминал",
        "Международный аэропорт Алматы – Международный терминал",
        "Международный терминал аэропорта Алматы",
        "Терминал международных авиалиний",
        "Новый международный терминал",
        "Новый международный терминал (Т2)",
        "Международный терминал",
        "Международный терминал Т2",
        "New International Terminal (Т2)",
        "New International Terminal (T2)",
        "International Terminal T2",
        "Т2",
        "T2"
    )
    private fun terminalKey(raw: String): String =
        raw.lowercase(java.util.Locale.ROOT).replace('ё','е').replace('т','t')
            .replace(Regex("""[^\p{L}\p{N}]+""")," ").trim()
    fun airportTerminalAliases(raw: String): List<String> =
        if (terminal2Names.any { terminalKey(it) == terminalKey(raw) }) terminal2Names else emptyList()

    // Airport passenger-terminal district, not a destination coordinate.
    fun terminalDistrict(lat: Double, lon: Double): Boolean =
        lat in 43.340..43.360 && lon in 77.000..77.025

    fun queries(raw: String): List<String> {''')
edit("PlaceLookup.kt", "        return listOf(raw, expanded, name).filter(String::isNotBlank).distinct()",
'''        val aliases = airportTerminalAliases(name)
        return if (aliases.isEmpty()) listOf(raw, expanded, name).filter(String::isNotBlank).distinct()
            else (listOf(raw) + aliases.filter { it.length > 2 && it != name } + name).distinct()''')
# The last item must retain the original requested name even when already first.
edit("PlaceLookup.kt", 'else (listOf(raw) + aliases.filter { it.length > 2 && it != name } + name).distinct()',
     'else (listOf(raw) + aliases.filter { it.length > 2 }).distinct().filter { it != name } + name')
edit("PlaceLookup.kt", "        val key = normalize(name)",
'''        val aliases = airportTerminalAliases(name)
        if (aliases.isNotEmpty()) {
            val keys = aliases.filter { it.length > 2 }.map(::terminalKey).toSet()
            val hits = matches.filter { item ->
                terminalDistrict(item.lat,item.lon) && item.labels.any { label ->
                    terminalKey(label) in keys || label.split(',').any { terminalKey(it) in keys }
                }
            }
            val first = hits.firstOrNull() ?: return null
            return first.takeIf { hits.all {
                kotlin.math.abs(it.lat-first.lat) <= 0.0008 &&
                    kotlin.math.abs(it.lon-first.lon) <= 0.001
            } }
        }
        val key = normalize(name)''')
# Try exact named-POI aliases in the existing local OSM index before Android
# geocoder. Never accept a city-wide terminal name or airfield centroid.
edit("OfflineRoutePipeline.kt", '''            else runCatching { offlineAlmaty.findExact(raw) }.getOrNull()
                ?: LearnedPlaces.find(appContext, raw)''',
'''            else {
                val aliases = PlaceLookup.airportTerminalAliases(raw)
                if (aliases.isEmpty()) runCatching { offlineAlmaty.findExact(raw) }.getOrNull()
                    ?: LearnedPlaces.find(appContext, raw)
                else {
                    val points = aliases.filter { it.length > 2 }.mapNotNull { name ->
                        runCatching { offlineAlmaty.findExact(name) }.getOrNull()
                            ?.takeIf { PlaceLookup.terminalDistrict(it.lat,it.lon) }
                    }
                    val first = points.firstOrNull()
                    first?.takeIf { point -> points.all {
                        kotlin.math.abs(it.lat-point.lat) <= 0.0008 &&
                            kotlin.math.abs(it.lon-point.lon) <= 0.001
                    } }
                }
            }''')
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
a="    addressMatcherChecks()"
assert s.count(a)==1
p.write_text(s.replace(a,'''    // Synthetic points for identity checks only, not real terminal coordinates.
    val airportOrder = "Алматы Аэропорт, Международный терминал"
    val t2 = PlaceLookup.Match(43.350,77.012,listOf("New International Terminal (Т2)"))
    val t1 = PlaceLookup.Match(43.348,77.012,listOf("Внутренний терминал"))
    val genericAirport = PlaceLookup.Match(43.355,77.042,listOf("Международный аэропорт Алматы"))
    check(PlaceLookup.queries(airportOrder).contains("New International Terminal (Т2)"))
    check(PlaceLookup.queries(airportOrder).last() == airportOrder)
    check(PlaceLookup.namedMatch(airportOrder,listOf(t1,genericAirport,t2)) == t2)
    check(PlaceLookup.namedMatch(airportOrder,listOf(t1,genericAirport)) == null)
    check(PlaceLookup.namedMatch(airportOrder,listOf(t2.copy(lat=43.25))) == null)
    check(PlaceLookup.airportTerminalAliases("Алматы Аэропорт, Внутренний терминал").isEmpty())
    check(PlaceLookup.namedMatch(airportOrder,listOf(t2,t2.copy(lat=43.353))) == null)
'''+a))
print("Airport terminal T2 alias regression added; real route still requires field test.")
