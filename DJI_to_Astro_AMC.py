#!/usr/bin/env python3
"""
DJI Pilot 2 KMZ -> Auterion Mission Control .plan converter
Target: Freefly Astro + Sony ILX-LR1 + Sigma 24 mm

IMPORTANT:
Generated plans are DRAFTS. Open each plan in AMC, visually inspect it, and
SAVE it in AMC before uploading/flying it. AMC will normalize/recalculate
internal mission data.

This converter is tailored to DJI Mapping 2D WPML missions and a
known-good Astro/LR1 AMC survey structure.
"""

from __future__ import annotations

import json
import math
import re
import uuid
import zipfile
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from shapely.geometry import Polygon, LineString, MultiLineString, GeometryCollection
    from pyproj import CRS, Transformer, Geod
except ImportError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Missing dependencies",
        "This converter requires shapely and pyproj.\n\n"
        "Run install_dependencies.bat first."
    )
    raise

GEOD = Geod(ellps="WGS84")
REF_ALT_M = 30.48
REF_FORWARD_M = 6.0452
REF_SIDE_M = 13.6017
REF_IMAGE_DENSITY = 0.47705176767676777
MIN_TRIGGER_INTERVAL_S = 2.0
AMC_MAX_SURVEY_SPEED_MPS = 5.4864
DEFAULT_TURNAROUND_M = 5.0


def local_name(tag: str) -> str:
    return tag.split("}")[-1]


def first_text(root, names, default=None):
    if isinstance(names, str):
        names = [names]
    wanted = set(names)
    for elem in root.iter():
        if local_name(elem.tag) in wanted and elem.text and elem.text.strip():
            return elem.text.strip()
    return default


def parse_coords(text):
    pts = []
    if not text:
        return pts
    for token in text.replace("\n", " ").split():
        bits = token.split(",")
        if len(bits) >= 2:
            pts.append([float(bits[1]), float(bits[0])])
    return pts


def parse_dji_kmz(path: Path):
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "wpmz/template.kml" not in names:
            raise ValueError("KMZ does not contain wpmz/template.kml")
        template_root = ET.fromstring(zf.read("wpmz/template.kml"))
        way_root = ET.fromstring(zf.read("wpmz/waylines.wpml")) if "wpmz/waylines.wpml" in names else None

    polygon = None
    for elem in template_root.iter():
        if local_name(elem.tag) == "Polygon":
            coord_elem = next((x for x in elem.iter() if local_name(x.tag) == "coordinates"), None)
            if coord_elem is not None:
                pts = parse_coords(coord_elem.text)
                if len(pts) >= 3:
                    polygon = pts
                    break
    if polygon is None:
        raise ValueError("No survey polygon found in template.kml")
    if len(polygon) > 1 and polygon[0] == polygon[-1]:
        polygon = polygon[:-1]

    height = float(first_text(template_root, ["height", "executeHeight"], REF_ALT_M))
    angle = float(first_text(template_root, ["direction"], 0.0))
    fwd = float(first_text(template_root, ["orthoCameraOverlapH"], 80.0))
    side = float(first_text(template_root, ["orthoCameraOverlapW"], 70.0))

    first_waypoint = None
    if way_root is not None:
        for elem in way_root.iter():
            if local_name(elem.tag) == "coordinates" and elem.text:
                pts = parse_coords(elem.text)
                if pts:
                    first_waypoint = pts[0]
                    break

    return {
        "polygon": polygon,
        "height": height,
        "angle": angle,
        "forward_overlap": fwd,
        "side_overlap": side,
        "first_waypoint": first_waypoint,
    }


def geod_distance(a, b):
    _, _, d = GEOD.inv(a[1], a[0], b[1], b[0])
    return d


def geod_azimuth(a, b):
    az, _, _ = GEOD.inv(a[1], a[0], b[1], b[0])
    return az % 360.0


def destination(p, az_deg, distance_m):
    lon2, lat2, _ = GEOD.fwd(p[1], p[0], az_deg, distance_m)
    return [lat2, lon2]


def longest_linestring(geom):
    if geom.is_empty:
        return None
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        parts = list(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        parts = [g for g in geom.geoms if isinstance(g, LineString)]
    else:
        parts = []
    return max(parts, key=lambda x: x.length) if parts else None


def make_transects(poly_latlon, angle_deg, spacing_m, turnaround_m, entry_location):
    """Draft transect construction. AMC will normalize the plan when re-saved."""
    latc = sum(p[0] for p in poly_latlon) / len(poly_latlon)
    lonc = sum(p[1] for p in poly_latlon) / len(poly_latlon)

    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={latc} +lon_0={lonc} +datum=WGS84 +units=m +no_defs"
    )
    to_xy = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_ll = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)

    pts = [to_xy.transform(lon, lat) for lat, lon in poly_latlon]
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)

    a = math.radians(angle_deg % 180.0)
    d = (math.sin(a), math.cos(a))
    n = (math.cos(a), -math.sin(a))

    def dot(p, v):
        return p[0] * v[0] + p[1] * v[1]

    nvals = [dot(p, n) for p in pts]
    dvals = [dot(p, d) for p in pts]
    nmin, nmax = min(nvals), max(nvals)
    dmin, dmax = min(dvals), max(dvals)
    width = nmax - nmin

    count = max(1, int(math.floor(width / spacing_m)))
    if count == 1:
        offsets = [(nmin + nmax) / 2.0]
    else:
        occupied = (count - 1) * spacing_m
        margin = (width - occupied) / 2.0
        offsets = [nmin + margin + i * spacing_m for i in range(count)]

    extension = (dmax - dmin) + width + 1000.0
    center_d = (dmin + dmax) / 2.0
    raw = []

    for off in offsets:
        cx = n[0] * off + d[0] * center_d
        cy = n[1] * off + d[1] * center_d
        p1 = (cx - d[0] * extension, cy - d[1] * extension)
        p2 = (cx + d[0] * extension, cy + d[1] * extension)
        seg = longest_linestring(poly.intersection(LineString([p1, p2])))
        if seg is None or seg.length < 0.01:
            continue
        c = list(seg.coords)
        s1, s2 = c[0], c[-1]
        if ((s2[0] - s1[0]) * d[0] + (s2[1] - s1[1]) * d[1]) < 0:
            s1, s2 = s2, s1
        raw.append((off, s1, s2))

    if entry_location in (1, 3):
        raw.reverse()
    if entry_location in (2, 3):
        raw = [(o, b, a) for o, a, b in raw]

    visual = []
    pairs = []
    for i, (_, s1, s2) in enumerate(raw):
        if i % 2 == 1:
            s1, s2 = s2, s1
        lon1, lat1 = to_ll.transform(s1[0], s1[1])
        lon2, lat2 = to_ll.transform(s2[0], s2[1])
        q1, q2 = [lat1, lon1], [lat2, lon2]
        az = geod_azimuth(q1, q2)
        ta1 = destination(q1, az, -turnaround_m)
        ta2 = destination(q2, az, turnaround_m)
        visual.extend([ta1, q1, q2, ta2])
        pairs.append((ta1, q1, q2, ta2))
    return visual, pairs


def choose_entry_location(src, spacing_m, turnaround_m):
    target = src.get("first_waypoint")
    if not target:
        return 1
    candidates = []
    for loc in range(4):
        visual, _ = make_transects(src["polygon"], src["angle"], spacing_m, turnaround_m, loc)
        if visual:
            candidates.append((geod_distance(target, visual[0]), loc))
    return min(candidates)[1] if candidates else 1


def waypoint(coord, altitude, dojump):
    return {
        "autoContinue": True, "command": 16, "doJumpId": dojump, "frame": 3,
        "groupTag": 0, "params": [0, 0, 0, None, coord[0], coord[1], altitude],
        "type": "SimpleItem",
    }


def command(cmd, params, dojump, frame=2):
    return {
        "autoContinue": True, "command": cmd, "doJumpId": dojump, "frame": frame,
        "groupTag": 0, "params": params, "type": "SimpleItem",
    }


def build_internal_items(pairs, altitude, trigger_distance, flight_speed, start_id=3):
    seq = start_id
    out = []

    def add(item):
        nonlocal seq
        item["doJumpId"] = seq
        seq += 1
        out.append(item)

    first_ta, _, _, _ = pairs[0]
    add(waypoint(first_ta, altitude, seq))
    add(command(206, [trigger_distance, 0, 1, 0, 0, 0, 0], seq))
    add(command(178, [1, flight_speed, -1, 0, 0, 0, 0], seq))
    add(command(1001, [-2, -2, -1, -1, 0, 0, 0], seq))
    add(command(1000, [-90, 0, None, None, 12, 0, 0], seq))
    add(command(532, [2, 100, 0, 0, 0, 0, 0], seq))
    add(command(530, [0, 2, 0, 0, 0, 0, 0], seq))
    add(command(93, [2, -1, -1, -1, 0, 0, 0], seq))

    for i, (ta1, entry, exitp, ta2) in enumerate(pairs):
        if i == 0:
            add(waypoint(entry, altitude, seq))
        else:
            add(waypoint(ta1, altitude, seq))
            add(waypoint(entry, altitude, seq))
        add(command(206, [trigger_distance, 0, 1, 0, 0, 0, 0], seq))
        add(waypoint(exitp, altitude, seq))
        add(waypoint(ta2, altitude, seq))

    add(command(206, [0, 0, 1, 0, 0, 0, 0], seq))
    add(command(1000, [None, None, None, None, 2, 0, 0], seq))
    add(command(1001, [-3, -3, -1, -1, 0, 0, 0], seq))
    add(command(530, [0, 0, 0, 0, 0, 0, 0], seq))
    add(command(93, [2, -1, -1, -1, 0, 0, 0], seq))
    return out


def rtl_item(dojump):
    return {
        "autoContinue": True, "command": 20, "doJumpId": dojump, "frame": 2,
        "groupTag": 0, "params": [0, 0, 0, 0, 0, 0, 0], "type": "SimpleItem",
    }


def sanitize_filename(stem):
    name = re.sub(r"[^A-Za-z0-9_]", "", stem).replace("-", "")
    if not name.lower().endswith("astro"):
        name += "Astro"
    return name or "ConvertedAstro"


def convert_one(kmz_path, template, output_path, trigger_turn=True,
                turnaround_m=DEFAULT_TURNAROUND_M, entry_mode="Auto", add_rtl=False):
    src = parse_dji_kmz(kmz_path)
    plan = deepcopy(template)
    plan["UUID"] = uuid.uuid4().hex

    survey_idx = None
    for idx, item in enumerate(plan["mission"]["items"]):
        if item.get("type") == "ComplexItem" and item.get("complexItemType") == "survey":
            survey_idx = idx
            break
    if survey_idx is None:
        for idx, item in enumerate(plan["mission"]["items"]):
            if item.get("type") == "ComplexItem":
                survey_idx = idx
                break
    if survey_idx is None:
        raise ValueError("Template contains no ComplexItem survey")

    plan["mission"]["items"] = plan["mission"]["items"][:survey_idx + 1]
    ci = plan["mission"]["items"][survey_idx]
    ts = ci["TransectStyleComplexItem"]
    cam = ts["CameraCalc"]

    altitude = src["height"]
    scale = altitude / REF_ALT_M
    forward_m = REF_FORWARD_M * scale
    side_m = REF_SIDE_M * scale
    image_density = REF_IMAGE_DENSITY * scale
    speed = min(forward_m / MIN_TRIGGER_INTERVAL_S, AMC_MAX_SURVEY_SPEED_MPS)

    entry = choose_entry_location(src, side_m, turnaround_m) if entry_mode == "Auto" else int(entry_mode)
    visual, pairs = make_transects(src["polygon"], src["angle"], side_m, turnaround_m, entry)
    if not pairs:
        raise ValueError("Could not generate survey transects")

    ci["polygon"] = src["polygon"]
    ci["angle"] = round(src["angle"], 8)
    ci["entryLocation"] = entry
    ci["flyAlternateTransects"] = False
    ci["splitConcavePolygons"] = False

    cam.update({
        "DistanceToSurface": altitude,
        "DistanceToSurfaceRelative": True,
        "FrontalOverlap": src["forward_overlap"],
        "SideOverlap": src["side_overlap"],
        "AdjustedFootprintFrontal": forward_m,
        "AdjustedFootprintSide": side_m,
        "ImageDensity": image_density,
        "CameraName": "Sony ILX-LR1 - 24mm",
        "FocalLength": 24,
        "ImageHeight": 6336,
        "ImageWidth": 9504,
        "SensorHeight": 23.8,
        "SensorWidth": 35.7,
        "MinTriggerInterval": 2,
        "Landscape": True,
        "FixedOrientation": True,
        "ValueSetIsDistance": True,
    })

    ts["FlightSpeed"] = speed
    ts["CameraTriggerInTurnAround"] = bool(trigger_turn)
    ts["FollowTerrain"] = False
    ts["HoverAndCapture"] = False
    ts["Refly90Degrees"] = False
    ts["TurnAroundDistance"] = turnaround_m
    ts["VisualTransectPoints"] = visual
    ts["Items"] = build_internal_items(pairs, altitude, forward_m, speed, start_id=3)

    total = sum(geod_distance(visual[i - 1], visual[i]) for i in range(1, len(visual)))
    ts["CameraShots"] = max(1, int(math.ceil(total / forward_m)))

    latc = sum(p[0] for p in src["polygon"]) / len(src["polygon"])
    lonc = sum(p[1] for p in src["polygon"]) / len(src["polygon"])
    home_alt = plan["mission"].get("plannedHomePosition", [0, 0, 0])[2]
    plan["mission"]["plannedHomePosition"] = [latc, lonc, home_alt]

    if add_rtl:
        last_id = max([1] + [int(item.get("doJumpId", 0)) for item in ts.get("Items", [])])
        plan["mission"]["items"].append(rtl_item(last_id + 1))

    output_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return {
        "output": str(output_path), "altitude_m": altitude, "angle": src["angle"],
        "entry": entry, "transects": len(pairs), "speed_mps": speed, "rtl": add_rtl,
    }


class ConverterApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DJI2AMC — DJI KMZ → Astro AMC Converter")
        self.geometry("850x620")
        self.minsize(760, 560)
        here = Path(__file__).resolve().parent
        self.template_var = tk.StringVar(value=str(here / "AstroTemplate.plan"))
        self.output_var = tk.StringVar(value=str(Path.home() / "Documents" / "Auterion Mission Control" / "Missions"))
        self.entry_var = tk.StringVar(value="Auto")
        self.trigger_var = tk.BooleanVar(value=True)
        self.rtl_last_var = tk.BooleanVar(value=False)
        self.turnaround_var = tk.StringVar(value="5")
        self.files = []
        self.build_ui()

    def build_ui(self):
        pad = {"padx": 10, "pady": 6}
        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=12)
        ttk.Label(frm, text="Astro/LR1 AMC template:").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.template_var).grid(row=1, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_template).grid(row=1, column=2, **pad)
        ttk.Label(frm, text="DJI Pilot 2 KMZ files:").grid(row=2, column=0, sticky="w")
        self.listbox = tk.Listbox(frm, height=10)
        self.listbox.grid(row=3, column=0, columnspan=2, sticky="nsew", **pad)
        btns = ttk.Frame(frm)
        btns.grid(row=3, column=2, sticky="n")
        ttk.Button(btns, text="Add KMZ…", command=self.add_files).pack(fill="x", pady=3)
        ttk.Button(btns, text="Remove", command=self.remove_selected).pack(fill="x", pady=3)
        ttk.Button(btns, text="Clear", command=self.clear_files).pack(fill="x", pady=3)
        ttk.Label(frm, text="Output folder:").grid(row=4, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.output_var).grid(row=5, column=0, columnspan=2, sticky="ew", **pad)
        ttk.Button(frm, text="Browse…", command=self.pick_output).grid(row=5, column=2, **pad)

        opts = ttk.LabelFrame(frm, text="Conversion options")
        opts.grid(row=6, column=0, columnspan=3, sticky="ew", padx=10, pady=8)
        ttk.Label(opts, text="Entry location:").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Combobox(opts, textvariable=self.entry_var, values=["Auto", "0", "1", "2", "3"],
                     state="readonly", width=10).grid(row=0, column=1, padx=8, pady=6, sticky="w")
        ttk.Label(opts, text="Turnaround distance (m):").grid(row=0, column=2, padx=8, pady=6, sticky="w")
        ttk.Entry(opts, textvariable=self.turnaround_var, width=8).grid(row=0, column=3, padx=8, pady=6, sticky="w")
        ttk.Checkbutton(opts, text="Take photos during turnarounds", variable=self.trigger_var).grid(
            row=1, column=0, columnspan=2, padx=8, pady=6, sticky="w")
        ttk.Checkbutton(opts, text="Add Return-to-Launch to LAST selected mission", variable=self.rtl_last_var).grid(
            row=1, column=2, columnspan=2, padx=8, pady=6, sticky="w")

        warning = (
            "Output filenames are sanitized for AMC (dashes and other punctuation removed).\n"
            "IMPORTANT: Open each generated plan in AMC, inspect it, then SAVE it in AMC before flight."
        )
        ttk.Label(frm, text=warning, foreground="#a06000").grid(row=7, column=0, columnspan=3, sticky="w", padx=10, pady=8)
        ttk.Button(frm, text="CONVERT", command=self.convert).grid(row=8, column=0, columnspan=3, pady=10)
        self.status = tk.Text(frm, height=8, state="disabled")
        self.status.grid(row=9, column=0, columnspan=3, sticky="nsew", padx=10, pady=5)
        frm.columnconfigure(0, weight=1)
        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(3, weight=1)
        frm.rowconfigure(9, weight=1)

    def log(self, text):
        self.status.configure(state="normal")
        self.status.insert("end", text + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")
        self.update_idletasks()

    def pick_template(self):
        p = filedialog.askopenfilename(filetypes=[("AMC plans", "*.plan"), ("All files", "*.*")])
        if p:
            self.template_var.set(p)

    def add_files(self):
        paths = filedialog.askopenfilenames(filetypes=[("DJI KMZ", "*.kmz"), ("All files", "*.*")])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", p)

    def remove_selected(self):
        for i in reversed(list(self.listbox.curselection())):
            self.listbox.delete(i)
            del self.files[i]

    def clear_files(self):
        self.files.clear()
        self.listbox.delete(0, "end")

    def pick_output(self):
        p = filedialog.askdirectory()
        if p:
            self.output_var.set(p)

    def convert(self):
        if not self.files:
            messagebox.showwarning("No files", "Add one or more DJI KMZ files first.")
            return
        template_path = Path(self.template_var.get())
        if not template_path.exists():
            messagebox.showerror("Template not found", str(template_path))
            return
        try:
            template = json.loads(template_path.read_text(encoding="utf-8"))
            turnaround = float(self.turnaround_var.get())
        except Exception as e:
            messagebox.showerror("Setup error", str(e))
            return

        output_dir = Path(self.output_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        self.log("Starting conversion…")
        ok = 0
        for index, filename in enumerate(self.files):
            src = Path(filename)
            stem = sanitize_filename(src.stem)
            out = output_dir / f"{stem}.plan"
            n = 2
            while out.exists():
                out = output_dir / f"{stem}{n}.plan"
                n += 1
            add_rtl = self.rtl_last_var.get() and index == len(self.files) - 1
            try:
                info = convert_one(
                    src, template, out, trigger_turn=self.trigger_var.get(),
                    turnaround_m=turnaround, entry_mode=self.entry_var.get(), add_rtl=add_rtl,
                )
                self.log(
                    f"OK  {src.name} -> {out.name} | {info['altitude_m']:.2f} m | "
                    f"angle {info['angle']:.1f}° | entry {info['entry']} | "
                    f"{info['transects']} draft transects | {info['speed_mps']:.4f} m/s"
                    + (" | RTL" if info["rtl"] else "")
                )
                ok += 1
            except Exception as e:
                self.log(f"ERROR  {src.name}: {e}")
        self.log(f"Finished: {ok}/{len(self.files)} converted.")
        messagebox.showinfo(
            "Conversion complete",
            f"{ok} of {len(self.files)} plan(s) converted.\n\n"
            "Open each plan in AMC, inspect it, and save it in AMC before flight."
        )


if __name__ == "__main__":
    ConverterApp().mainloop()
