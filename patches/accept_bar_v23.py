from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
p=base/"Engine.kt"
s=p.read_text()
needle="    fun colorAmount(text:String):Long? {"
assert needle in s
s=s.replace(needle,'''    // The accept button in the Kazakhstan driver app has white currency
    // text over a purple progress bar. The isolated central amount is KZT.
    private val acceptMoney=Regex("""^\\s*\\+\\s*(\\d{1,3}(?:[ \\u00a0\\u202f]\\d{3})+|\\d{1,7})\\s*(?:₸|тенге|тг\\.?|[ТT])\\s*$""",RegexOption.IGNORE_CASE)
    fun acceptAmount(text:String):Long? = acceptMoney.matchEntire(text.trim())?.let(::amount)
    fun acceptButton(text:String):Demand? {
        val lines=text.lines().map{it.trim()}.filter{it.isNotEmpty()}
        val values=mutableSetOf<Long>()
        for(i in lines.indices){
            val line=lines[i]
            if(!line.contains("Принять",true))continue
            val inline=line.replace(Regex("Принять",RegexOption.IGNORE_CASE),"").trim()
            acceptAmount(inline)?.let{values.add(it)}
            // Some accessibility trees expose the currency and label as two nodes.
            if(inline.isEmpty())lines.getOrNull(i-1)?.let{acceptAmount(it)}?.let{values.add(it)}
        }
        return values.singleOrNull()?.let{Demand(DemandType.FIXED_ADD,it.toDouble(),true)}
    }
'''+needle)
s=s.replace("if(isOrder)OfferDemandEvidence.direct(t) else d","if(isOrder)OfferDemandEvidence.direct(t) ?: OfferDemandEvidence.acceptButton(t) else d")
# Recognize OCR card addresses when the A/B markers have been lost, only
# if two distinct address-like lines follow the pickup section.
needle='        val a = extract("А") ?: extract("A")\n        val b = extract("Б") ?: extract("B")'
assert needle in s
s=s.replace(needle,'''        val pickupIndex=addresses.indexOfFirst{it.contains("подача",true)}
        val passengerIndex=addresses.indexOfFirst{it.contains("Пассажир",true)}
        val body=if(pickupIndex>=0 && passengerIndex>pickupIndex)addresses.subList(pickupIndex+1,passengerIndex) else emptyList()
        val candidates=body.map{it.replace(Regex("^[АAБB]\\\\s*[:.)]?\\\\s+"),"").trim()}.filter{
            it.length>=7 && !TarifCatalog.titles.any{n->it.equals(n,true)} &&
            (Regex("(?iu)улица|проспект|микрорайон|переулок|шоссе|бульвар|площадь|паркинг|plaza|mall|торговый центр|ТРЦ").containsMatchIn(it) ||
                Regex("(?u),\\\\s*\\\\d+[А-Яа-яA-Za-z]?\\\\s*$").containsMatchIn(it))
        }.distinct()
        val fallback=candidates.takeIf{it.size==2 && isOrder}
        val a = extract("А") ?: extract("A") ?: fallback?.get(0)
        val b = extract("Б") ?: extract("B") ?: fallback?.get(1)''')
p.write_text(s)
p=base/"WindowOcr.kt"
s=p.read_text()
# first inspect bottom accept area before the legacy isolated violet glyph search
s=s.replace("purple=purpleAmount(bitmap,api)","purple=acceptBarAmount(bitmap,api) ?: purpleAmount(bitmap,api)")
i=s.index("    private fun purpleAmount(")
s=s[:i]+'''    private fun acceptBarAmount(bitmap:Bitmap,api:TessBaseAPI):Long? {
        val w=bitmap.width;val h=bitmap.height
        if(w<80 || h<80)return null
        val row=IntArray(w)
        var top=-1;var bottom=-1;var bestTop=-1;var bestBottom=-1
        // Detect the broad violet accept progress background in the bottom fifth.
        for(y in (h*.80f).toInt() until h){
            bitmap.getPixels(row,0,w,0,y,w,1)
            val count=row.count{c->
                val r=android.graphics.Color.red(c);val g=android.graphics.Color.green(c);val b=android.graphics.Color.blue(c)
                r>=100 && b>=140 && r-g>=70 && b-g>=90 && b>=r-25
            }
            if(count>=w*.12f){
                if(top<0)top=y
                bottom=y
                if(bottom-top>bestBottom-bestTop){bestTop=top;bestBottom=bottom}
            }else if(top>=0 && y-bottom>3){top=-1;bottom=-1}
        }
        if(bestTop<0 || bestBottom-bestTop<h*.025f || bestBottom-bestTop>h*.15f)return null
        val bh=bestBottom-bestTop+1
        // Exclude priority (+1) at the left and lightning icon at the right.
        // Upper middle line contains the amount; lower line says "Принять".
        val x0=(w*.34f).toInt();val x1=(w*.67f).toInt()
        val y0=(bestTop+bh*.14f).toInt();val y1=(bestTop+bh*.58f).toInt().coerceAtMost(h)
        if(y1<=y0)return null
        val crop=Bitmap.createBitmap(bitmap,x0,y0,x1-x0,y1-y0)
        val enlarged=Bitmap.createScaledBitmap(crop,crop.width*2,crop.height*2,true)
        try{
            api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_LINE)
            api.setImage(enlarged)
            val raw=api.getUTF8Text()
            return if(api.meanConfidence()>=70)OfferDemandEvidence.acceptAmount(raw) else null
        }finally{
            api.clear();api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SPARSE_TEXT)
            if(enlarged!==crop)enlarged.recycle()
            if(crop!==bitmap)crop.recycle()
        }
    }
'''+s[i:]
p.write_text(s)
p=base/"RadarAccessibilityService.kt"
s=p.read_text()
# Recognize amount and display independently even while route is unavailable.
old='if(!merged.order || merged.pickup.isNullOrBlank() || merged.destination.isNullOrBlank() || merged.tariff==null || demand==null)return@post'
assert old in s
s=s.replace(old,'if(!merged.order || merged.tariff==null || demand==null)return@post')
s=s.replace('val merged=if(original.order && !original.pickup.isNullOrBlank() && !original.destination.isNullOrBlank() && original.tariff!=null)original else candidate','''val merged=if(original.order)original.copy(
                                pickup=original.pickup ?: candidate.pickup,
                                destination=original.destination ?: candidate.destination,
                                tariff=original.tariff ?: candidate.tariff
                            ) else candidate''')
# Keep evidence scoped to a full stable identity, not any subsequent partial offer.
s=s.replace('identity==verifiedIdentity && now-verifiedAt','identity!=null && identity==verifiedIdentity && now-verifiedAt')
p.write_text(s)
p=base/"OfflineRoutePipeline.kt"
s=p.read_text()
old='val list=Geocoder(appContext,Locale("ru","KZ")).getFromLocationName("$raw, Алматы, Казахстан",5)'
assert old in s
s=s.replace(old,'''val geocoder=Geocoder(appContext,Locale("ru","KZ"))
            val cleaned=raw.replace(Regex("(?iu),?\\\\s*(?:выход|вход)\\\\s+на\\\\s+паркинг.*$"),"").trim()
            val queries=listOf(raw,cleaned).filter{it.isNotBlank()}.distinct()
            val list=queries.asSequence().map{q->
                runCatching{geocoder.getFromLocationName("$q, Алматы, Казахстан",5)}.getOrNull()
            }.firstOrNull{items->items?.any{it.latitude in 42.5..44.5 && it.longitude in 75.0..79.0}==true}''')
p.write_text(s)
p=base/"OfferPopupView.kt"
s=p.read_text()
s=s.replace('text(c,"Нажмите, чтобы скрыть",120f,96f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)','text(c,footer,120f,96f,14f,Color.WHITE,false,Paint.Align.CENTER,228f)')
s=s.replace('private val density=','private var footer="Нажмите, чтобы скрыть"\n    private val density=')
s=s.replace('        demandText=if(demand.startsWith("+"))demand else "—"','''        demandText=if(demand.startsWith("+"))demand else "—"
        footer=if(estimate!=null)"Нажмите, чтобы скрыть" else when{
            status.startsWith("Надбавка")->"Не считана надбавка"
            status.startsWith("Адреса")->"Не считаны адреса"
            status.startsWith("Нет маршрута")->"Нет маршрута BRouter"
            status.startsWith("Маршрут")->"Расчёт маршрута…"
            else->"Нажмите, чтобы скрыть"
        }''')
p.write_text(s)
p=Path("core-tests/OfferDemandCheck.kt")
s=p.read_text()
s=s.replace('    println("16 surcharge evidence checks passed")','''    check(OfferDemandEvidence.acceptAmount("+50 ₸")==50L)
    check(OfferDemandEvidence.acceptAmount("+50 Т")==50L)
    check(OfferDemandEvidence.acceptAmount("+1")==null)
    check(OfferDemandEvidence.acceptAmount("+1 +50 ₸")==null)
    check(OfferDemandEvidence.acceptButton("+50 ₸\\\\nПринять")?.amount==50.0)
    check(OfferDemandEvidence.acceptButton("+1\\\\nПринять")==null)
    val offer=OrderTextParser.parse("Пропустить\\\\n1,4 км · 3 мин\\\\nБлижняя подача\\\\nКомфорт+\\\\nулица Кабанбай батыра, 15\\\\nDostyk Plaza, Выход на паркинг — 2 этаж\\\\nПассажир\\\\n+1\\\\n+50 ₸\\\\nПринять")
    check(offer.order && offer.tariff=="Комфорт+" && offer.demand?.amount==50.0)
    check(offer.pickup=="улица Кабанбай батыра, 15" && offer.destination?.startsWith("Dostyk Plaza")==true)
    println("24 surcharge and address checks passed")''')
p.write_text(s)
print("Real offer layout adaptation applied")
