from pathlib import Path
p=Path("app/src/main/java/kz/taxiprofitai/MainActivity.kt")
s=p.read_text()
def replace(old,new):
    global s
    assert s.count(old)==1, old[:100]
    s=s.replace(old,new,1)
replace('import android.graphics.Color','''import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.content.res.ColorStateList
import android.view.View''')
replace('    private lateinit var refresh: Spinner','''    private lateinit var refresh: Spinner
    private lateinit var permissionState: TextView
    private lateinit var advanced: LinearLayout
    private lateinit var more: Button
    private lateinit var stop: Button
    private val gold=Color.rgb(255,225,0)
    private val dark=Color.rgb(16,28,33)
    private val panel=Color.rgb(32,48,56)
    private val muted=Color.rgb(176,190,198)
    private fun dp(v:Int)=(v*resources.displayMetrics.density+0.5f).toInt()
    private fun rounded(fill:Int, stroke:Int=Color.TRANSPARENT, radius:Int=10)=GradientDrawable().apply {
        setColor(fill);cornerRadius=dp(radius).toFloat()
        if(stroke!=Color.TRANSPARENT)setStroke(dp(1),stroke)
    }
    private fun label(t:String,size:Float=15f,color:Int=Color.WHITE,bold:Boolean=false)=TextView(this).apply {
        text=t;textSize=size;setTextColor(color)
        if(bold)setTypeface(typeface,Typeface.BOLD)
    }
    private fun action(t:String,primary:Boolean=false,click:()->Unit)=Button(this).apply {
        text=t;textSize=14f;isAllCaps=false;setTypeface(typeface,Typeface.BOLD)
        setTextColor(if(primary)dark else Color.WHITE)
        background=rounded(if(primary)gold else panel,if(primary)gold else Color.rgb(74,92,100))
        minimumHeight=dp(44);minHeight=dp(44);setPadding(dp(10),dp(6),dp(10),dp(6))
        setOnClickListener{click()}
    }
    private fun space(parent:LinearLayout,h:Int=8){parent.addView(View(this),LinearLayout.LayoutParams(1,dp(h)))}
    private fun styleCheck(c:CheckBox){
        c.textSize=14f;c.setTextColor(Color.WHITE);c.buttonTintList=ColorStateList(
            arrayOf(intArrayOf(android.R.attr.state_checked),intArrayOf()),intArrayOf(gold,muted))
        c.minHeight=dp(42)
    }
    private fun styleField(e:EditText){
        e.setTextColor(Color.WHITE);e.setHintTextColor(muted);e.backgroundTintList=ColorStateList.valueOf(gold)
    }
    private fun updatePermission(){
        if(!::permissionState.isInitialized)return
        val enabled=accessibilityEnabled()
        permissionState.text=if(enabled)"Включено" else "Не включено"
        permissionState.setTextColor(if(enabled)Color.rgb(162,255,151) else gold)
        stop.visibility=if(prefs.getBoolean("shift_active",false))View.VISIBLE else View.GONE
    }
    override fun onResume(){super.onResume();updatePermission()}''')
a=s.index('        val scroll = ScrollView(this)')
b=s.index('        title("Комиссия Яндекса по каждому тарифу',a)
s=s[:a]+'''        window.statusBarColor=dark
        window.navigationBarColor=dark
        window.decorView.systemUiVisibility=0
        val scroll=ScrollView(this).apply {setBackgroundColor(dark);isFillViewport=true}
        val root=LinearLayout(this).apply {
            orientation=LinearLayout.VERTICAL;setPadding(dp(14),dp(10),dp(14),dp(12))
            setBackgroundColor(dark);isFocusableInTouchMode=true
        }
        val heading=label("TAXI PROFIT AI",23f,gold,true).apply {gravity=Gravity.CENTER}
        root.addView(heading)
        space(root,8)
        val permission=LinearLayout(this).apply {
            orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL
            setPadding(dp(10),dp(8),dp(10),dp(8));background=rounded(panel)
        }
        val permText=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL}
        permText.addView(label("Разрешения Android",15f,Color.WHITE,true))
        permissionState=label("Проверка…",13f,gold)
        permText.addView(permissionState)
        permission.addView(permText,LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f))
        permission.addView(action("Открыть"){openPermissions()})
        root.addView(permission)
        space(root,10)
        root.addView(label("Выбери свои тарифы",16f,Color.WHITE,true))
        space(root,4)
        val selectedDefault=TarifCatalog.defaultSelected
        TarifCatalog.radarOrder.chunked(2).forEach {names ->
            val row=LinearLayout(this).apply {orientation=LinearLayout.HORIZONTAL}
            names.forEachIndexed {i,name ->
                val c=CheckBox(this).apply {
                    text="${TarifCatalog.shortName(name)} · $name"
                    isChecked=prefs.getBoolean("tariff_$name",name in selectedDefault)
                }
                styleCheck(c);c.background=rounded(panel)
                checks[name]=c
                row.addView(c,LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f).apply {
                    if(i==0)marginEnd=dp(6)
                })
            }
            root.addView(row);space(root,4)
        }
        airport=CheckBox(this).apply {text="✈ Радар аэропорта";isChecked=prefs.getBoolean("airport",true)}
        styleCheck(airport);root.addView(airport)
        val parkRow=LinearLayout(this).apply {orientation=LinearLayout.HORIZONTAL;gravity=Gravity.CENTER_VERTICAL}
        parkRow.addView(label("Комиссия таксопарка",15f),LinearLayout.LayoutParams(0,ViewGroup.LayoutParams.WRAP_CONTENT,1f))
        park=EditText(this).apply {
            setSingleLine(true);inputType=android.text.InputType.TYPE_CLASS_NUMBER or android.text.InputType.TYPE_NUMBER_FLAG_DECIMAL
            setText(prefs.getString("park","1"));textSize=16f;gravity=Gravity.CENTER
        }
        styleField(park)
        parkRow.addView(park,LinearLayout.LayoutParams(dp(66),ViewGroup.LayoutParams.WRAP_CONTENT))
        parkRow.addView(label("%",15f));root.addView(parkRow)
        space(root,6)
        more=action("⚙ Дополнительные настройки  ›"){
            val show=advanced.visibility!=View.VISIBLE
            advanced.visibility=if(show)View.VISIBLE else View.GONE
            more.text=if(show)"⚙ Дополнительные настройки  ⌄" else "⚙ Дополнительные настройки  ›"
        }
        root.addView(more);space(root,8)
        root.addView(action("OK · ЗАПУСТИТЬ РАДАР",true){
            if(save()){
                if(checks.values.none{it.isChecked})Toast.makeText(this,"Выберите хотя бы один тариф",Toast.LENGTH_SHORT).show()
                else if(!accessibilityEnabled())openPermissions()
                else {
                    prefs.edit().putBoolean("shift_active",true).apply()
                    updatePermission()
                    moveTaskToBack(true)
                }
            }
        },LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,dp(48)))
        stop=action("Завершить смену"){
            prefs.edit().putBoolean("shift_active",false).apply()
            updatePermission()
            Toast.makeText(this,"Смена завершена",Toast.LENGTH_SHORT).show()
        }
        root.addView(stop);stop.visibility=View.GONE
        advanced=LinearLayout(this).apply {
            orientation=LinearLayout.VERTICAL;visibility=View.GONE;setPadding(0,dp(12),0,0)
        }
        root.addView(advanced)
        val col=advanced
        fun title(t:String,size:Float=17f){space(col,8);col.addView(label(t,size,gold,true))}
        fun button(t:String,onClick:()->Unit){space(col,5);col.addView(action(t,false,onClick))}
'''.replace('\\${','${')+s[b:]
replace('        scroll.addView(col)\n        setContentView(scroll)','''        fun recolor(v:View){
            if(v is EditText)styleField(v)
            else if(v is TextView && v !is Button && v !is CheckBox && v.currentTextColor!=gold)v.setTextColor(muted)
            if(v is ViewGroup)for(i in 0 until v.childCount)recolor(v.getChildAt(i))
        }
        recolor(advanced)
        scroll.addView(root)
        setContentView(scroll)
        root.requestFocus()
        updatePermission()''')
replace('    private fun accessibilityEnabled():Boolean {','''    private fun openPermissions(){
        android.app.AlertDialog.Builder(this)
            .setTitle("Разрешение Android")
            .setMessage("Откройте «Основные» → «Скачанные приложения» → Taxi Profit AI. Включите службу, затем вернитесь сюда и нажмите OK. Служба читает доступный текст Яндекс Про и отображает радар. Разрешение можно отключить в любой момент.")
            .setNegativeButton("Отмена",null)
            .setPositiveButton("Открыть настройки"){_,_->startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))}
            .show()
    }
    private fun accessibilityEnabled():Boolean {''')
replace('        button("Включить чтение видимой карточки и накладку") {\n            if(!save())return@button\n            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))\n            Toast.makeText(this,"В настройках Android включите службу Taxi Profit AI",Toast.LENGTH_LONG).show()\n        }\n','')
p.write_text(s)
print("Simplified main screen applied")
