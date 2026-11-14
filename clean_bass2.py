"""
Flame in Freefall — BASS-II experimental table cleaner
-------------------------------------------------------
Input : PSI-25_Experimental_table_BASS-II.csv (raw PSI export)
Output: tests_clean.csv   one row per test, normalized fields + quality flags
        flow_steps.csv    long format: airflow sequence per test (cm/s)

Usage : python clean_bass2.py <raw_csv> [out_dir]
"""
import re
import sys
from pathlib import Path

import pandas as pd

# ---------- column map (raw headers have stray spaces + BOM) ----------
COLS = {
    "PI": "pi",
    "Test #": "test_id",
    "Date": "date",
    "GMT": "gmt_day",
    "Sample #": "sample_raw",
    "Fuel Sample Material": "material_raw",
    "Flow restrictor": "flow_restrictors",
    "Fan display": "fan_raw",
    "Air display": "air_raw",
    "Radiometer gain   (1000   250   50   10)": "radiometer_gain",
    "Total Frames Shot": "frames_raw",
    "Calibrated  initial O2 % by vol": "o2_initial",
    "Calibrated final O2 % by vol": "o2_final",
    "Initial CO2 % by vol": "co2_initial",
    "Final CO2 % by vol": "co2_final",
    "Initial CO (ppm)": "co_initial",
    "Final CO (ppm)": "co_final",
}

# Plausible ranges — values outside are treated as entry errors
O2_RANGE = (10.0, 25.0)       # % by vol; MSG was vitiated with N2, never enriched
AIR_MAX_CMS = 55.0            # report: max ~55 cm/s with no restrictors


# ---------- material parsing ----------
def parse_material(raw: str) -> dict:
    s = " ".join(str(raw).lower().split())
    out = {
        "material": None, "geometry": None, "thickness_mm": None,
        "width_cm": None, "diameter_in": None, "color": None, "sides_burned": None,
    }

    if "sibal" in s:
        out["material"], out["geometry"] = "SIBAL", "fabric"
    elif "nomex" in s:
        out["material"], out["geometry"] = "Nomex III", "fabric"
    elif "wax" in s or "candle" in s:
        out["material"], out["geometry"] = "Japan wax", "candle"
    elif "spherical" in s or "sphere" in s:
        out["material"], out["geometry"] = "PMMA", "spherical_section"
    elif "rod" in s:
        out["material"], out["geometry"] = "PMMA", "rod"
    else:
        out["material"] = "PMMA"  # every remaining BASS-II sample is PMMA sheet

    # rods: diameter in inches ("1/4", "3/8", "0.5")
    if out["geometry"] == "rod":
        frac = re.search(r"(\d)/(\d)", s)
        dec = re.search(r"(0?\.\d+)\s*\"", s)
        if frac:
            out["diameter_in"] = round(int(frac.group(1)) / int(frac.group(2)), 3)
        elif dec:
            out["diameter_in"] = float(dec.group(1))
        out["color"] = "black" if "bla" in s else "clear"  # catches typo "blac"
        return out

    # sheets: thickness in micron or mm
    mic = re.search(r"(\d+)\s*micron", s)
    mm = re.search(r"(\d*\.?\d+)\s*mm", s)
    if mic:
        out["thickness_mm"] = int(mic.group(1)) / 1000
    elif mm:
        out["thickness_mm"] = float(mm.group(1))

    # width: "1 cm" / "2 cm" (skip the 4 cm sphere)
    if out["geometry"] != "spherical_section":
        w = re.search(r"(\d)\s*cm", s)
        if w:
            out["width_cm"] = float(w.group(1))
    else:
        out["diameter_in"] = None

    if out["geometry"] is None and out["thickness_mm"] is not None:
        out["geometry"] = "film" if out["thickness_mm"] < 1 else "slab"

    if "1 sided" in s:
        out["sides_burned"] = 1
    elif "2 sided" in s or out["geometry"] in ("film", "slab"):
        out["sides_burned"] = 2  # default for sheet holders
    return out


# ---------- airflow parsing ----------
EXT_PATTERN = r"(?<![a-z])ext|extinguish|\bout\b"
NUM = re.compile(r"(?<![\w.])(\d*\.?\d+)(?![\w.])")


def parse_air(raw: str) -> dict:
    """Return the airflow step sequence (cm/s) plus event flags."""
    s = "" if pd.isna(raw) else str(raw).lower()
    s = re.sub(r"(\d)ext", r"\1 ext", s)  # "0ext" -> "0 ext"
    flags = {
        "air_extinction": bool(re.search(EXT_PATTERN, s)),
        "air_blowoff": "blowoff" in s,
        "air_no_ignition": bool(re.search(r"no ign|would not stay lit", s)),
        "air_hit_max": "max" in s,
        "air_ambiguous": False,
    }

    outside = s.split("(")[0]
    inside = s[s.find("(") + 1:s.find(")")] if "(" in s and ")" in s else ""

    def nums(txt):
        return [float(x) for x in NUM.findall(txt.replace(">", " ").replace("?", ""))]

    steps = nums(outside)
    # A few rows logged fan counts outside and air speed inside the parentheses
    # (e.g. "49 44 42 41 (5 2 0)"). Fan counts sit ~40-120, air speed < 40.
    if steps and min(steps) >= 40 and inside:
        steps = nums(inside)
        flags["air_ambiguous"] = True
    if "pot" in outside:
        # "pot" values are fan potentiometer settings, not cm/s
        flags["air_ambiguous"] = True
        steps = [v for v in nums(outside.split("pot")[0])]

    steps = [v for v in steps if v <= AIR_MAX_CMS]
    return {"air_steps": steps, **flags}


# ---------- numeric gas columns ----------
def to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.strip(), errors="coerce")


def main(raw_path: str, out_dir: str = ".") -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(raw_path, encoding="utf-8-sig", dtype=str)
    df.columns = [" ".join(c.split()) if "Radiometer" not in c else c.strip() for c in df.columns]
    df = df.rename(columns={" ".join(k.split()): v for k, v in COLS.items()})
    df = df.rename(columns={"Radiometer gain   (1000   250   50   10)": "radiometer_gain"})

    for c in ["pi", "test_id", "sample_raw", "material_raw"]:
        df[c] = df[c].str.strip()

    # test run suffix: O3a / O3b = repeated burns on the same sample
    m = df["test_id"].str.extract(r"^([A-Z])(\d+)([a-z]?)$")
    df["test_number"] = pd.to_numeric(m[1])
    df["run"] = m[2].replace("", None)

    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y", errors="coerce").dt.date

    # materials
    mat = df["material_raw"].apply(parse_material).apply(pd.Series)
    df = pd.concat([df, mat], axis=1)

    # airflow
    air = df["air_raw"].apply(parse_air).apply(pd.Series)
    df = pd.concat([df, air], axis=1)
    df["air_initial_cms"] = df["air_steps"].apply(lambda x: x[0] if x else None)
    df["air_min_cms"] = df["air_steps"].apply(lambda x: min(x) if x else None)
    df["air_max_cms"] = df["air_steps"].apply(lambda x: max(x) if x else None)
    df["blowoff"] = df["air_blowoff"] | df["fan_raw"].fillna("").str.lower().str.contains("blowoff")
    df["extinction"] = df["air_extinction"] | df["fan_raw"].fillna("").str.lower().str.contains(EXT_PATTERN)

    # gases
    for c in ["o2_initial", "o2_final", "co2_initial", "co2_final", "co_initial", "co_final"]:
        df[c + "_raw"] = df[c]
        df[c] = to_num(df[c])

    lo, hi = O2_RANGE
    bad_o2 = ~df["o2_final"].between(lo, hi) & df["o2_final"].notna()
    df["flag_o2_final_invalid"] = bad_o2
    df.loc[bad_o2, "o2_final"] = None

    df["flag_co_negative"] = (df["co_initial"] < 0) | (df["co_final"] < 0)  # sensor offset near 0
    df["flag_gas_missing"] = df[["o2_final", "co2_final", "co_final"]].isna().any(axis=1)

    df["o2_consumed_pct"] = (df["o2_initial"] - df["o2_final"]).round(2)
    df["co_produced_ppm"] = df["co_final"] - df["co_initial"]

    df["needs_review"] = (
        df["flag_o2_final_invalid"] | df["air_ambiguous"]
        | df["material"].isna() | df["air_initial_cms"].isna()
    )

    # ---------- outputs ----------
    keep = [
        "test_id", "pi", "test_number", "run", "date", "gmt_day", "sample_raw",
        "material", "geometry", "thickness_mm", "width_cm", "diameter_in", "color", "sides_burned",
        "flow_restrictors", "air_initial_cms", "air_min_cms", "air_max_cms",
        "extinction", "blowoff", "air_no_ignition", "air_hit_max",
        "o2_initial", "o2_final", "o2_consumed_pct",
        "co2_initial", "co2_final", "co_initial", "co_final", "co_produced_ppm",
        "flag_o2_final_invalid", "flag_co_negative", "flag_gas_missing", "air_ambiguous", "needs_review",
        "material_raw", "fan_raw", "air_raw", "frames_raw",
    ]
    tests = df[keep].rename(columns={"air_no_ignition": "no_ignition", "air_hit_max": "hit_max_flow"})
    tests.to_csv(out / "tests_clean.csv", index=False)

    steps = (
        df[["test_id", "air_steps"]].explode("air_steps").dropna()
        .rename(columns={"air_steps": "air_cms"})
    )
    steps["step_idx"] = steps.groupby("test_id").cumcount()
    steps[["test_id", "step_idx", "air_cms"]].to_csv(out / "flow_steps.csv", index=False)

    # ---------- console summary ----------
    print(f"tests: {len(tests)}  |  flow steps: {len(steps)}")
    print("\nby material/geometry:")
    print(tests.groupby(["material", "geometry"], dropna=False).size().to_string())
    print(f"\nextinction: {tests.extinction.sum()}  blowoff: {tests.blowoff.sum()}  "
          f"no_ignition: {tests.no_ignition.sum()}")
    print(f"needs_review: {tests.needs_review.sum()} -> "
          f"{', '.join(tests.loc[tests.needs_review, 'test_id'])}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python clean_bass2.py <raw_csv> [out_dir]")
    main(*sys.argv[1:3])
