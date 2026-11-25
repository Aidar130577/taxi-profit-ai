from pathlib import Path

source = Path("app/src/main/java/kz/taxiprofitai")


def replace(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Expected one match: {old[:100]}")
    return text.replace(old, new, 1)


def replace_block(text, start, end, new=""):
    first = text.index(start)
    after = text.index(end, first + len(start))
    return text[:first] + new + text[after:]


path = source / "RadarAccessibilityService.kt"
service = path.read_text()
service = replace(service, "import android.graphics.Color\n", "")
for declaration in (
    "    private val radar=RadarMemory()\n",
    "    private var badge: RadarPanelView?=null\n",
    "    private var params: WindowManager.LayoutParams?=null\n",
    "    private var lastRadar=0L\n",
    "    private var popupParams: WindowManager.LayoutParams?=null\n",
    "    private var popupDragged=false\n",
    "    private var panelScale=1f\n",
):
    service = replace(service, declaration, "")
service = replace(
    service, "    private var lastScan=0L\n",
    """    private var lastScan = 0L
    private var routeGeneration = 0L
    private var windowChangedSinceScan = false
    private val driverPackage = "ru.yandex.taximeter"
    private val scan = Runnable { scanActiveWindow() }
""",
)
service = replace_block(
    service, "    private val ticker=", "    override fun onServiceConnected()",
    """    private val settingsListener=android.content.SharedPreferences.OnSharedPreferenceChangeListener { _,key ->
        if (key == "shift_active") {
            if (prefs.getBoolean("shift_active", false)) startShift() else stopShift()
        }
    }
""",
)
service = replace_block(
    service, "    private fun clampPanel(", "    private fun closeOffer()",
    """    private fun startShift() {
        if (running || !::windows.isInitialized) return
        running = true
        ocr = WindowOcr(this)
        ocrEpoch++
        lastOcr = 0
        ocrBusy = false
        routePipeline = OfflineRoutePipeline(this)
        lastScan = 0
        scanActiveWindow(retryIfMissing = true)
    }

    private fun stopShift() {
        running = false
        ui.removeCallbacks(scan)
        windowChangedSinceScan = false
        ocrEpoch++
        scanGeneration++
        ocr?.close()
        ocr = null
        ocrBusy = false
        closeOffer()
        hideFarePopup()
        if (::routePipeline.isInitialized) routePipeline.close()
    }

    private fun showFarePopup() {
        if (popup != null) return
        val panel = OfferPopupView(this)
        val layout = WindowManager.LayoutParams(
            minOf(dp(240), screenWidth()), WindowManager.LayoutParams.WRAP_CONTENT,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
            PixelFormat.TRANSLUCENT
        ).apply { gravity = Gravity.TOP or Gravity.START }
        val maxX = (screenWidth() - layout.width).coerceAtLeast(0)
        val maxY = (screenHeight() - dp(112)).coerceAtLeast(0)
        layout.x = prefs.getInt("calculator_x", ((screenWidth() - layout.width) / 2)).coerceIn(0, maxX)
        layout.y = prefs.getInt("calculator_y", dp(96)).coerceIn(0, maxY)
        val slop = ViewConfiguration.get(this).scaledTouchSlop
        var touchX = 0f
        var touchY = 0f
        var initialX = 0
        var initialY = 0
        var moving = false
        panel.setOnClickListener {
            offerPopupState.dismiss()
            render()
        }
        panel.setOnTouchListener { _, event ->
            when (event.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    touchX = event.rawX
                    touchY = event.rawY
                    initialX = layout.x
                    initialY = layout.y
                    moving = false
                    true
                }
                MotionEvent.ACTION_MOVE -> {
                    if (abs(event.rawX - touchX) > slop || abs(event.rawY - touchY) > slop) moving = true
                    if (moving) {
                        layout.x = (initialX + (event.rawX - touchX).toInt()).coerceIn(0, maxX)
                        layout.y = (initialY + (event.rawY - touchY).toInt()).coerceIn(0, maxY)
                        windows.updateViewLayout(panel, layout)
                    }
                    true
                }
                MotionEvent.ACTION_UP -> {
                    if (moving) prefs.edit().putInt("calculator_x", layout.x).putInt("calculator_y", layout.y).apply()
                    else panel.performClick()
                    true
                }
                MotionEvent.ACTION_CANCEL -> true
                else -> false
            }
        }
        popup = panel
        windows.addView(panel, layout)
    }

    private fun hideFarePopup() {
        popup?.let { windows.removeView(it) }
        popup = null
    }

""",
)
service = replace(
    service, "        offerPopupState.clear()\n        hideFarePopup()",
    "        routeGeneration++\n        offerPopupState.clear()",
)
service = replace_block(
    service, "    override fun onAccessibilityEvent(", "        val texts=mutableListOf<String>()",
    """    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event == null || !running) return
        val windowChanged = event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED
        if (event.packageName?.toString() != driverPackage && !windowChanged) return
        windowChangedSinceScan = windowChangedSinceScan || windowChanged
        if (windowChanged) {
            ui.removeCallbacks(scan)
            scanActiveWindow(retryIfMissing = true)
        } else if (!ui.hasCallbacks(scan)) {
            val elapsed = android.os.SystemClock.elapsedRealtime() - lastScan
            ui.postDelayed(scan, (450L - elapsed).coerceAtLeast(0L))
        }
    }

    private fun scanActiveWindow(retryIfMissing: Boolean = false) {
        if (!running) return
        val root = rootInActiveWindow
        if (root == null) {
            if (!ui.hasCallbacks(scan)) ui.postDelayed(scan, 250L)
            return
        }
        val windowChanged = windowChangedSinceScan
        windowChangedSinceScan = false
        if (root.packageName?.toString() != driverPackage) {
            if (popup != null) {
                scanGeneration++
                closeOffer()
                hideFarePopup()
            }
            return
        }
        showFarePopup()
        lastScan = android.os.SystemClock.elapsedRealtime()
        val now = System.currentTimeMillis()
""",
)
service = replace(service, '        val root=rootInActiveWindow\n        if(root?.packageName?.toString()!="ru.yandex.taximeter")return\n', "")
service = replace(service, "        val windowChanged=event.eventType==AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED\n", "")
service = replace(service, "processDetection(newer.copy(demand=newer.demand ?: reuse),windowChanged,now)", "processDetection(newer.copy(demand=newer.demand ?: reuse),windowChanged)")
service = replace(service, "processDetection(merged.copy(demand=demand),false,verifiedAt)", "processDetection(merged.copy(demand=demand),false)")
service = replace(service, "windowChanged:Boolean,now:Long){", "windowChanged:Boolean){")
service = replace(service, "                routeKey=key;estimate=null", "                routeKey=key;estimate=null\n                val generation = ++routeGeneration")
service = replace(service, "                    val thisKey=key\n", "")
service = replace(service, "if (!running || routeKey!=thisKey)return@calculate", "if (!running || routeGeneration != generation) return@calculate")
service = replace_block(
    service, "        val interval=prefs.getInt", "            val demand=detected.demand",
    """        render()
    }

    private fun render() {
        val panel = popup ?: return
        if (detected.order && offerPopupState.shouldShow()) {
""",
)
service = replace(service, "            popup?.showQuote(", "            panel.showQuote(")
service = replace(service, "        } else hideFarePopup()\n        movePopupNextToRadar()", "        } else panel.showWaiting()")
# The project supports Android 8, while Handler.hasCallbacks requires Android 10.
service = replace(service, "    private val scan = Runnable { scanActiveWindow() }", """    private var scanScheduled = false
    private val scan = Runnable {
        scanScheduled = false
        scanActiveWindow()
    }
    private fun scheduleScan(delay: Long) {
        if (scanScheduled) return
        scanScheduled = true
        ui.postDelayed(scan, delay)
    }
    private fun cancelScan() {
        ui.removeCallbacks(scan)
        scanScheduled = false
    }""")
service = replace(service, "        ui.removeCallbacks(scan)\n        windowChangedSinceScan", "        cancelScan()\n        windowChangedSinceScan")
service = replace(service, "            ui.removeCallbacks(scan)\n            scanActiveWindow(retryIfMissing = true)\n        } else if (!ui.hasCallbacks(scan)) {", "            cancelScan()\n            scanActiveWindow(retryIfMissing = true)\n        } else {")
service = replace(service, "            ui.postDelayed(scan, (450L - elapsed).coerceAtLeast(0L))", "            scheduleScan((450L - elapsed).coerceAtLeast(0L))")
service = replace(service, "            if (!ui.hasCallbacks(scan)) ui.postDelayed(scan, 250L)", "            if (retryIfMissing) scheduleScan(250L)")
service = replace(
    service, "            if (nonOrderSnapshots>=2) closeOffer()",
    "            if (nonOrderSnapshots >= 2) closeOffer() else scheduleScan(450L)",
)
path.write_text(service)
(source / "RadarPanelView.kt").unlink()

path = source / "OfferPopupView.kt"
view = path.read_text()
view = replace(view, "/** Approved 240×104 fare overlay; separate from persistent radar. */", "/** Single overlay that expands from waiting to the fare for the current order. */")
view = replace_block(view, "    private var footer=", "    private fun text(", """    private var footer="Нажмите, чтобы свернуть"
    private val density=resources.displayMetrics.density
    private var waiting = true

    init {
        isClickable = true
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
        contentDescription = "Ждём заказ"
    }

    override fun onMeasure(w: Int, h: Int) {
        val width = resolveSize((240 * density).toInt(), w)
        val height = (if (waiting) 38 else 104) * width / 240
        setMeasuredDimension(width, resolveSize(height, h))
    }

    fun showWaiting() {
        if (waiting) return
        waiting = true
        contentDescription = "Ждём заказ"
        requestLayout()
        invalidate()
    }

""")
view = replace_block(view, "        super.onDraw(c);", "        text(c,title", """        super.onDraw(c)
        c.save()
        val logicalHeight = if (waiting) 38f else 104f
        c.scale(width / 240f, height / logicalHeight)
        val border = RectF(1f, 1f, 239f, logicalHeight - 1f)
        paint.style = Paint.Style.FILL
        paint.color = Color.rgb(22, 32, 39)
        c.drawRoundRect(border, 7f, 7f, paint)
        paint.style = Paint.Style.STROKE
        paint.strokeWidth = 2f
        paint.color = yellow
        c.drawRoundRect(border, 7f, 7f, paint)
        if (waiting) {
            text(c, "Ждём заказ", 120f, 25f, 17f, Color.WHITE, true, Paint.Align.CENTER, 228f)
            c.restore()
            return
        }
""")
view = replace(view, "        title=when(tariff)", """        if (waiting) {
            waiting = false
            requestLayout()
        }
        title=when(tariff)""")
view = view.replace("Нажмите, чтобы скрыть", "Нажмите, чтобы свернуть")
view = replace(view, 'status.startsWith("Маршрут")->"Расчёт маршрута…"', 'status.startsWith("Маршрут")->"Считаем…"')
path.write_text(view)

path = source / "OfferPopupState.kt"
state = path.read_text()
state = replace(state, "/** Controls only the separate fare popup, not the persistent radar overlay.", "/** Controls whether the single overlay shows the current offer or waits.")
path.write_text(state)

path = source / "MainActivity.kt"
activity = path.read_text()
for declaration in (
    "    private val checks = linkedMapOf<String,CheckBox>()\n",
    "    private lateinit var airport: CheckBox\n",
    "    private lateinit var refresh: Spinner\n",
    "    private lateinit var advanced: LinearLayout\n",
    "    private lateinit var more: Button\n",
):
    activity = replace(activity, declaration, "")
activity = replace_block(activity, "    private fun styleCheck(", "    private fun styleField(")
activity = replace_block(activity, '        root.addView(label("Мои тарифы"', "        val parkRow=")
activity = replace(activity, '        root.addView(action("OK · ЗАПУСТИТЬ РАДАР",true){', '        root.addView(action("Включить калькулятор",true){')
activity = replace_block(
    activity, "                if(checks.values.none", "                else {",
    "                if(!accessibilityEnabled())openPermissions()\n",
)
activity = replace(
    activity, "        scroll.addView(root)",
    """        stop=action("Выключить калькулятор"){
            prefs.edit().putBoolean("shift_active",false).apply()
            updatePermission()
        }
        root.addView(stop)
        scroll.addView(root)""",
)
activity = replace(
    activity, "        permissionState.setTextColor(if(enabled)Color.rgb(162,255,151) else gold)",
    """        permissionState.setTextColor(if(enabled)Color.rgb(162,255,151) else gold)
        stop.visibility = if (prefs.getBoolean("shift_active",false)) View.VISIBLE else View.GONE""",
)
activity = replace(activity, "checks.keys.mapNotNull { CommissionSettings.percent(prefs,it) }", "TarifCatalog.titles.mapNotNull { CommissionSettings.percent(prefs,it) }")
activity = replace(activity, '            checks.forEach{(name,c)->putBoolean("tariff_$name",c.isChecked)}\n', "")
activity = replace(activity, '            putBoolean("airport",airport.isChecked)\n', "")
activity = activity.replace("startRadar()", "startCalculator()")
activity = replace(activity, '            prefs.edit().putBoolean("shift_active",true).apply()\n            moveTaskToBack(true)', '            prefs.edit().putBoolean("shift_active",true).apply()\n            updatePermission()\n            moveTaskToBack(true)')
activity = replace(activity, "Без него можно проверить радар, но прогноз цены недоступен.", "Без BRouter приложение покажет карточку заказа, но маршрут и прогноз цены будут недоступны.")
activity = replace(activity, 'setNegativeButton("Только радар")', 'setNegativeButton("Включить без маршрута")')
activity = replace(activity, "нажмите OK. Служба читает доступный текст Яндекс Про и отображает радар.", "включите калькулятор. Служба читает доступный текст карточки заказа в Яндекс Про и показывает расчёт.")
path.write_text(activity)

path = Path("app/src/main/res/xml/accessibility_service_config.xml")
config = path.read_text()
config = replace(config, '    android:packageNames="ru.yandex.taximeter"\n', "")
path.write_text(config)

path = Path("app/src/main/res/values/strings.xml")
strings = path.read_text()
path.write_text(replace(strings, "показывает тариф и спрос.", "показывает расчёт поездки."))
print("Calculator overlay replaces city and airport radar")
