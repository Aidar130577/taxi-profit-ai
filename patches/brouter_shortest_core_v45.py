#!/usr/bin/env python3
"""Add a distance objective to pinned BRouter 1.7.10 without discarding its car ETA model."""
from pathlib import Path
import sys
root=Path(sys.argv[1])
def replace(p,old,new):
    s=p.read_text()
    assert s.count(old)==1,(str(p),old[:100])
    p.write_text(s.replace(old,new,1))
model=root/"brouter-core/src/main/java/btools/router/KinematicModel.java"
path=root/"brouter-core/src/main/java/btools/router/KinematicPath.java"
replace(model,"  public double turnAngleDecayTime;","  public boolean shortestDistance;\n  public double turnAngleDecayTime;")
replace(model,'    turnAngleDecayTime = getParam("turnAngleDecayTime", 5.f);',
    '    shortestDistance = getParam("shortest_distance", 0.f) != 0.f;\n    turnAngleDecayTime = getParam("turnAngleDecayTime", 5.f);')
replace(path,"    cost += distanceCost;\n\n    return cost;",
    """    cost += distanceCost;

    // ZnayTsenu distance objective. Keep the speed/energy integration above for ETA.
    // OsmPath still enforces forbidden ways, turn restrictions and destination access.
    if (km.shortestDistance) {
      if (cf >= 9999.f || distanceCost < 0.) return -1.;
      return dist * Math.max(1.f, cf) + 0.5f;
    }
    return cost;""")
# In the search phase (no detail message), do not evaluate vehicle dynamics on
# discarded alternatives. The guided retrace sets message and computes real ETA.
replace(path, "    double cost = 0.;\n    double extraTime = 0.;",
    """    if (km.shortestDistance && message == null) {
      float cf = rc.expctxWay.getCostfactor();
      if (cf >= 9999.f || km.getWayMaxspeed() <= 0.f) return -1.;
      return dist * Math.max(1.f, cf) + 0.5f;
    }

    double cost = 0.;
    double extraTime = 0.;""")
# Skip construction of crossing/turn slowdown hints during the distance-only
# search; leave the regular link loading and detailed ETA pass intact.
engine=root/"brouter-core/src/main/java/btools/router/RoutingEngine.java"
replace(engine, "          OsmPrePath prePath = routingContext.createPrePath(path, link);",
    """          if (guideTrack == null && routingContext.pm instanceof KinematicModel
              && ((KinematicModel) routingContext.pm).shortestDistance) continue;
          OsmPrePath prePath = routingContext.createPrePath(path, link);""")
# A distinct profile filename avoids stale extracted profiles on upgrades.
profile=root/"misc/profiles2/car-vario.brf"
s=profile.read_text()
assert s.count("assign pass1coefficient    = 1.3")==1
s=s.replace("assign pass1coefficient    = 1.3",
            "assign pass1coefficient    = 1.0\nassign pass2coefficient = -1\nassign shortest_distance = 1\nassign considerTurnRestrictions = 1")
# Keep ferry / access / motorway / toll constraints and node barriers.
# Disable turn-by-turn hints, speed-profile and display-only outputs.
assert s.count("assign turnInstructionMode          = 1")==1
s=s.replace("assign turnInstructionMode          = 1","assign turnInstructionMode          = 0")
# Prefer through streets to service/living-street shortcuts; keep legal local access.
# Multipliers are search costs, NOT artificial increases in physical distance or ETA.
# A finite penalty permits the unavoidable first/last local access.
old = "  add no_river_penalty\n  0\n"
new = """  add no_river_penalty
  switch highway=service|living_street 8
  switch highway=residential 1.8
  switch highway=track|road|path 12
  switch highway=unclassified 1.15
  1
"""
assert s.count(old)==1
s=s.replace(old,new,1)
profile.with_name("car-shortest-znay-v45.brf").write_text(s)
