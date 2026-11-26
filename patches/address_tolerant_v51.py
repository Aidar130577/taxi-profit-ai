"""v51: tolerant address matching + per-endpoint diagnostic codes (fixes v50 'Уточните адрес' on every order).

Field result for v50 (4 of 4 orders): no price. v50 required an exact normalised key match against OSM and a
single geocoder candidate whose first two comma segments equalled the order text. Real data differs in street-name
variants (full names, case endings), Latin/Cyrillic house letters, 'блок/корпус' notations, geocoder labels such as
'улица Шевченко 118, Алматы 050000' and venue/microdistrict segments. Strictness stays (a different street or house is
never accepted) but comparison is done on parsed street tokens and house numbers.
Run from the android-project directory after exact_geocode_v50.py (which invokes this script).
"""
from pathlib import Path

root = Path("app/src/main/java/kz/taxiprofitai")


def edit(path, old, new):
    s = path.read_text()
    assert s.count(old) == 1, f"{path.name}: expected exactly one match for: {old[:90]!r} (found {s.count(old)})"
    path.write_text(s.replace(old, new, 1))


# ---------------------------------------------------------------- pure-JVM matcher (compiled by CI tests too)
MATCHER = r'''

/** Tolerant address comparison: street-name variants, case endings, Latin/Cyrillic house letters, corpus notations. */
object AddressMatcher {
    data class Parts(val street: List<String>, val house: String)
    enum class Level { FULL, NEAR }

    private val dropWords = setOf(
        "улица", "ул", "проспект", "просп", "пр", "микрорайон", "мкр", "мкрн", "переулок", "пер", "шоссе",
        "бульвар", "бул", "площадь", "пл", "проезд", "тупик", "көшесі", "даңғылы", "street", "st", "avenue", "ave",
        "город", "г", "алматы", "казахстан", "almaty", "kazakhstan"
    )
    private val lookalike = mapOf(
        'a' to 'а', 'b' to 'в', 'c' to 'с', 'e' to 'е', 'h' to 'н', 'k' to 'к',
        'm' to 'м', 'o' to 'о', 'p' to 'р', 't' to 'т', 'x' to 'х', 'y' to 'у'
    )
    private const val HOUSE_CORE = """\d{1,4}\s*[a-zа-я]?(?:\s*[/-]\s*\d{1,4}[a-zа-я]?)?(?:\s*(?:блок|корпус|корп|к|стр|строение)\s*\d{1,3})?"""
    private val houseOnly = Regex("^" + HOUSE_CORE + "\$")
    private val houseTail = Regex("^(.*\\D)\\s+(" + HOUSE_CORE + ")\$")
    private val skipSegment = Regex("^(?:микрорайон|мкр|мкрн|район|выход|вход|подъезд)(?![\\p{L}]).*")
    private val splitter = Regex("[^\\p{L}\\p{N}]+")
    private val corpusWord = Regex("\\s*(?:блок|корпус|корп|стр|строение)\\s*")

    private fun house(seg: String): String? {
        val s = seg.trim().map { lookalike[it] ?: it }.joinToString("")
        if (!houseOnly.matches(s)) return null
        return s.replace(corpusWord, "к").replace(" ", "").replace('-', '/')
    }

    private fun tokens(seg: String): List<String> =
        seg.split(splitter).filter { it.isNotEmpty() && it !in dropWords }

    /** Street tokens and canonical house of an order address, an OSM label or a geocoder line; null if it has no house. */
    fun parse(raw: String): Parts? {
        val text = (PlaceLookup.streetAddress(raw) ?: raw).replace('\u00a0', ' ').lowercase().replace('ё', 'е')
        val segments = text.split(',').map { it.trim() }.filter { it.isNotEmpty() && !skipSegment.matches(it) }
        for (i in 1 until segments.size) {
            val h = house(segments[i]) ?: continue
            val street = tokens(segments[i - 1])
            if (street.isNotEmpty()) return Parts(street, h)
        }
        val first = segments.firstOrNull() ?: return null
        val m = houseTail.matchEntire(first) ?: return null
        val h = house(m.groupValues[2]) ?: return null
        val street = tokens(m.groupValues[1])
        return if (street.isEmpty()) null else Parts(street, h)
    }

    private fun stem(t: String) = if (t.length <= 4) t else t.substring(0, 5)

    fun sameStreet(a: List<String>, b: List<String>): Boolean {
        if (a.isEmpty() || b.isEmpty()) return false
        val (small, large) = if (a.size <= b.size) a to b else b to a
        val stems = large.map(::stem)
        return small.all { stem(it) in stems }
    }

    private fun nearHouse(a: String, b: String): Boolean {
        val (s, l) = if (a.length <= b.length) a to b else b to a
        return l.startsWith(s) && (l.length == s.length || !l[s.length].isDigit())
    }

    fun match(order: Parts, candidate: Parts): Level? {
        if (!sameStreet(order.street, candidate.street)) return null
        return when {
            order.house == candidate.house -> Level.FULL
            nearHouse(order.house, candidate.house) -> Level.NEAR
            else -> null
        }
    }

    fun matchesLabel(order: Parts, label: String): Level? = parse(label)?.let { match(order, it) }

    fun searchStem(p: Parts): String? = p.street.maxByOrNull { it.length }?.let(::stem)?.takeIf { it.length >= 3 }

    fun houseDigits(p: Parts): String = p.house.takeWhile { it.isDigit() }
}
'''
place = root / "PlaceLookup.kt"
place.write_text(place.read_text().rstrip("\n") + "\n" + MATCHER)

edit(place, "    private fun normalize(text: String): String =",
     '''    /** Geocoder candidates that denote the ordered address. Several records of one building are fine; separated ones are ambiguous. */
    fun addressMatch(raw: String, matches: List<Match>): Match? {
        val order = AddressMatcher.parse(raw)
        val hits = matches.filter { candidate ->
            candidate.labels.any { label ->
                (order != null && AddressMatcher.matchesLabel(order, label) != null) ||
                    OrderTextParser.samePoint(raw, label.split(',').take(2).joinToString(",").trim())
            }
        }
        val first = hits.firstOrNull() ?: return null
        return first.takeIf {
            hits.all { kotlin.math.abs(it.lat - first.lat) <= 0.003 && kotlin.math.abs(it.lon - first.lon) <= 0.004 }
        }
    }

    private fun normalize(text: String): String =''')

# ---------------------------------------------------------------- offline index: tolerant fallback after the exact key lookup
index = root / "OfflineAlmatyIndex.kt"
edit(index, "    fun find(raw: String): BRouterConnector.Point? {",
     "    fun find(raw: String): BRouterConnector.Point? = findExact(raw) ?: findTolerant(raw)\n\n"
     "    private fun findExact(raw: String): BRouterConnector.Point? {")
edit(index, "    private var preparedFile: File? = null", '''    /** Street-name variants and house notations that the exact key lookup cannot see. Same ambiguity rule as the exact lookup. */
    private fun findTolerant(raw: String): BRouterConnector.Point? {
        val order = AddressMatcher.parse(raw) ?: return null
        val stem = AddressMatcher.searchStem(order) ?: return null
        val digits = AddressMatcher.houseDigits(order)
        val path = indexFile() ?: return null
        open(path).use { db ->
            val found = ArrayList<BRouterConnector.Point>()
            db.rawQuery(
                "select lat, lon, label from places where kind = 0 and key like ? and key like ? limit 600",
                arrayOf("%" + stem + "%", "%" + digits + "%")
            ).use { cursor ->
                while (cursor.moveToNext()) {
                    if (AddressMatcher.matchesLabel(order, cursor.getString(2)) != null) {
                        found.add(BRouterConnector.Point(cursor.getInt(0) / 1_000_000.0, cursor.getInt(1) / 1_000_000.0))
                    }
                }
            }
            if (found.isEmpty()) return null
            val first = found.first()
            if (found.any { kotlin.math.abs(it.lat - first.lat) > 0.003 || kotlin.math.abs(it.lon - first.lon) > 0.004 }) {
                error("Место не найдено однозначно")
            }
            return first
        }
    }

    private var preparedFile: File? = null''')

# ---------------------------------------------------------------- diagnostics: reason code per endpoint (no addresses, no coordinates)
edit(root / "RouteQuality.kt",
     'internal class UncertainAddressException : IllegalArgumentException("Уточните адрес")',
     'internal class UncertainAddressException(val code: String = "?") : IllegalArgumentException("Уточните адрес")')

pipe = root / "OfflineRoutePipeline.kt"
edit(pipe, "        from.thenCombine(to) { start, end -> runCatching { start.getOrThrow() to end.getOrThrow() } }",
     '''        from.thenCombine(to) { start, end ->
            val failA = start.exceptionOrNull()
            val failB = end.exceptionOrNull()
            if (failA == null && failB == null) Result.success(start.getOrThrow() to end.getOrThrow())
            else Result.failure<Pair<Resolved, Resolved>>(UncertainAddressException("А" + codeOf(failA) + " Б" + codeOf(failB)))
        }''')
edit(pipe, "    private fun complete(key: String, result: Result<OfflineRoute>) {",
     '''    // + found; 0 nothing found; 1 candidates found but none is this address; 2 several different places;
    // 3 no geocoder service; 4 geocoder error; ! other.
    private fun codeOf(e: Throwable?): String = when {
        e == null -> "+"
        e is UncertainAddressException -> e.code
        e.message == "Место не найдено однозначно" -> "2"
        else -> "!"
    }

    private fun complete(key: String, result: Result<OfflineRoute>) {''')
edit(pipe, "            val named = PlaceLookup.isNamedPlace(queries.lastOrNull().orEmpty())\n",
     "            val named = PlaceLookup.isNamedPlace(queries.lastOrNull().orEmpty())\n"
     "            var seen = 0\n            var failed = false\n")
edit(pipe, 'runCatching { geocoder.getFromLocationName("$query, Алматы, Казахстан", 5) }.getOrNull()',
     'runCatching { geocoder.getFromLocationName("$query, Алматы, Казахстан", 5) }.onFailure { failed = true }.getOrNull()')
edit(pipe, "listOfNotNull(address.featureName, address.premises, address.getAddressLine(0)))",
     "listOfNotNull(address.featureName, address.premises, address.getAddressLine(0),\n"
     "                                address.thoroughfare?.let { street -> address.subThoroughfare?.let { house -> street + \", \" + house } }))")
edit(pipe, "            }.map { matches ->\n", "            }.map { matches ->\n                seen += matches.size\n")
edit(pipe, '''PlaceLookup.namedMatch(queries.last(), matches) else matches.filter { candidate ->
                    candidate.labels.any { label ->
                        OrderTextParser.samePoint(raw, label.split(',').take(2).joinToString(",").trim())
                    }
                }.singleOrNull()''', "PlaceLookup.namedMatch(queries.last(), matches) else PlaceLookup.addressMatch(raw, matches)")
edit(pipe, "                ?: throw UncertainAddressException()\n            found",
     '                ?: throw UncertainAddressException(when {\n'
     '                    !Geocoder.isPresent() -> "3"\n                    failed -> "4"\n                    seen == 0 -> "0"\n                    else -> "1"\n'
     '                })\n            found')

radar = root / "RadarAccessibilityService.kt"
edit(radar, 'routeStatus = if (badgeQuote == null) "Уточните адрес" else "Время Яндекс Про"',
     'routeStatus = if (badgeQuote == null) "Уточните адрес " + ((failure as? UncertainAddressException)?.code ?: "") else "Время Яндекс Про"')
edit(root / "OfferPopupView.kt", 'status == "Уточните адрес" -> status', 'status.startsWith("Уточните адрес") -> status')

# ---------------------------------------------------------------- checks (run by CI together with RouteQualityCheck)
chk = Path("core-tests/RouteQualityCheck.kt")
edit(chk, '    println("Route quality checks passed")', '    addressMatcherChecks()\n    println("Route quality checks passed")')
chk.write_text(chk.read_text().rstrip("\n") + "\n" + r'''
private fun addressMatcherChecks() {
    fun ck(ok: Boolean, name: String) { if (!ok) error("AddressMatcher: $name") }
    fun level(order: String, label: String): AddressMatcher.Level? =
        AddressMatcher.parse(order)?.let { AddressMatcher.matchesLabel(it, label) }
    // Real orders from the field test (v50 refused all of them).
    ck(level("улица Байтурсынова, 103", "улица Ахмета Байтурсынова, 103") == AddressMatcher.Level.FULL, "full street name in OSM")
    ck(level("Spectrum, ул. Кабанбай батыра, 51В, Алматы", "проспект Кабанбай батыра, 51B") == AddressMatcher.Level.FULL, "venue prefix, Latin house letter")
    ck(level("Maximus, ул. Нагимы Арыковой, 54/49, Алматы", "улица Нагимы Арыкова, 54/49") == AddressMatcher.Level.FULL, "case ending, slash house")
    ck(level("Жетысуская улица, 17/1", "улица Жетысуская, 17/1") == AddressMatcher.Level.FULL, "street word after the name")
    ck(level("Жетысуская улица, 17/1", "улица Жетысуская, 17") == AddressMatcher.Level.NEAR, "same plot, shorter house number")
    ck(level("Жетысуская улица, 17/1", "улица Жетысуская, 18") == null, "different house rejected")
    ck(level("улица Шевченко, 118", "улица Шевченко 118, Алматы 050000, Казахстан") == AddressMatcher.Level.FULL, "geocoder line without comma")
    ck(level("ул. Жолдасбекова, 9А, микрорайон Самал-1, Алматы", "улица Жолдасбекова, 9А") == AddressMatcher.Level.FULL, "microdistrict segment")
    ck(level("улица Талгата Бигельдинова, 1Бблок4", "улица Талгата Бигельдинова, 1Б к4") == AddressMatcher.Level.FULL, "block notation")
    ck(level("улица Талгата Бигельдинова, 1Бблок4", "улица Талгата Бигельдинова, 1Б") == AddressMatcher.Level.NEAR, "block notation, base building")
    ck(level("улица Пушкина, 83", "улица Пушкина, 38") == null, "digits swapped rejected")
    ck(level("улица Пушкина, 83", "улица Абая, 83") == null, "different street rejected")
    ck(level("улица Пушкина, 83", "улица Пушкина, 830") == null, "prefix of a longer number rejected")
    ck(AddressMatcher.parse("Dostyk Plaza, Выход на паркинг — 2 этаж") == null, "named place has no house")
    val order = AddressMatcher.parse("Spectrum, ул. Кабанбай батыра, 51В, Алматы")!!
    ck(AddressMatcher.searchStem(order) == "кабан" && AddressMatcher.houseDigits(order) == "51", "search stem and digits")
    val a = PlaceLookup.Match(43.2500, 76.9500, listOf("улица Шевченко 118, Алматы 050000, Казахстан"))
    val b = PlaceLookup.Match(43.2501, 76.9502, listOf("улица Шевченко, 118"))
    val c = PlaceLookup.Match(43.2800, 76.9500, listOf("улица Шевченко, 118"))
    ck(PlaceLookup.addressMatch("улица Шевченко, 118", listOf(a, b)) != null, "duplicate records of one building")
    ck(PlaceLookup.addressMatch("улица Шевченко, 118", listOf(a, c)) == null, "separated buildings are ambiguous")
    ck(PlaceLookup.addressMatch("улица Шевченко, 118", listOf(PlaceLookup.Match(43.25, 76.95, listOf("улица Абая, 118")))) == null, "other street rejected")
}
''')
print("v51 address tolerance + diagnostics applied.")
