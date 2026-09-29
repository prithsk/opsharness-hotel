"""Tests for the hotel world.

WorldContract (from the opsharness core) checks the generic promises: the
correct plan scores 1.0, doing nothing scores 0.0, approvals get enforced,
the harness survives injected model slips, and the world scores 1.0 over MCP.
The wrong agents below are hotel-specific mistakes a real model could make,
and each one has to lose points.
"""
import unittest

from opsharness.testing import WorldContract, play, strip_approvals
from opsharness_hotel.world import HotelEnv

SEEDS = range(100)


class Contract(WorldContract, unittest.TestCase):
    world = HotelEnv


class WrongAgents(unittest.TestCase):
    def test_hotel_wrong_event_space(self):
        for s in SEEDS:
            env = HotelEnv(s)
            biggest = "Grand Hall" if env.truth_space != "Grand Hall" else "Fyris"
            plan = [(t, a) for t, a in env.oracle_plan() if t not in ("hold_event_space",)]
            plan = [(t, a) for t, a in plan if not (t == "request_approval" and a["tool"] == "hold_event_space")]
            if biggest not in env.booked:
                plan += env.gated_call("hold_event_space", {"rfp_id": env.rfp["id"], "space": biggest})
            self.assertLess(play(env, plan)["score"], 1.0, f"seed {s}")
    def test_hotel_skips_cleaning(self):
        hit = 0
        for s in SEEDS:
            env = HotelEnv(s)
            plan = [(t, a) for t, a in env.oracle_plan() if t != "schedule_cleaning"]
            if len(plan) < len(env.oracle_plan()):
                hit += 1
                self.assertLess(play(env, plan)["score"], 1.0, f"seed {s}")
        self.assertGreater(hit, 10)
    def test_hotel_ignores_accessibility(self):
        for s in SEEDS:
            env = HotelEnv(s)
            guest = next(a for a in env.arrivals if "accessible" in a["requests"])
            wrong = next((x["room"] for x in env.rooms.values() if not x["accessible"] and x["status"] != "out_of_order"
                          and not x["stayover"] and x["type"] == guest["room_type"]), None)
            if wrong is None:
                continue
            plan = []
            for rid, room in sorted(env.truth["assign"].items()):
                if rid == guest["id"]:
                    room = wrong
                elif room == wrong:
                    room = env.truth["assign"][guest["id"]]
                plan += env.gated_call("assign_room", {"reservation_id": rid, "room": room})
                plan.append(("schedule_cleaning", {"room": room}))
            self.assertLess(play(env, plan)["score"], 1.0, f"seed {s}")


if __name__ == "__main__":
    unittest.main()
