from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
p=base/"Engine.kt"
s=p.read_text()
a=s.index("object OrderTextParser {")
s=s[:a]+'''object OfferDemandEvidence {
    private val money=Regex("""(?<![\\p{L}\\d+])\\+\\s*(\\d{1,3}(?:[ \\u00a0\\u202f]\\d{3})+|\\d{1,7})\\s*(?:₸|тенге|тг\\.?)(?![\\p{L}\\d])""",RegexOption.IGNORE_CASE)
    private val labelled=Regex("""(?iu)надбавк|повышенн\\p{L}*\\s+спрос|доплат\\p{L}*\\s+за\\s+спрос|сұраныс|surge""")
    private val unrelated=Regex("""(?iu)бонус|чаев|приоритет|промокод|скидк|балл|bonus|tip|priority""")
    private val noAdd=Regex("""(?iu)^\\s*(?:без надбавки|надбавка отсутствует|надбавка\\s*[:]?\\s*0\\s*₸|no surge)\\s*$""")
    private fun amount(m:MatchResult)=m.groupValues[1].filter{it.isDigit()}.toLongOrNull()?.takeIf{it in 1..1_000_000}
    fun colorAmount(text:String):Long? {
        val t=text.trim()
        return money.matchEntire(t)?.let(::amount)
    }
    fun direct(text:String):Demand? {
        val lines=text.lines().map{it.trim()}
        val values=lines.flatMap{line->
            if(!unrelated.containsMatchIn(line) && labelled.containsMatchIn(line))
                money.findAll(line).mapNotNull(::amount).toList()
            else emptyList()
        }.distinct()
        val zero=lines.any{noAdd.matches(it)}
        if(values.size>1 || (zero && values.isNotEmpty()))return null
        return if(zero)Demand(DemandType.NONE,0.0,true)
        else values.singleOrNull()?.let{Demand(DemandType.FIXED_ADD,it.toDouble(),true)}
    }
    fun merge(direct:Demand?,purple:Long?):Demand? {
        if(purple==null)return direct
        if(direct!=null && (direct.type!=DemandType.FIXED_ADD || direct.amount!=purple.toDouble()))return null
        return Demand(DemandType.FIXED_ADD,purple.toDouble(),true)
    }
}

'''+s[a:]
s=s.replace("else tariff,d,t.contains", "else tariff,if(isOrder)OfferDemandEvidence.direct(t) else d,t.contains")
assert "if(isOrder)OfferDemandEvidence.direct(t)" in s
p.write_text(s)
p=base/"WindowOcr.kt"
s=p.read_text()
s=s.replace("fun recognize(result:AccessibilityService.ScreenshotResult,done:(String?)->Unit)", "data class Reading(val text:String?,val purple:Long?)\n    fun recognize(result:AccessibilityService.ScreenshotResult,done:(Reading?)->Unit)")
s=s.replace("var text:String?=null","var text:String?=null\n                var purple:Long?=null")
s=s.replace("} finally {api.clear()}\n                        }","} finally {api.clear()}\n                            purple=purpleAmount(bitmap,api)\n                        }")
s=s.replace("done(if(closed)null else text)","done(if(closed)null else Reading(text,purple))")
i=s.index("    fun close(){")
s=s[:i]+'''    // Identify saturated violet regions, then OCR only their bounded line crops.
    // Never accept an uncoloured amount, a multiplier, or a bare priority number.
    private fun purpleAmount(bitmap:Bitmap,api:TessBaseAPI):Long? {
        val w=bitmap.width;val h=bitmap.height
        if(w<40 || h<40)return null
        val row=IntArray(w)
        val left=IntArray(h){w};val right=IntArray(h){-1}
        fun violet(c:Int):Boolean{
            val r=android.graphics.Color.red(c);val g=android.graphics.Color.green(c);val b=android.graphics.Color.blue(c)
            return b>=95 && r>=70 && b-g>=32 && r-g>=15 && b>=r-22 && b<=r+125
        }
        for(y in 0 until h){
            bitmap.getPixels(row,0,w,0,y,w,1)
            var count=0
            for(x in 0 until w)if(violet(row[x])){
                if(x<left[y])left[y]=x
                right[y]=x;count++
            }
            if(count<3){left[y]=w;right[y]=-1}
        }
        val values=mutableSetOf<Long>()
        var y=0;var attempts=0
        while(y<h && attempts<8 && !closed){
            if(right[y]<0){y++;continue}
            val top=y;var l=w;var r=-1;var last=y
            while(y<h && y-last<=3){
                if(right[y]>=0){l=minOf(l,left[y]);r=maxOf(r,right[y]);last=y}
                y++
            }
            val height=last-top+1;val width=r-l+1
            if(height !in 8..(h/9).coerceAtLeast(8) || width !in 15..(w*0.75).toInt())continue
            val pad=(height/3).coerceIn(4,24)
            val x0=(l-pad).coerceAtLeast(0);val x1=(r+pad+1).coerceAtMost(w)
            val y0=(top-pad).coerceAtLeast(0);val y1=(last+pad+1).coerceAtMost(h)
            val crop=Bitmap.createBitmap(bitmap,x0,y0,x1-x0,y1-y0)
            attempts++
            try {
                api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SINGLE_LINE)
                api.setImage(crop)
                val raw=api.getUTF8Text()
                if(api.meanConfidence()>=75)OfferDemandEvidence.colorAmount(raw)?.let{values.add(it)}
            }finally{
                api.clear();api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SPARSE_TEXT)
                if(crop!==bitmap)crop.recycle()
            }
        }
        return values.singleOrNull()
    }
'''+s[i:]
assert "purple=purpleAmount(bitmap,api)" in s
p.write_text(s)
p=base/"RadarAccessibilityService.kt"
s=p.read_text()
s=s.replace("val incomplete=newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank() || newer.tariff==null","val incomplete=newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank() || newer.tariff==null || newer.demand==null")
s=s.replace("worker.recognize(result){text->","worker.recognize(result){reading->")
s=s.replace("if(!running || text.isNullOrBlank())return@post","if(!running || reading==null)return@post")
s=s.replace("val candidate=OrderTextParser.parse(text)\n                            val original=OrderTextParser.parse(visible)","""val original=OrderTextParser.parse(visible)
                            val candidate=OrderTextParser.parse(reading.text.orEmpty())
                            val merged=if(original.order && !original.pickup.isNullOrBlank() && !original.destination.isNullOrBlank() && original.tariff!=null)original else candidate
                            val demand=OfferDemandEvidence.merge(original.demand ?: candidate.demand,reading.purple)""")
s=s.replace("if(!candidate.order || candidate.pickup.isNullOrBlank() || candidate.destination.isNullOrBlank() || candidate.tariff==null)return@post","if(!merged.order || merged.pickup.isNullOrBlank() || merged.destination.isNullOrBlank() || merged.tariff==null || demand==null)return@post")
for field in ["tariff","pickup","destination"]:
    s=s.replace("!=candidate."+field,"!=merged."+field)
s=s.replace("processDetection(candidate.copy(demand=original.demand ?: candidate.demand),false,System.currentTimeMillis())","""if(!detected.order && scanGeneration!=generation)return@post
                            verifiedIdentity=OfferPopupState.identity(merged.pickup,merged.destination,merged.tariff)
                            verifiedDemand=demand;verifiedAt=System.currentTimeMillis()
                            processDetection(merged.copy(demand=demand),false,verifiedAt)""")
s=s.replace("    private var lastScan=0L","    private var verifiedIdentity:String?=null\n    private var verifiedDemand:Demand?=null\n    private var verifiedAt=0L\n    private var lastScan=0L")
s=s.replace("        routeKey=null;estimate=null;routeStatus=","        verifiedIdentity=null;verifiedDemand=null;verifiedAt=0L\n        routeKey=null;estimate=null;routeStatus=")
s=s.replace("        processDetection(newer,windowChanged,now)","""        val identity=OfferPopupState.identity(newer.pickup,newer.destination,newer.tariff)
        val reuse=if(newer.order && !windowChanged && identity==verifiedIdentity && now-verifiedAt in 0L..3000L)verifiedDemand else null
        if(windowChanged || (newer.order && identity!=verifiedIdentity)){verifiedIdentity=null;verifiedDemand=null;verifiedAt=0L}
        processDetection(newer.copy(demand=newer.demand ?: reuse),windowChanged,now)""")
s=s.replace("routeStatus=\"Адреса А/Б или тариф недоступны Android\"\n                } else {","routeStatus=\"Адреса А/Б или тариф недоступны Android\"\n                } else if(newer.demand==null){\n                    routeStatus=\"Надбавка не распознана — цена недоступна\"\n                } else {")
s=s.replace("newer.demand?:Demand(DemandType.NONE)","requireNotNull(newer.demand)")
assert "else if(newer.demand==null)" in s
s=s.replace('else -> "спрос —"','else -> "+0 ₸"')
p.write_text(s)
Path("core-tests/OfferDemandCheck.kt").write_text('''package kz.taxiprofitai
fun main(){
    fun direct(s:String)=OfferDemandEvidence.direct(s)
    check(direct("Надбавка +800 ₸")?.amount==800.0)
    check(direct("Повышенный спрос +1 500 ₸")?.amount==1500.0)
    check(direct("Приоритет +1")==null)
    check(direct("Бонус +800 ₸")==null)
    check(direct("+800 ₸")==null)
    check(direct("Надбавка +800 ₸\\nНадбавка +500 ₸")==null)
    check(direct("Без надбавки")?.type==DemandType.NONE)
    check(direct("Надбавка 0 ₸\\nНадбавка +800 ₸")==null)
    check(OfferDemandEvidence.colorAmount("+800 ₸")==800L)
    check(OfferDemandEvidence.colorAmount("+1 500 ₸")==1500L)
    check(OfferDemandEvidence.colorAmount("+1")==null)
    check(OfferDemandEvidence.colorAmount("3 000 ₸")==null)
    check(OfferDemandEvidence.colorAmount("+800 ₸ +900 ₸")==null)
    check(OfferDemandEvidence.merge(null,800L)?.amount==800.0)
    check(OfferDemandEvidence.merge(direct("Надбавка +800 ₸"),500L)==null)
    check(OfferDemandEvidence.merge(null,null)==null)
    println("16 surcharge evidence checks passed")
}
''')
print("Purple surcharge fallback applied")
