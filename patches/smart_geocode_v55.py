#!/usr/bin/env python3
"""v55 runtime smart index, conservative pickup-only disambiguation."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p=root/name
    s=p.read_text()
    assert s.count(old)==1,(name,old[:160],s.count(old))
    p.write_text(s.replace(old,new,1))
p=root/"PlaceLookup.kt"
p.write_text(p.read_text()+r'''
/** Deterministic candidate keys shared with build_smart_index_v55.py. */
internal object SmartPlace {
    private val types = mapOf(
        "street" to "улица ул көшесі street st",
        "avenue" to "проспект просп пр даңғылы avenue ave",
        "lane" to "переулок пер lane", "boulevard" to "бульвар бул boulevard",
        "drive" to "проезд drive", "highway" to "шоссе highway",
        "district" to "микрорайон мкр мкрн ықшамаудан microdistrict",
        "square" to "площадь пл square"
    ).mapValues { it.value.split(" ").toSet() }
    private val drop = "город г алматы almaty казахстан kazakhstan".split(" ").toSet() + types.values.flatten()
    private val translit = "абвгдежзийклмнопрстуфхцчшщыэюяьъәғқңөұүһі".toList().zip(
        "a b v g d e zh z i y k l m n o p r s t u f kh ts ch sh shch y e yu ya _ _ a g k ng o u u h i".split(" ")
    ).toMap()
    private val aliases = mapOf(
        "baitursyn" to "байтурсын байтурсынова байтурсынов байтурсынулы байтұрсынұлы baitursyn baitursynov baitursynova baitursynuly baytursynov baytursynuly",
        "abay" to "абай абая abay abai",
        "satpayev" to "сатпаев сатпаева сәтбаев satpayev satpaev satbayev satbaev",
        "dostyk" to "достык достық dostyk dostyq"
    ).flatMap { (k,v) -> v.split(" ").map { it to k } }.toMap()
    private fun tokens(raw: String) = java.text.Normalizer.normalize(raw,java.text.Normalizer.Form.NFKC)
        .lowercase(java.util.Locale.ROOT).replace('ё','е').split(Regex("""[^\p{L}\p{N}]+""")).filter { it.isNotEmpty() }
    fun type(raw: String): String {
        val t=tokens(raw).toSet()
        return types.filter { (_,v) -> v.any { it in t } }.keys.singleOrNull().orEmpty()
    }
    fun key(raw: String, address: Boolean): String {
        var t=tokens(raw)
        if (address) t=t.filter { it !in drop }
        else if (t.firstOrNull() in "кафе кофейня ресторан магазин трц тц бц жк здание отель гостиница".split(" ")) t=t.drop(1)
        var k=t.map { word -> aliases[word] ?: word.map { translit[it] ?: it.toString() }.joinToString("").replace("_","") }
        if (address && "baitursyn" in k) k=k.filter { it !in setOf("akhmet","akhmeta","ahmet","ahmeta") }
        return k.filter { it.isNotEmpty() }.distinct().sorted().joinToString(" ")
    }
    data class Candidate(val lat: Double, val lon: Double, val type: String)
    data class Hint(val lat: Double, val lon: Double, val accuracyM: Double, val pickupKm: Double?)
    data class Choice(val point: Candidate, val certain: Boolean)
    fun metres(a: Double,b: Double,c: Double,d: Double): Double {
        val p=Math.toRadians(c-a); val q=Math.toRadians(d-b)
        val h=kotlin.math.sin(p/2).let { it*it } +
            kotlin.math.cos(Math.toRadians(a))*kotlin.math.cos(Math.toRadians(c))*kotlin.math.sin(q/2).let { it*it }
        return 12742000.0*kotlin.math.asin(kotlin.math.sqrt(h.coerceIn(0.0,1.0)))
    }
    fun choose(all: List<Candidate>, requestedType: String, hint: Hint?): Choice? {
        val compatible=all.filter { requestedType.isEmpty() || it.type.isEmpty() || it.type==requestedType }
        if (compatible.isEmpty()) return null
        val typed=if (requestedType.isNotEmpty()) compatible.filter { it.type==requestedType }.ifEmpty { compatible } else compatible
        val first=typed.first()
        if (typed.all { metres(first.lat,first.lon,it.lat,it.lon)<=85.0 }) {
            // If a credible pickup distance contradicts even the single result, refuse it.
            if (hint?.pickupKm != null && metres(hint.lat,hint.lon,first.lat,first.lon) >
                hint.pickupKm*1000 + maxOf(200.0,hint.accuracyM*2)) return null
            return Choice(first,requestedType.isEmpty() || first.type==requestedType)
        }
        if (hint==null) return null
        val limit=hint.pickupKm?.let { it*1000+maxOf(200.0,hint.accuracyM*2) }
        val sorted=typed.map { it to metres(hint.lat,hint.lon,it.lat,it.lon) }
            .filter { limit==null || it.second<=limit }.sortedBy { it.second }
        val best=sorted.firstOrNull() ?: return null
        val distant=sorted.firstOrNull { metres(best.first.lat,best.first.lon,it.first.lat,it.first.lon)>85.0 }
        if (distant!=null && distant.second-best.second < maxOf(500.0,hint.accuracyM*4,best.second*0.6)) return null
        // Context-dependent selection is provisional, never a persistent verified alias.
        return Choice(best.first,false)
    }
}
''')
# Keep types in parsed addresses; the existing five-character fallback cannot
# turn explicitly different road classes into a verified address.
edit("PlaceLookup.kt", "    data class Parts(val street: List<String>, val house: String)",
     '    data class Parts(val street: List<String>, val house: String, val roadType: String = "")')
edit("PlaceLookup.kt", "return Parts(street, h)", "return Parts(street, h, SmartPlace.type(segments[i - 1]))")
edit("PlaceLookup.kt", "else Parts(street, h)", "else Parts(street, h, SmartPlace.type(m.groupValues[1]))")
edit("PlaceLookup.kt", "        if (!sameStreet(order.street, candidate.street)) return null",
'''        if (order.roadType.isNotEmpty() && candidate.roadType.isNotEmpty() && order.roadType != candidate.roadType) return null
        if (!sameStreet(order.street, candidate.street)) return null''')
# Exact canonical matching first, conservative legacy morphological variants.
edit("PlaceLookup.kt", '''        val (small, large) = if (a.size <= b.size) a to b else b to a
        val stems = large.map(::stem)
        return small.all { stem(it) in stems }''',
'''        val ka=SmartPlace.key(a.joinToString(" "),true)
        val kb=SmartPlace.key(b.joinToString(" "),true)
        if (ka.isNotEmpty() && ka==kb) return true
        fun ending(s: String) = s.replace(Regex("""(?:овой|ова|овой|евой|ева)$"""),"ов")
        val aa=a.map(::ending).toSet()
        val bb=b.map(::ending).toSet()
        return aa==bb''')
# Old unit test conflated two explicitly different road classes; new contract rejects this.
p=Path("core-tests/RouteQualityCheck.kt")
s=p.read_text()
old='ck(level("Spectrum, ул. Кабанбай батыра, 51В, Алматы", "проспект Кабанбай батыра, 51B") == AddressMatcher.Level.FULL'
assert s.count(old)==1
s=s.replace(old,old.replace('проспект','улица'))
# Keep old short/full forms for known Baitursyn variants, and check disambiguation.
a="    addressMatcherChecks()"
assert s.count(a)==1
s=s.replace(a,'''    check(SmartPlace.key("Байтурсынова",true)==SmartPlace.key("Байтұрсынұлы көшесі",true))
    check(SmartPlace.key("Baitursynov",true)==SmartPlace.key("Байтурсын",true))
    check(SmartPlace.key("Dostyk Plaza",false)==SmartPlace.key("Plaza Dostyk",false))
    check(SmartPlace.type("Абай көшесі, 25")=="street")
    check(SmartPlace.type("Abay Avenue, 25")=="avenue")
    check(AddressMatcher.parse("улица Абая, 25")?.let { AddressMatcher.matchesLabel(it,"проспект Абая, 25") } == null)
    val nearA=SmartPlace.Candidate(43.250,76.95,"street")
    val farA=SmartPlace.Candidate(43.350,76.95,"street")
    val avenueA=SmartPlace.Candidate(43.250,76.95,"avenue")
    val hintA=SmartPlace.Hint(43.249,76.95,20.0,0.8)
    check(SmartPlace.choose(listOf(nearA,farA),"street",hintA)?.point==nearA)
    check(SmartPlace.choose(listOf(nearA,farA),"street",hintA)?.certain==false)
    check(SmartPlace.choose(listOf(nearA,farA),"street",null)==null)
    check(SmartPlace.choose(listOf(avenueA),"street",hintA)==null)
'''+a)
p.write_text(s)

# Smart indexed lookup; distinguish no match from conflicting matches. No full-table scan.
edit("OfflineAlmatyIndex.kt", "    internal fun findExact(raw: String): BRouterConnector.Point? {",
'''    internal fun warmSmart() { indexFile()?.let { path -> open(path).use { db ->
        db.rawQuery("select count(*) from metadata",null).use { it.moveToFirst() }
    } } }

    internal fun smartCandidates(raw: String): List<SmartPlace.Candidate> {
        val order=AddressMatcher.parse(raw)
        val sig=if (order!=null) SmartPlace.key(order.street.joinToString(" "),true)
            else SmartPlace.key(PlaceLookup.queries(raw).lastOrNull() ?: raw,false)
        if (sig.isBlank()) return emptyList()
        val path=indexFile() ?: return emptyList()
        return open(path).use { db ->
            db.rawQuery("select lat,lon,roadtype from smart_candidates where kind=? and sig=? and house=? limit 81",
                arrayOf(if(order==null) "1" else "0",sig,order?.house.orEmpty())).use { cursor ->
                if(cursor.count>=81) throw UncertainAddressException("2")
                buildList {
                    while(cursor.moveToNext()) add(SmartPlace.Candidate(cursor.getInt(0)/1e6,cursor.getInt(1)/1e6,cursor.getString(2)))
                }
            }
        }
    }

    internal fun findExact(raw: String): BRouterConnector.Point? {''')
# Fresh last-known fixes only; never block the incoming offer on a GPS request.
edit("OfflineRoutePipeline.kt", "    fun prepare() {",
'''    private fun pickupHint(km: Double?): SmartPlace.Hint? = runCatching {
        val lm=appContext.getSystemService(android.content.Context.LOCATION_SERVICE) as android.location.LocationManager
        lm.getProviders(true).mapNotNull { provider -> runCatching { lm.getLastKnownLocation(provider) }.getOrNull() }
            .filter { it.hasAccuracy() && it.accuracy<=60f &&
                android.os.SystemClock.elapsedRealtimeNanos()-it.elapsedRealtimeNanos in 0L..30_000_000_000L }
            .minByOrNull { it.accuracy }?.let { SmartPlace.Hint(it.latitude,it.longitude,it.accuracy.toDouble(),km?.takeIf { d -> d>0 && d.isFinite() }) }
    }.getOrNull()

    fun prepare() {
        geocodeWorker.execute { runCatching { offlineAlmaty.warmSmart() } }''')
edit("OfflineRoutePipeline.kt", "fun calculate(a: String, b: String, preview: ((OfflineRoute) -> Unit)? = null,",
     "fun calculate(a: String, b: String, pickupKm: Double? = null, preview: ((OfflineRoute) -> Unit)? = null,")
edit("OfflineRoutePipeline.kt", '        val key = a.trim().lowercase(Locale.ROOT) + "|" + b.trim().lowercase(Locale.ROOT)',
'''        val hint=pickupHint(pickupKm)
        val key = a.trim().lowercase(Locale.ROOT) + "|" + b.trim().lowercase(Locale.ROOT) +
            (hint?.let { "|A:" + it.lat + ":" + it.lon + ":" + it.pickupKm } ?: "")''')
edit("OfflineRoutePipeline.kt","runCatching { resolve(a) }","runCatching { resolve(a, hint) }")
edit("OfflineRoutePipeline.kt","private fun resolve(raw: String): Resolved {","private fun resolve(raw: String, hint: SmartPlace.Hint? = null): Resolved {")
edit("OfflineRoutePipeline.kt", "        synchronized(pointCache) { pointCache[norm]?.let { return it } }",
'''        // Airport-specific known aliases still use the prior exact terminal resolver.
        if (PlaceLookup.airportTerminalAliases(raw).isEmpty()) {
            val candidates=offlineAlmaty.smartCandidates(raw)
            if (candidates.isNotEmpty()) {
                val choice=SmartPlace.choose(candidates,AddressMatcher.parse(raw)?.roadType.orEmpty(),hint)
                    ?: throw UncertainAddressException("2")
                return Resolved(BRouterConnector.Point(choice.point.lat,choice.point.lon),choice.certain)
            }
        }
        if (hint==null) synchronized(pointCache) { pointCache[norm]?.let { return it } }''')
# Do not bypass the new index with a fuzzy house or type from the old local lookup.
edit("OfflineRoutePipeline.kt", '''                if (aliases.isEmpty()) runCatching { offlineAlmaty.findExact(raw) }.getOrNull()
                    ?: LearnedPlaces.find(appContext, raw)''',
'''                if (aliases.isEmpty()) {
                    if (AddressMatcher.parse(raw)!=null) null
                    else runCatching { offlineAlmaty.findExact(raw) }.getOrNull() ?: LearnedPlaces.find(appContext, raw)
                }''')
edit("OfflineRoutePipeline.kt", '        val tolerant = if (offline == null) runCatching { offlineAlmaty.findTolerant(raw) }.getOrNull() else null',
     '        val tolerant: BRouterConnector.Point? = null // never use a neighboring house as a substitute')
# Existing geocoder fallback can still return a nearby house: require the strict identity.
edit("PlaceLookup.kt", '''            val near = local.filter { c -> c.labels.any {
                AddressMatcher.matchesLabel(order, it) == AddressMatcher.Level.NEAR
            } }
            if (near.isNotEmpty()) return cluster(near)''','''            // A different house suffix is not a valid substitute.''')
edit("RadarAccessibilityService.kt", "pipeline.calculate(newer.pickup, newer.destination) { result ->",
     "pipeline.calculate(newer.pickup, newer.destination, pickupKm = newer.pickupKm) { result ->")
print("v55 indexed multilingual names, road type and pickup context applied.")
