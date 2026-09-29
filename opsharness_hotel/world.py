"""Hotel front office (Zaplar-style).

Tonight's arrivals need rooms. Constraints: room type, accessibility,
out-of-order rooms, stayovers, and dirty rooms that need a cleaning task.
Upgrades need staff approval and must be the smallest step up. An event
RFP must go to the smallest free space that fits the group and features.
"""

from opsharness.core import Env, Tool, ToolError

RANK = {"queen": 0, "king": 1, "suite": 2}
GUESTS = ["Lindqvist", "Okafor", "Moreau", "Tanaka", "Haddad", "Novak", "Brennan", "Sato", "Ruiz", "Kowalski"]
SPACES = [("Linnea", 20, ["projector"]), ("Ekoln", 45, ["projector", "stage"]),
          ("Fyris", 60, ["projector"]), ("Grand Hall", 200, ["projector", "stage", "catering"])]

class HotelEnv(Env):
    name = "hotel"

    def build(self):
        for _ in range(200):
            if self._generate():
                break
        else:
            raise RuntimeError("could not build a solvable hotel instance")
        self.assign, self.cleaning, self.hold = {}, set(), None

    def _generate(self):
        r = self.rng
        types = ["queen"] * 5 + ["king"] * 4 + ["suite"] * 3
        r.shuffle(types)
        self.rooms = {}
        for i, t in enumerate(types):
            floor = i // 4 + 1
            num = f"{floor}0{i % 4 + 1}"
            self.rooms[num] = {"room": num, "type": t, "floor": floor, "accessible": False,
                               "status": "clean", "stayover": False}
        for num in r.sample([n for n in self.rooms if n.startswith("1")], 2):
            self.rooms[num]["accessible"] = True
        nums = list(self.rooms)
        r.shuffle(nums)
        self.rooms[nums[0]]["status"] = "out_of_order"
        self.rooms[nums[1]]["stayover"] = True
        self.rooms[nums[2]]["stayover"] = True
        for n in nums[3:6]:
            self.rooms[n]["status"] = "dirty"
        free = [x for x in self.rooms.values() if x["status"] != "out_of_order" and not x["stayover"]]
        count = {t: sum(1 for x in free if x["type"] == t) for t in RANK}
        if count["queen"] < 1 or count["king"] < 2 or count["suite"] < 1:
            return False
        # one more queen booking than queen rooms forces exactly one upgrade
        booked = ["queen"] * (count["queen"] + 1) + ["king"] * (count["king"] - 2) + ["suite"] * r.randint(0, 1)
        r.shuffle(booked)
        names = r.sample(GUESTS, len(booked))
        self.arrivals = [{"id": f"RES{101 + i}", "guest": names[i], "room_type": t, "nights": r.randint(1, 4),
                          "requests": []} for i, t in enumerate(booked)]
        r.choice(self.arrivals)["requests"].append("accessible")
        self.truth = self._solve()
        if self.truth is None:
            return False
        self._make_rfp()
        return True

    def _ok(self, res, room):
        if res["requests"] and "accessible" in res["requests"] and not room["accessible"]:
            return False
        return RANK[room["type"]] >= RANK[res["room_type"]]

    def _solve(self):
        """Search for an assignment with the fewest upgrade steps, preferring clean rooms."""
        free = [x for x in self.rooms.values() if x["status"] != "out_of_order" and not x["stayover"]]
        order = sorted(self.arrivals, key=lambda a: (not a["requests"], -RANK[a["room_type"]]))
        best = [None, None]

        def cost(assign):
            ups = sum(RANK[self.rooms[rm]["type"]] - RANK[a["room_type"]] for a in order
                      for rm in [assign[a["id"]]])
            dirty = sum(self.rooms[rm]["status"] == "dirty" for rm in assign.values())
            return (ups, dirty)

        def rec(i, used, assign):
            if i == len(order):
                c = cost(assign)
                if best[0] is None or c < best[0]:
                    best[0], best[1] = c, dict(assign)
                return
            a = order[i]
            for room in free:
                if room["room"] in used or not self._ok(a, room):
                    continue
                assign[a["id"]] = room["room"]
                used.add(room["room"])
                rec(i + 1, used, assign)
                used.discard(room["room"])
                del assign[a["id"]]

        rec(0, set(), {})
        if best[1] is None or best[0][0] != 1:
            return None
        return {"assign": best[1]}

    def _make_rfp(self):
        r = self.rng
        self.event_date = "2026-10-0" + str(r.randint(2, 9))
        size = r.randint(16, 50)
        needs = r.choice([["projector"], ["projector", "stage"]])
        self.rfp = {"id": "RFP-7", "organizer": r.choice(["Nordic Fintech Forum", "Uppsala Robotics Club",
                                                        "Klarberg AB offsite"]),
                    "date": self.event_date, "attendees": size, "needs": needs}
        fits = [s for s in SPACES if s[1] >= size and all(n in s[2] for n in needs)]
        fits.sort(key=lambda s: s[1])
        # book the best fit on that date half the time, so the second-best is right
        self.booked = set()
        if len(fits) > 1 and r.random() < 0.5:
            self.booked.add(fits[0][0])
            fits = fits[1:]
        self.truth_space = fits[0][0]

    # ---- tools -----------------------------------------------------------
    def _res(self, rid):
        for a in self.arrivals:
            if a["id"] == rid:
                return a
        raise ToolError(f"no reservation '{rid}'")

    def _room(self, num):
        if num not in self.rooms:
            raise ToolError(f"no room '{num}'")
        return self.rooms[num]

    def list_arrivals(self):
        return {"date": "2026-09-28", "arrivals": self.arrivals}

    def list_rooms(self):
        rooms = []
        for x in self.rooms.values():
            assigned = next((rid for rid, rm in self.assign.items() if rm == x["room"]), None)
            rooms.append({**x, "assigned_to": assigned, "cleaning_scheduled": x["room"] in self.cleaning})
        return {"rooms": rooms}

    def assign_room(self, reservation_id, room):
        self._res(reservation_id)
        x = self._room(room)
        if x["status"] == "out_of_order":
            raise ToolError(f"room {room} is out of order")
        if x["stayover"]:
            raise ToolError(f"room {room} is occupied by a stayover guest")
        other = next((rid for rid, rm in self.assign.items() if rm == room and rid != reservation_id), None)
        if other:
            raise ToolError(f"room {room} is already assigned to {other}")
        self.assign[reservation_id] = room
        return {"reservation_id": reservation_id, "room": room, "status": x["status"]}

    def _upgrade_gated(self, args):
        try:
            return RANK[self._room(args["room"])["type"]] > RANK[self._res(args["reservation_id"])["room_type"]]
        except (ToolError, KeyError):
            return False

    def schedule_cleaning(self, room):
        self._room(room)
        self.cleaning.add(room)
        return {"room": room, "cleaning": "scheduled"}

    def get_rfp(self):
        return self.rfp

    def list_event_spaces(self, date):
        return {"date": date, "spaces": [{"name": n, "capacity": c, "features": f,
                                          "booked": date == self.event_date and n in self.booked}
                                         for n, c, f in SPACES]}

    def hold_event_space(self, rfp_id, space):
        if rfp_id != self.rfp["id"]:
            raise ToolError(f"no RFP '{rfp_id}'")
        if space not in [s[0] for s in SPACES]:
            raise ToolError(f"no space '{space}'")
        if space in self.booked:
            raise ToolError(f"{space} is already booked on {self.event_date}")
        self.hold = space
        return {"rfp_id": rfp_id, "space": space, "status": "held, quote sent"}

    def env_tools(self):
        s = {"type": "string"}
        return [
            Tool("list_arrivals", "Tonight's arriving reservations with room type and special requests.",
                 {}, self.list_arrivals),
            Tool("list_rooms", "All rooms with type, floor, accessibility, status, stayovers and assignments.",
                 {}, self.list_rooms),
            Tool("assign_room", "Assign a room to a reservation. Reassigning replaces the old room.",
                 {"reservation_id": s, "room": s}, self.assign_room, ["reservation_id", "room"],
                 gated=self._upgrade_gated),
            Tool("schedule_cleaning", "Add a room to housekeeping's list for today.",
                 {"room": s}, self.schedule_cleaning, ["room"]),
            Tool("get_rfp", "The open event request for proposal.", {}, self.get_rfp),
            Tool("list_event_spaces", "Event spaces with capacity, features and whether booked on a date.",
                 {"date": s}, self.list_event_spaces, ["date"]),
            Tool("hold_event_space", "Hold a space for an RFP and send the quote.",
                 {"rfp_id": s, "space": s}, self.hold_event_space, ["rfp_id", "space"], gated=lambda a: True),
        ]

    def task(self):
        return ("Prepare the property for tonight: give every arrival a room and handle the open event RFP. "
                "Upgrades and event holds need staff approval.")

    # ---- answer key and scoring -------------------------------------------
    def oracle_plan(self):
        plan = []
        for rid, room in sorted(self.truth["assign"].items()):
            plan += self.gated_call("assign_room", {"reservation_id": rid, "room": room})
            if self.rooms[room]["status"] == "dirty":
                plan.append(("schedule_cleaning", {"room": room}))
        plan += self.gated_call("hold_event_space", {"rfp_id": self.rfp["id"], "space": self.truth_space})
        return plan

    def _free_at_end(self):
        used = set(self.assign.values())
        return [x for x in self.rooms.values()
                if x["status"] != "out_of_order" and not x["stayover"] and x["room"] not in used]

    def score(self):
        correct = 0
        spare = self._free_at_end()
        for a in self.arrivals:
            room = self.assign.get(a["id"])
            if room is None:
                continue
            x = self.rooms[room]
            if not self._ok(a, x):
                continue
            if x["status"] == "dirty" and room not in self.cleaning:
                continue
            step = RANK[x["type"]] - RANK[a["room_type"]]
            if step > 0:
                # a smaller step (or no upgrade) must not have been possible with the rooms left over
                if any(self._ok(a, y) and RANK[y["type"]] < RANK[x["type"]] for y in spare):
                    continue
            correct += 1
        event_ok = self.hold == self.truth_space
        n = len(self.arrivals) + 1
        return {"score": round((correct + event_ok) / n, 4), "details": {
            "arrivals_correct": correct, "arrivals": len(self.arrivals), "event_correct": event_ok,
            "upgrades": sum(RANK[self.rooms[rm]["type"]] > RANK[self._res(rid)["room_type"]]
                            for rid, rm in self.assign.items())}}
