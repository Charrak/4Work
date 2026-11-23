def mk(c, dept, user_id=None, start="2030-01-07T08:00:00Z", end="2030-01-07T16:00:00Z", **kw):
    return c.post("/api/shifts", json={"department_id": dept, "user_id": user_id, "start": start, "end": end, **kw})


WEEK = "start=2030-01-07T00:00:00Z&end=2030-01-14T00:00:00Z"


def test_create_validation_and_overlap(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    assert mk(admin, dept, ids["anna"], end="2030-01-07T07:00:00Z").status_code == 422
    assert mk(admin, dept, ids["anna"]).status_code == 201
    assert mk(admin, dept, ids["anna"], start="2030-01-07T12:00:00Z", end="2030-01-07T20:00:00Z").status_code == 409
    assert mk(admin, dept, ids["ben"], start="2030-01-07T12:00:00Z", end="2030-01-07T20:00:00Z").status_code == 201


def test_drafts_hidden_until_published(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    mk(admin, dept, ids["anna"])
    anna = world["new_client"]("anna@test.de")
    assert anna.get(f"/api/shifts?{WEEK}").json() == []
    assert len(admin.get(f"/api/shifts?{WEEK}").json()) == 1
    r = admin.post("/api/shifts/publish", json={"start": "2030-01-07T00:00:00Z", "end": "2030-01-14T00:00:00Z"})
    assert r.json()["published"] == 1
    assert len(anna.get(f"/api/shifts?{WEEK}").json()) == 1


def test_optimistic_locking_conflict(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    s = mk(admin, dept, ids["anna"]).json()
    r1 = admin.patch(f"/api/shifts/{s['id']}", json={"version": s["version"], "note": "Von Gerät A"})
    assert r1.status_code == 200 and r1.json()["version"] == s["version"] + 1
    r2 = admin.patch(f"/api/shifts/{s['id']}", json={"version": s["version"], "note": "Von Gerät B"})
    assert r2.status_code == 409
    assert r2.json()["detail"]["current_version"] == r1.json()["version"]
    current = admin.get(f"/api/shifts?{WEEK}").json()[0]
    assert current["note"] == "Von Gerät A"   # nichts wurde überschrieben


def test_soft_delete(world):
    admin, dept = world["admin"], world["dept"]
    s = mk(admin, dept).json()
    assert admin.delete(f"/api/shifts/{s['id']}").status_code == 204
    assert admin.get(f"/api/shifts?{WEEK}").json() == []
    assert admin.delete(f"/api/shifts/{s['id']}").status_code == 404


def test_open_shift_claim_with_and_without_approval(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    open_approval = mk(admin, dept).json()
    open_direct = mk(admin, dept, start="2030-01-08T08:00:00Z", end="2030-01-08T16:00:00Z",
                     claim_requires_approval=False).json()
    admin.post("/api/shifts/publish", json={"start": "2030-01-07T00:00:00Z", "end": "2030-01-14T00:00:00Z"})
    anna, ben = world["new_client"]("anna@test.de"), world["new_client"]("ben@test.de")
    assert anna.post(f"/api/shifts/{open_direct['id']}/claim").json()["status"] == "assigned"
    assert ben.post(f"/api/shifts/{open_direct['id']}/claim").status_code == 409   # schon besetzt
    assert anna.post(f"/api/shifts/{open_approval['id']}/claim").json()["status"] == "pending"
    assert ben.post(f"/api/shifts/{open_approval['id']}/claim").json()["status"] == "pending"
    claims = admin.get(f"/api/shifts/{open_approval['id']}/claims").json()
    assert len(claims) == 2
    assert admin.post(f"/api/shifts/claims/{claims[1]['id']}/decide", json={"approve": True}).status_code == 200
    after = {c["user_name"]: c["status"] for c in admin.get(f"/api/shifts/{open_approval['id']}/claims").json()}
    assert sorted(after.values()) == ["approved", "rejected"]


def test_swap_flow_requires_manager_approval(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    s = mk(admin, dept, ids["anna"], start="2031-01-07T08:00:00Z", end="2031-01-07T16:00:00Z").json()
    admin.post("/api/shifts/publish", json={"start": "2031-01-01T00:00:00Z", "end": "2031-02-01T00:00:00Z"})
    anna, ben = world["new_client"]("anna@test.de"), world["new_client"]("ben@test.de")
    assert ben.post("/api/swaps", json={"shift_id": s["id"]}).status_code == 403   # nicht seine Schicht
    sw = anna.post("/api/swaps", json={"shift_id": s["id"]}).json()
    assert anna.post("/api/swaps", json={"shift_id": s["id"]}).status_code == 409  # doppelt
    assert anna.post(f"/api/swaps/{sw['id']}/accept").status_code == 400            # nicht selbst
    assert ben.post(f"/api/swaps/{sw['id']}/accept").json()["status"] == "accepted"
    week = "start=2031-01-05T00:00:00Z&end=2031-01-12T00:00:00Z"
    assert admin.get(f"/api/shifts?{week}").json()[0]["user_name"] == "Anna"       # noch unverändert
    assert ben.post(f"/api/swaps/{sw['id']}/decide", json={"approve": True}).status_code == 403
    assert admin.post(f"/api/swaps/{sw['id']}/decide", json={"approve": True}).json()["status"] == "approved"
    assert admin.get(f"/api/shifts?{week}").json()[0]["user_name"] == "Ben"


def test_copy_week(world):
    admin, dept, ids = world["admin"], world["dept"], world["ids"]
    mk(admin, dept, ids["anna"])                                  # Mo 2030-01-07
    r = admin.post("/api/shifts/copy-week", json={"source_start": "2030-01-07", "target_start": "2030-01-14"})
    assert r.json() == {"created": 1, "unassigned_due_to_conflict": 0}
    copied = admin.get("/api/shifts?start=2030-01-14T00:00:00Z&end=2030-01-21T00:00:00Z").json()
    assert len(copied) == 1 and copied[0]["start"].startswith("2030-01-14T08:00") and not copied[0]["published"]
