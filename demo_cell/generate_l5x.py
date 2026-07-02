#!/usr/bin/env python3
"""
generate_l5x.py -- Emit a Rockwell L5X file from the declarative PressLine_3 cell spec.

Reads ``pressline3.yaml`` (the single source of truth for the demo cell -- a future
simulator will consume the SAME file) and writes ``build/PressLine_3.L5X``, a fictional
but Studio-5000-plausible CompactLogix export.

Usage:
    python generate_l5x.py [--spec pressline3.yaml] [--out build/PressLine_3.L5X]

The output *.L5X is intentionally gitignored repo-wide; this generator is the committed
artifact. See README.md for the regeneration workflow.

Design notes
------------
* Interlocks are declared as DATA (all_of / any_of / none_of lists) and compiled into
  ladder rungs here, so the "money-shot" permissive chain is guaranteed consistent
  between the L5X and any consumer of the same YAML.
* Everything else (timers, seal-ins, latch pairs, sequencers, comparisons, AOI calls)
  is authored as explicit rung text in the spec for full control.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from xml.sax.saxutils import quoteattr

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write("PyYAML is required. Install with: pip install pyyaml\n")
    raise

HERE = os.path.dirname(os.path.abspath(__file__))

# Atomic (built-in scalar) types get a Radix attribute; structured types do not.
ATOMIC_RADIX = {
    "BOOL": "Decimal",
    "SINT": "Decimal",
    "INT": "Decimal",
    "DINT": "Decimal",
    "LINT": "Decimal",
    "REAL": "Float",
}


# ---------------------------------------------------------------------------
# Small XML helpers
# ---------------------------------------------------------------------------

def attr(value) -> str:
    """Escape an attribute value (returns the quoted string incl. quotes)."""
    return quoteattr(str(value))


def cdata(text: str) -> str:
    """Wrap text in a CDATA section, defusing any embedded terminator."""
    safe = str(text).replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{safe}]]>"


def desc_element(text, indent: str) -> str:
    if not text:
        return ""
    return f"{indent}<Description>\n{indent}  {cdata(text)}\n{indent}</Description>\n"


# ---------------------------------------------------------------------------
# Interlock -> rung text compiler (the data-driven part)
# ---------------------------------------------------------------------------

def compile_interlock(il: dict) -> str:
    """Turn an interlock spec into a single OTE-gated rung's text.

    all_of  -> series XIC contacts (must be TRUE)
    none_of -> series XIO contacts (must be FALSE)
    any_of  -> a parallel branch [XIC(a),XIC(b),...] (at least one TRUE)
    """
    parts = []
    for t in il.get("all_of", []) or []:
        parts.append(f"XIC({t})")
    if il.get("any_of"):
        legs = ",".join(f"XIC({t})" for t in il["any_of"])
        parts.append(f"[{legs}]")
    for t in il.get("none_of", []) or []:
        parts.append(f"XIO({t})")
    verb = il.get("verb", "OTE")
    parts.append(f"{verb}({il['output']})")
    return "".join(parts) + ";"


# ---------------------------------------------------------------------------
# Emitters
# ---------------------------------------------------------------------------

def emit_datatypes(udts: list) -> str:
    out = ["  <DataTypes Use=\"Context\">\n"]
    for udt in udts:
        out.append(
            f"    <DataType Name={attr(udt['name'])} Family=\"NoFamily\" Class=\"User\">\n"
        )
        out.append(desc_element(udt.get("description"), "      "))
        out.append("      <Members>\n")
        for m in udt["members"]:
            dim = str(m.get("dimension", "0"))
            radix = m.get("radix") or ATOMIC_RADIX.get(m["data_type"], "NullType")
            out.append(
                f"        <Member Name={attr(m['name'])} DataType={attr(m['data_type'])} "
                f"Dimension={attr(dim)} Radix={attr(radix)} Hidden=\"false\" "
                f"ExternalAccess={attr(m.get('external_access', 'Read/Write'))}>\n"
            )
            out.append(desc_element(m.get("description"), "          "))
            out.append("        </Member>\n")
        out.append("      </Members>\n")
        out.append("    </DataType>\n")
    out.append("  </DataTypes>\n")
    return "".join(out)


def emit_modules(modules: list) -> str:
    out = ["  <Modules>\n"]
    for mod in modules:
        parent = mod.get("parent", "")
        parent_port = mod.get("parent_port", 0)
        out.append(
            f"    <Module Name={attr(mod['name'])} CatalogNumber={attr(mod.get('catalog', ''))} "
            f"Vendor={attr(mod.get('vendor', 1))} ProductType={attr(mod.get('product_type', 0))} "
            f"ProductCode={attr(mod.get('product_code', 0))} Major={attr(mod.get('major', 1))} "
            f"Minor={attr(mod.get('minor', 1))} ParentModule={attr(parent)} "
            f"ParentModPortId={attr(parent_port)} Inhibited=\"false\" MajorFault=\"false\">\n"
        )
        out.append("      <Ports>\n")
        for p in mod.get("ports", []):
            up = "true" if p.get("upstream") else "false"
            out.append(
                f"        <Port Id={attr(p['id'])} Type={attr(p.get('type', 'ICP'))} "
                f"Address={attr(p.get('address', ''))} Upstream={attr(up)}/>\n"
            )
        out.append("      </Ports>\n")
        out.append("    </Module>\n")
    out.append("  </Modules>\n")
    return "".join(out)


def emit_rll(routine: dict, indent: str) -> str:
    out = [f"{indent}<RLLContent>\n"]
    for i, rung in enumerate(routine["_rungs"]):
        out.append(f"{indent}  <Rung Number={attr(i)} Type=\"N\">\n")
        if rung.get("comment"):
            out.append(f"{indent}    <Comment>\n{indent}      {cdata(rung['comment'])}\n{indent}    </Comment>\n")
        out.append(f"{indent}    <Text>\n{indent}      {cdata(rung['text'])}\n{indent}    </Text>\n")
        out.append(f"{indent}  </Rung>\n")
    out.append(f"{indent}</RLLContent>\n")
    return "".join(out)


def emit_st(routine: dict, indent: str) -> str:
    out = [f"{indent}<STContent>\n"]
    for i, line in enumerate(routine.get("lines", [])):
        out.append(f"{indent}  <Line Number={attr(i)}>\n{indent}    {cdata(line)}\n{indent}  </Line>\n")
    out.append(f"{indent}</STContent>\n")
    return "".join(out)


def emit_routine(routine: dict, indent: str) -> str:
    rtype = routine.get("type", "RLL")
    out = [f"{indent}<Routine Name={attr(routine['name'])} Type={attr(rtype)}>\n"]
    out.append(desc_element(routine.get("description"), indent + "  "))
    if rtype == "RLL":
        out.append(emit_rll(routine, indent + "  "))
    elif rtype == "ST":
        out.append(emit_st(routine, indent + "  "))
    out.append(f"{indent}</Routine>\n")
    return "".join(out)


def emit_aois(aois: list) -> str:
    out = ["  <AddOnInstructionDefinitions>\n"]
    for aoi in aois:
        out.append(
            f"    <AddOnInstructionDefinition Name={attr(aoi['name'])} "
            f"Revision={attr(aoi.get('revision', '1.0'))} ExecutePrescan=\"false\" "
            f"ExecutePostscan=\"false\" ExecuteEnableInFalse=\"false\" Class=\"Standard\">\n"
        )
        out.append(desc_element(aoi.get("description"), "      "))
        # Parameters
        out.append("      <Parameters>\n")
        for p in aoi.get("parameters", []):
            req = "true" if p.get("required") else "false"
            vis = "true" if p.get("visible") else "false"
            radix = ATOMIC_RADIX.get(p["data_type"])
            radix_attr = f" Radix={attr(radix)}" if radix else ""
            dd = ""
            if p.get("default_data") is not None:
                dd = f" DefaultData={attr(p['default_data'])}"
            out.append(
                f"        <Parameter Name={attr(p['name'])} TagType=\"Base\" "
                f"DataType={attr(p['data_type'])}{radix_attr} Usage={attr(p.get('usage', 'Input'))} "
                f"Required={attr(req)} Visible={attr(vis)}{dd} ExternalAccess=\"Read/Write\">\n"
            )
            out.append(desc_element(p.get("description"), "          "))
            out.append("        </Parameter>\n")
        out.append("      </Parameters>\n")
        # Local tags
        if aoi.get("local_tags"):
            out.append("      <LocalTags>\n")
            for lt in aoi["local_tags"]:
                out.append(
                    f"        <LocalTag Name={attr(lt['name'])} DataType={attr(lt['data_type'])} "
                    f"Dimensions={attr(lt.get('dimensions', '0'))} ExternalAccess=\"Read/Write\">\n"
                )
                out.append(desc_element(lt.get("description"), "          "))
                out.append("        </LocalTag>\n")
            out.append("      </LocalTags>\n")
        # Internal routines
        out.append("      <Routines>\n")
        for r in aoi.get("routines", []):
            _prep_routine(r)
            out.append(emit_routine(r, "        "))
        out.append("      </Routines>\n")
        out.append("    </AddOnInstructionDefinition>\n")
    out.append("  </AddOnInstructionDefinitions>\n")
    return "".join(out)


def emit_tag(tag: dict, indent: str) -> str:
    tag_type = tag.get("tag_type", "Base")
    dims = str(tag.get("dimensions", "0"))
    attrs = [f"Name={attr(tag['name'])}", f"TagType={attr(tag_type)}"]
    if dims not in ("0", ""):
        attrs.append(f"Dimensions={attr(dims)}")
    attrs.append(f"DataType={attr(tag['data_type'])}")
    radix = ATOMIC_RADIX.get(tag["data_type"])
    if radix:
        attrs.append(f"Radix={attr(radix)}")
    if tag_type == "Alias":
        attrs.append(f"AliasFor={attr(tag.get('alias_for', ''))}")
    if tag.get("constant"):
        attrs.append("Constant=\"true\"")
    else:
        attrs.append("Constant=\"false\"")
    attrs.append(f"ExternalAccess={attr(tag.get('external_access', 'Read/Write'))}")
    line = f"{indent}<Tag {' '.join(attrs)}>\n"
    body = desc_element(tag.get("description"), indent + "  ")
    return line + body + f"{indent}</Tag>\n"


def emit_controller_tags(tags: list) -> str:
    ctrl = [t for t in tags if t.get("scope", "Controller") == "Controller"]
    out = ["  <Tags>\n"]
    for t in ctrl:
        out.append(emit_tag(t, "    "))
    out.append("  </Tags>\n")
    return "".join(out)


def emit_programs(programs: list, tags: list) -> str:
    out = ["  <Programs>\n"]
    for prog in programs:
        out.append(
            f"    <Program Name={attr(prog['name'])} TestEdits=\"false\" "
            f"MainRoutineName={attr(prog.get('main_routine', 'MainRoutine'))} "
            f"Disabled={attr('true' if prog.get('disabled') else 'false')} "
            f"UseAsFolder=\"false\">\n"
        )
        # program-scoped tags
        prog_tags = [t for t in tags if t.get("scope") == prog["name"]]
        out.append("      <Tags>\n")
        for t in prog_tags:
            out.append(emit_tag(t, "        "))
        out.append("      </Tags>\n")
        # routines
        out.append("      <Routines>\n")
        for r in prog["routines"]:
            out.append(emit_routine(r, "        "))
        out.append("      </Routines>\n")
        out.append("    </Program>\n")
    out.append("  </Programs>\n")
    return "".join(out)


def emit_tasks(programs: list) -> str:
    names = [p["name"] for p in programs]
    scheduled = "".join(f"        <ScheduledProgram Name={attr(n)}/>\n" for n in names)
    return (
        "  <Tasks>\n"
        "    <Task Name=\"MainTask\" Type=\"CONTINUOUS\" Priority=\"10\" Watchdog=\"500\" "
        "DisableUpdateOutputs=\"false\" InhibitTask=\"false\">\n"
        "      <ScheduledPrograms>\n"
        f"{scheduled}"
        "      </ScheduledPrograms>\n"
        "    </Task>\n"
        "  </Tasks>\n"
    )


# ---------------------------------------------------------------------------
# Routine preparation (merge explicit rungs + compiled interlocks; number them)
# ---------------------------------------------------------------------------

def _prep_routine(routine: dict) -> None:
    """Populate routine['_rungs'] as an ordered list of {comment,text} dicts.

    Idempotent: once seeded (and possibly extended with compiled interlocks) it is
    not reset on subsequent calls.
    """
    if routine.get("type", "RLL") != "RLL":
        return
    if "_rungs" not in routine:
        routine["_rungs"] = list(routine.get("rungs", []) or [])


def _apply_interlocks(programs: list, interlocks: dict) -> list:
    """Compile interlocks into rungs appended to their target routine.

    Returns a list of (name, program, routine, hint) for reporting.
    """
    # index routines by (program, routine)
    index = {}
    for prog in programs:
        for r in prog["routines"]:
            _prep_routine(r)
            index[(prog["name"], r["name"])] = r

    applied = []
    for name, il in (interlocks or {}).items():
        key = (il["program"], il["routine"])
        if key not in index:
            raise SystemExit(f"Interlock {name!r} targets unknown routine {key}")
        r = index[key]
        rung = {"text": compile_interlock(il)}
        if il.get("comment"):
            rung["comment"] = il["comment"]
        r["_rungs"].append(rung)
        applied.append((name, il["program"], il["routine"]))
    return applied


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_l5x(spec: dict) -> str:
    c = spec["controller"]
    now = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

    programs = spec.get("programs", [])
    interlocks = spec.get("interlocks", {})
    _apply_interlocks(programs, interlocks)
    # prep any routines not touched by interlocks
    for prog in programs:
        for r in prog["routines"]:
            _prep_routine(r)

    header = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
        f"<RSLogix5000Content SchemaRevision=\"1.0\" "
        f"SoftwareRevision={attr(c.get('software_revision', '33.00'))} "
        f"TargetName={attr(c['name'])} TargetType=\"Controller\" "
        f"ContainsContext=\"false\" ExportDate={attr(now)} "
        f"ExportOptions=\"References DecoratedData Context Dependencies ForceProtectedEncoding AllProjDocTrans\">\n"
    )

    controller_open = (
        f"  <Controller Use=\"Target\" Name={attr(c['name'])} "
        f"ProcessorType={attr(c['processor'])} MajorRev={attr(c.get('major_rev', 33))} "
        f"MinorRev={attr(c.get('minor_rev', 11))} TimeSlice=\"20\" ShareUnusedTimeSlice=\"1\" "
        f"ProjectCreationDate={attr(c.get('project_creation_date', now))} "
        f"LastModifiedDate={attr(c.get('last_modified_date', now))} "
        f"SFCExecutionControl=\"CurrentActive\" SFCRestartPosition=\"MostRecent\" "
        f"SFCLastScan=\"DontScan\" CommDriverName=\"AB_ETHIP-1\">\n"
    )
    controller_open += desc_element(c.get("description"), "    ")

    body = []
    body.append(header)
    body.append(controller_open)
    body.append(emit_datatypes(spec.get("udts", [])))
    body.append(emit_modules(spec.get("modules", [])))
    body.append(emit_aois(spec.get("aois", [])))
    body.append(emit_controller_tags(spec.get("tags", [])))
    body.append(emit_programs(programs, spec.get("tags", [])))
    body.append(emit_tasks(programs))
    body.append("  </Controller>\n")
    body.append("</RSLogix5000Content>\n")
    return "".join(body)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate PressLine_3.L5X from the YAML cell spec.")
    ap.add_argument("--spec", default=os.path.join(HERE, "pressline3.yaml"))
    ap.add_argument("--out", default=os.path.join(HERE, "build", "PressLine_3.L5X"))
    args = ap.parse_args()

    with open(args.spec, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    xml = build_l5x(spec)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(xml)

    # Small console summary
    tags = spec.get("tags", [])
    n_rungs = 0
    for prog in spec.get("programs", []):
        for r in prog["routines"]:
            n_rungs += len(r.get("_rungs", []))
    print(f"Wrote {args.out}")
    print(f"  tags={len(tags)}  programs={len(spec.get('programs', []))}  "
          f"udts={len(spec.get('udts', []))}  aois={len(spec.get('aois', []))}  "
          f"modules={len(spec.get('modules', []))}  rll_rungs={n_rungs}")


if __name__ == "__main__":
    main()
