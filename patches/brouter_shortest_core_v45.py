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
# A distinct profile filename avoids stale extracted profiles on upgrades.
profile=root/"misc/profiles2/car-vario.brf"
s=profile.read_text()
assert s.count("assign pass1coefficient    = 1.3")==1
s=s.replace("assign pass1coefficient    = 1.3",
            "assign pass1coefficient    = 1.0\nassign shortest_distance = 1\nassign considerTurnRestrictions = 1")
# Keep ferry / access / motorway / toll constraints and node barriers.
profile.with_name("car-shortest-znay-v45.brf").write_text(s)
