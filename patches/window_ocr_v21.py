from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
p=base/"RadarAccessibilityService.kt"
s=p.read_text()
s=s.replace("or capture raw screenshots.","or capture other apps. Optional local window OCR only with user consent.")
s=s.replace("    private var lastScan=0L",'''    private var ocr: WindowOcr?=null
    private var scanGeneration=0L
    private var ocrEpoch=0L
    private var lastOcr=0L
    private var ocrBusy=false
    private var lastScan=0L''')
s=s.replace("running=true;routePipeline=", "running=true;ocr=WindowOcr(this);ocrEpoch++;lastOcr=0;ocrBusy=false;routePipeline=")
s=s.replace("running=false;ui.removeCallbacks(ticker)", "running=false;ocrEpoch++;scanGeneration++;ocr?.close();ocr=null;ocrBusy=false;ui.removeCallbacks(ticker)")
a=s.index("        if(texts.isEmpty()){")
b=s.index("        if(newer.order) {",a)
s=s[:a]+'''        val visible=texts.distinct().joinToString("\\n")
        val newer=OrderTextParser.parse(visible)
        val windowChanged=event.eventType==AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
        val generation=++scanGeneration
        val incomplete=newer.pickup.isNullOrBlank() || newer.destination.isNullOrBlank() || newer.tariff==null
        val hint=visible.isBlank() || newer.order || visible.contains("Принять",true) || visible.contains("Пропустить",true)
        if(hint && (!newer.order || incomplete))tryOcr(root.windowId,generation,now,visible)
        processDetection(newer,windowChanged,now)
    }
    private fun tryOcr(windowId:Int,generation:Long,now:Long,visible:String){
        if(android.os.Build.VERSION.SDK_INT<34 || !prefs.getBoolean("ocr_allowed",false))return
        if(ocrBusy || now-lastOcr<1800L)return
        val worker=ocr ?: return
        ocrBusy=true;lastOcr=now
        val epoch=ocrEpoch
        try{
            takeScreenshotOfWindow(windowId,mainExecutor,object:TakeScreenshotCallback{
                override fun onSuccess(result:ScreenshotResult){
                    if(!running || epoch!=ocrEpoch){result.hardwareBuffer.close();return}
                    worker.recognize(result){text->
                        ui.post {
                            if(epoch!=ocrEpoch)return@post
                            ocrBusy=false
                            if(!running || text.isNullOrBlank())return@post
                            val active=rootInActiveWindow
                            if(active?.packageName?.toString()!="ru.yandex.taximeter" || active.windowId!=windowId)return@post
                            if(android.os.SystemClock.uptimeMillis()<0)return@post
                            if(System.currentTimeMillis()-now>5000L)return@post
                            if(scanGeneration!=generation && !detected.order)return@post
                            val candidate=OrderTextParser.parse(text)
                            val original=OrderTextParser.parse(visible)
                            if(!candidate.order || candidate.pickup.isNullOrBlank() || candidate.destination.isNullOrBlank() || candidate.tariff==null)return@post
                            if(original.tariff!=null && original.tariff!=candidate.tariff)return@post
                            if(original.pickup!=null && original.pickup!=candidate.pickup)return@post
                            if(original.destination!=null && original.destination!=candidate.destination)return@post
                            if(detected.order && detected.pickup!=null && detected.pickup!=candidate.pickup)return@post
                            if(detected.order && detected.destination!=null && detected.destination!=candidate.destination)return@post
                            if(detected.order && detected.tariff!=null && detected.tariff!=candidate.tariff)return@post
                            processDetection(candidate.copy(demand=original.demand ?: candidate.demand),false,System.currentTimeMillis())
                        }
                    }
                }
                override fun onFailure(errorCode:Int){if(epoch==ocrEpoch)ocrBusy=false}
            })
        }catch(e:Exception){ocrBusy=false}
    }
    private fun processDetection(newer:OrderTextParser.Detected,windowChanged:Boolean,now:Long){
'''+s[b:]
s=s.replace("} else if (event.eventType==AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {","} else if (windowChanged) {")
s=s.replace('                            if(android.os.SystemClock.uptimeMillis()<0)return@post\n','')
p.write_text(s)
(base/"WindowOcr.kt").write_text('''package kz.taxiprofitai

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Bitmap
import com.googlecode.tesseract.android.TessBaseAPI
import java.io.File
import java.util.concurrent.Executors

/** Window image and recognized text exist in memory only. Only language models are stored. */
class WindowOcr(private val context:Context) {
    private val worker=Executors.newSingleThreadExecutor()
    @Volatile private var closed=false
    private var tess:TessBaseAPI?=null
    private fun engine():TessBaseAPI {
        tess?.let{return it}
        val home=File(context.filesDir,"ocr-v1")
        val data=File(home,"tessdata").apply{mkdirs()}
        for(lang in listOf("rus","kaz","eng")){
            val name="$lang.traineddata"
            val target=File(data,name)
            if(!target.exists()){
                val tmp=File(data,"$name.tmp")
                context.assets.open("tessdata/$name").use{input->tmp.outputStream().use{input.copyTo(it)}}
                check(tmp.renameTo(target))
            }
        }
        val api=TessBaseAPI()
        if(!api.init(home.absolutePath,"rus+kaz+eng",TessBaseAPI.OEM_LSTM_ONLY)){api.recycle();error("OCR init")}
        api.setPageSegMode(TessBaseAPI.PageSegMode.PSM_SPARSE_TEXT)
        tess=api
        return api
    }
    fun recognize(result:AccessibilityService.ScreenshotResult,done:(String?)->Unit){
        val buffer=result.hardwareBuffer
        if(closed){buffer.close();done(null);return}
        try{
            worker.execute {
                var bitmap:Bitmap?=null
                var hw:Bitmap?=null
                var text:String?=null
                try{
                    if(!closed){
                        hw=Bitmap.wrapHardwareBuffer(buffer,result.colorSpace)
                        bitmap=hw?.copy(Bitmap.Config.ARGB_8888,false)
                        if(bitmap!=null && !closed){
                            val api=engine()
                            api.setImage(bitmap)
                            try {
                                val raw=api.getUTF8Text()
                                if(api.meanConfidence()>=75)text=raw
                            } finally {api.clear()}
                        }
                    }
                }catch(e:Exception){}catch(e:LinkageError){}
                finally{bitmap?.recycle();hw?.recycle();buffer.close();done(if(closed)null else text)}
            }
        }catch(e:java.util.concurrent.RejectedExecutionException){buffer.close();done(null)}
    }
    fun close(){
        closed=true
        worker.execute{tess?.recycle();tess=null}
        worker.shutdown()
    }
}
''')
p=base/"MainActivity.kt"
s=p.read_text()
s=s.replace('    private fun startRadar(){','''    private fun startRadar(){
        if(android.os.Build.VERSION.SDK_INT>=34 && !prefs.getBoolean("ocr_choice",false)){
            android.app.AlertDialog.Builder(this)
                .setTitle("Распознавание заказа")
                .setMessage("Если текст заказа недоступен, Taxi Profit AI может временно получить снимок только окна Яндекс Про. OCR выполняется на телефоне. Снимки не сохраняются и не отправляются. Разрешить?")
                .setNegativeButton("Без OCR"){_,_->prefs.edit().putBoolean("ocr_choice",true).putBoolean("ocr_allowed",false).apply();startRadar()}
                .setPositiveButton("Разрешить"){_,_->prefs.edit().putBoolean("ocr_choice",true).putBoolean("ocr_allowed",true).apply();startRadar()}
                .show()
            return
        }''')
p.write_text(s)
p=Path("app/src/main/res/xml/accessibility_service_config.xml")
p.write_text(p.read_text().replace('android:canRetrieveWindowContent="true"','android:canRetrieveWindowContent="true"\n    android:canTakeScreenshot="true"'))
p=Path("app/src/main/res/values/strings.xml")
p.write_text(p.read_text().replace("Считывает только видимый текст экрана Яндекс Про по вашему разрешению","Считывает видимый текст Яндекс Про и, только с отдельного согласия, распознаёт снимок окна на устройстве"))
p=Path("settings.gradle.kts")
p.write_text(p.read_text().replace("repositories { google(); mavenCentral() }","repositories { google(); mavenCentral(); maven { url = uri(\"https://jitpack.io\"); content { includeGroup(\"cz.adaptech.tesseract4android\") } } }"))
p=Path("app/build.gradle.kts")
p.write_text(p.read_text().replace('dependencies {','dependencies { implementation("cz.adaptech.tesseract4android:tesseract4android:4.9.0");'))
print("Local OCR sources applied")
