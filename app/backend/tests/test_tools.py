"""Unit tests for the ten PLC tools — every tool asserts real content from the
PressLine_3 demo file."""


def test_get_project_summary(toolbox):
    s = toolbox.get_project_summary()
    assert s["controller"]["name"] == "PressLine_3"
    assert s["counts"]["tags"] == 169
    assert s["counts"]["programs"] == 6
    # AOI instance map derived from tag data types
    assert "FB_VALVE" in s["aoi_instances"]
    assert set(s["aoi_instances"]["FB_VALVE"]) == {"Valve_PressClamp", "Valve_Lube"}
    assert s["documentation"]["coverage_pct"] > 0
    prog_names = {p["name"] for p in s["programs"]}
    assert "P900_Safety" in prog_names


def test_search_tags(toolbox):
    r = toolbox.search_tags("safety")
    assert r["total"] >= 5
    names = {t["name"] for t in r["tags"]}
    assert "Safety_OK" in names
    # limit + total reporting
    r2 = toolbox.search_tags("", limit=5)  # matches everything
    assert r2["returned"] <= 5
    assert r2["total"] >= r2["returned"]


def test_search_tags_scope(toolbox):
    r = toolbox.search_tags("Seq", scope="P200_Transfer")
    assert all(t["scope"] == "P200_Transfer" for t in r["tags"])
    assert r["total"] >= 1


def test_get_tag_with_usage(toolbox):
    t = toolbox.get_tag("Safety_OK")
    assert t["name"] == "Safety_OK"
    assert t["data_type"] == "BOOL"
    # Safety_OK is written in R92_SafetyOK and read widely
    assert t["usage"]["write_count"] >= 1
    assert t["usage"]["read_count"] >= 1
    write_routines = {w["cite"]["routine"] for w in t["usage"]["writes"]}
    assert "R92_SafetyOK" in write_routines


def test_get_tag_missing(toolbox):
    t = toolbox.get_tag("NoSuchTag_ZZZ")
    assert "error" in t


def test_get_tag_aoi_instance(toolbox):
    t = toolbox.get_tag("Valve_PressClamp")
    assert t["is_aoi_instance"] is True
    assert t["data_type"] == "FB_VALVE"


def test_get_routine(toolbox):
    r = toolbox.get_routine("P900_Safety", "R92_SafetyOK")
    assert r["type"] == "RLL"
    assert r["total_rungs"] == 2
    # the Safety_OK permissive rung is appended as rung 1
    texts = " ".join(rg["text"] for rg in r["rungs"])
    assert "Safety_OK" in texts
    assert "GuardDoor_Closed" in texts


def test_get_routine_st(toolbox):
    r = toolbox.get_routine("P300_Press", "R32_Recipe")
    assert r["type"] == "ST"
    assert r["total_lines"] > 0
    assert any("Recipe" in ln["text"] for ln in r["lines"])


def test_get_rung(toolbox):
    r = toolbox.get_rung("P300_Press", "R30_PressCycle", 9)
    assert "PERMISSIVE" in (r["comment"] or "").upper()
    mnems = {i["mnemonic"] for i in r["instructions"]}
    assert "XIC" in mnems and "OTE" in mnems
    tag_names = {t["name"] for t in r["tags"]}
    assert "Safety_OK" in tag_names
    # descriptions are attached
    safety = next(t for t in r["tags"] if t["name"] == "Safety_OK")
    assert safety["description"]


def test_get_rung_bad(toolbox):
    assert "error" in toolbox.get_rung("P300_Press", "R30_PressCycle", 999)


def test_find_writers(toolbox):
    w = toolbox.find_writers("Safety_OK")
    assert w["total"] >= 1
    cites = {(c["cite"]["routine"], c["cite"]["rung_number"]) for c in w["results"]}
    assert ("R92_SafetyOK", 1) in cites


def test_find_writers_press_cycle_active(toolbox):
    w = toolbox.find_writers("Press_Cycle_Active")
    routines = {c["cite"]["routine"] for c in w["results"]}
    assert "R30_PressCycle" in routines


def test_find_readers(toolbox):
    r = toolbox.find_readers("Safety_OK")
    assert r["total"] >= 2
    assert all("read" in c["access"] for c in r["results"])


def test_trace_blockers_faulted(toolbox):
    # the money shot: guard-door-open snapshot yields Safety_OK -> GuardDoor_Closed
    r = toolbox.trace_blockers("Press_Cycle_Start")
    assert r["root_satisfied"] is False
    assert r["failing_count"] == 1
    path = r["failing_paths"][0]
    assert path["chain"] == ["Safety_OK", "GuardDoor_Closed"]
    assert path["leaf_tag"] == "GuardDoor_Closed"
    # a citation for R92_SafetyOK is present along the path
    routines = {n["cite"]["routine"] for n in path["nodes"] if n.get("cite")}
    assert "R92_SafetyOK" in routines


def test_trace_blockers_explicit_values(toolbox):
    r = toolbox.trace_blockers("Safety_OK", live_values={
        "Estop_Chain_OK": True, "GuardDoor_Closed": False, "LightCurtain_Clear": True,
        "SafetyRelay_CH1": True, "SafetyRelay_CH2": True, "Safety_Reset_Done": True,
    })
    assert r["root_satisfied"] is False
    leaf_tags = {p["leaf_tag"] for p in r["failing_paths"]}
    assert "GuardDoor_Closed" in leaf_tags


def test_trace_blockers_healthy(healthy_toolbox):
    r = healthy_toolbox.trace_blockers("Press_Cycle_Start")
    assert r["root_satisfied"] is True
    assert r["failing_count"] == 0


def test_trace_blockers_no_values():
    from app.backend.plc_tools import PLCToolbox, DEFAULT_L5X
    tb = PLCToolbox(str(DEFAULT_L5X))  # no provider
    r = tb.trace_blockers("Press_Cycle_Start")
    assert "tree" in r
    assert "root_satisfied" not in r  # not evaluated without values


def test_get_aoi(toolbox):
    a = toolbox.get_aoi("FB_VALVE")
    assert a["name"] == "FB_VALVE"
    param_names = {p["name"] for p in a["parameters"]}
    assert {"Open", "Close", "CmdOpen"} <= param_names
    assert a["instance_count"] == 2
    # internal logic rungs are present
    assert any(r.get("rungs") for r in a["routines"])


def test_get_aoi_missing(toolbox):
    assert "error" in toolbox.get_aoi("FB_NOPE")


def test_explain_context_pack(toolbox):
    p = toolbox.explain_context_pack("P900_Safety", "R92_SafetyOK")
    assert p["type"] == "RLL"
    assert len(p["rungs"]) == 2
    tag_names = {t["name"] for t in p["tags"]}
    assert "Safety_OK" in tag_names


def test_explain_context_pack_aoi_signatures(toolbox):
    p = toolbox.explain_context_pack("P300_Press", "R31_Hydraulics")
    aoi_names = {a["name"] for a in p["aoi_signatures"]}
    assert "FB_VALVE" in aoi_names


def test_get_live_values(toolbox):
    v = toolbox.get_live_values()
    assert v["available"] is True
    assert v["values"]["GuardDoor_Closed"] is False
    filtered = toolbox.get_live_values(["Safety_OK"])
    assert set(filtered["values"].keys()) == {"Safety_OK"}


def test_get_live_values_none():
    from app.backend.plc_tools import PLCToolbox, DEFAULT_L5X
    tb = PLCToolbox(str(DEFAULT_L5X))
    v = tb.get_live_values()
    assert v["available"] is False
