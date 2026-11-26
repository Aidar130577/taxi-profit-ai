"""Preserve EV as a calculation fallback, but separate it from a confirmed tariff."""
from pathlib import Path
root=Path("app/src/main/java/kz/taxiprofitai")
def edit(name, old, new):
    p=root/name
    s=p.read_text()
    assert s.count(old)==1,(name,old,s.count(old))
    p.write_text(s.replace(old,new,1))

edit("Engine.kt", 'val trialId: Long? = null)', 'val trialId: Long? = null, val assumedEv: Boolean = false)')
edit("Engine.kt", 'if (isOrder && !cardOnly) TripBadgeReader.read(t) else null)', '''if (isOrder && !cardOnly) TripBadgeReader.read(t) else null,
            assumedEv = isOrder && !unsupported && explicitTariff == null && tariff == "Электро")''')

edit("OfferPopupView.kt", '    private val logicalHeight get() = if (waiting) 38 else if (hasQuote) 96 else 116', '''    private var assumedEv = false
    private val logicalHeight get() = if (waiting) 38 else (if (hasQuote) 96 else 116) + if (assumedEv) 36 else 0''')
edit("OfferPopupView.kt", 'destinationAddress:String?, paidPickup: Long?){', 'destinationAddress:String?, paidPickup: Long?, assumedEv: Boolean = false){')
edit("OfferPopupView.kt", '        hasQuote = estimate != null\n', '        hasQuote = estimate != null\n        this.assumedEv = assumedEv\n')
edit("OfferPopupView.kt", '''        c.restore()
        if (hasQuote) onPriceDrawn?.invoke()''', '''        if (assumedEv) {
            val y = if (hasQuote) 96f else 116f
            line(c,y)
            text(c,"Возможно корпоративный",120f,y+15f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)
            text(c,"или Fasten",120f,y+30f,15f,Color.WHITE,false,Paint.Align.CENTER,228f)
        }
        c.restore()
        if (hasQuote) onPriceDrawn?.invoke()''')
edit("RadarAccessibilityService.kt", 'CommissionSettings.park(prefs), detected.pickup, detected.destination, detected.pickupExtra)', 'CommissionSettings.park(prefs), detected.pickup, detected.destination, detected.pickupExtra, detected.assumedEv)')
# A provisional EV is still a useful fare comparison, but never a labelled EV training sample.
edit("LocalFareLearning.kt", '    val yandexTimeWeight: Double? = null\n)', '    val yandexTimeWeight: Double? = null,\n    val assumedEv: Boolean = false\n)')
edit("TrialStore.kt", '                    obj.optDouble("yandexTimeWeight").takeIf(Double::isFinite)\n', '                    obj.optDouble("yandexTimeWeight").takeIf(Double::isFinite),\n                    obj.optBoolean("assumedEv", obj.optString("tariff") == "Электро")\n')
edit("TrialStore.kt", '            r.yandexTimeWeight?.let { j.put("yandexTimeWeight", it) }\n', '            r.yandexTimeWeight?.let { j.put("yandexTimeWeight", it) }\n            j.put("assumedEv", r.assumedEv)\n')
edit("TrialStore.kt", 'provisional: Boolean = false): Long {', 'provisional: Boolean = false, assumedEv: Boolean = false): Long {')
edit("TrialStore.kt", 'provisional = provisional)\n', 'provisional = provisional, assumedEv = assumedEv)\n')
edit("RadarAccessibilityService.kt", 'knownSurcharge(offer), offlineMinutes, weather, knownMultiplier(offer), offlineKm, provisional)', 'knownSurcharge(offer), offlineMinutes, weather, knownMultiplier(offer), offlineKm, provisional, offer.assumedEv)')
edit("TrialStore.kt", 'fixed: Double?, multiplier: Double?): Long {', 'fixed: Double?, multiplier: Double?, assumedEv: Boolean = false): Long {')
edit("TrialStore.kt", 'demandMultiplier = multiplier)\n', 'demandMultiplier = multiplier, assumedEv = assumedEv)\n')
edit("RadarAccessibilityService.kt", 'knownSurcharge(quote), knownMultiplier(quote)).also(tripProgress::attachTrial)', 'knownSurcharge(quote), knownMultiplier(quote), quote.assumedEv).also(tripProgress::attachTrial)')
edit("LearnedRates.kt", '!it.excluded && it.tariff == rate.title', '!it.excluded && !it.assumedEv && it.tariff == rate.title')
# Guard against invalid or late road result causing a quote failure.
edit("RadarAccessibilityService.kt", 'DualFareMean.combinedRoute(badgeRoute, route, DualFareMean.fixedDemand(newer.demand)) else null', 'runCatching { DualFareMean.combinedRoute(badgeRoute, route, DualFareMean.fixedDemand(newer.demand)) }.getOrNull() else null')
p=Path("core-tests/OfferDemandCheck.kt")
s=p.read_text()
import re
m=re.search(r'(?m)^fun main\s*\([^)]*\)\s*\{',s)
assert m is not None
a=m.group(0)
s=s.replace(a,a+'''
    val unknownPassenger = "Пропустить\\nБлижняя подача\\nА: Абая, 10\\nБ: Достык, 50\\nПассажир\\nПринять"
    check(OrderTextParser.parse(unknownPassenger).assumedEv)
    check(OrderTextParser.parse(unknownPassenger).tariff == "Электро")
    check(!OrderTextParser.parse(unknownPassenger.replace("Пассажир","Электро\\nПассажир")).assumedEv)
    check(!OrderTextParser.parse(unknownPassenger.replace("Пассажир","Комфорт+\\nПассажир")).assumedEv)
    check(!OrderTextParser.parse("Пассажир").assumedEv)
''',1)
p.write_text(s)
print("Passenger warning and conservative EV learning labels applied.")
