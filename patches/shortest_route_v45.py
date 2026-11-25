#!/usr/bin/env python3
from pathlib import Path
base=Path("app/src/main/java/kz/taxiprofitai")
def edit(p,old,new):
    s=p.read_text()
    assert s.count(old)==1,(p,old[:100])
    p.write_text(s.replace(old,new,1))
p=base/"EmbeddedRoadRouter.kt"
edit(p,'    private fun context() = RoutingContext().apply {\n        localFunction = File(data, "car-vario.brf").absolutePath',
'''    private fun context(shortest: Boolean = true) = RoutingContext().apply {
        localFunction = File(data, if (shortest) "car-shortest-znay-v45.brf" else "car-vario.brf").absolutePath''')
edit(p,'    fun route(fromLat: Double, fromLon: Double, toLat: Double, toLon: Double): OfflineRoute {',
'''    fun route(fromLat: Double, fromLon: Double, toLat: Double, toLon: Double,
              shortest: Boolean = true): OfflineRoute {''')
edit(p,'        val routing = context()\n        val engine = RoutingEngine',
'''        val routing = context(shortest)
        val engine = RoutingEngine''')
edit(p,'        engine.doRun(2_000)','        engine.doRun(if (shortest) 3_000 else 2_000)')
edit(p,'return OfflineRoute(result.distance / 1000.0, result.totalSeconds / 60.0,\n            geometry = points,',
'''return OfflineRoute(result.distance / 1000.0, result.totalSeconds / 60.0,
            source = if (shortest) "BRouter · минимум км" else "BRouter · обычный профиль",
            geometry = points,''')
p=base/"BRouterConnector.kt"
edit(p,'listOf("car-vario.brf", "lookups.dat", "E75_N40.rd5")','listOf("car-vario.brf", "car-shortest-znay-v45.brf", "lookups.dat", "E75_N40.rd5")')
# Do not silently substitute a longer profile for a failed shortest search.
# Tests compare both objectives on the same actual map and endpoints.
p=Path("core-tests/EmbeddedRouterCheck.kt")
edit(p,'            check(result.geometry.size >= 2)',
'''            val previous = engine.route(row[0], row[1], row[2], row[3], shortest = false)
            check(result.km <= previous.km + 0.05) {
                "Distance objective is longer: " + result.km + " vs " + previous.km
            }
            println("Distance-first: " + result.km + " km; previous: " + previous.km + " km")
            check(result.geometry.size >= 2)''')
# Store the routing source together with the trace.
p=base/"RouteTraceStore.kt"
edit(p,'d.put("plan", encode(raw.geometry)).put("rawKm", raw.km).put("rawMinutes",raw.minutes)',
'''d.put("plan", encode(raw.geometry)).put("rawKm", raw.km).put("rawMinutes",raw.minutes)
            .put("profile", raw.source)''')
edit(p,'text="Синий — BRouter; зелёный — GPS\\n" +',
'''text="Синий — BRouter; зелёный — GPS\\n" +
                "Профиль: " + d.optString("profile", "неизвестен") + "\\n" +''')
