# DJI2AMC

Convert **DJI Pilot 2 Mapping 2D KMZ** missions into draft **Auterion Mission Control (`.plan`)** survey missions.

DJI2AMC was created to reduce the amount of manual mission reconstruction required when moving an established DJI mapping workflow into Auterion Mission Control. The current beta is tailored to a **Freefly Astro + Sony ILX-LR1 + 24 mm lens** workflow.

> [!WARNING]
> **Generated plans are drafts. Do not fly converter output without reviewing the complete mission in Auterion Mission Control.**
>
> Open every generated `.plan` in desktop AMC, inspect it carefully, make any required changes, and **Save it from AMC before operational use**. The pilot/operator remains responsible for validating altitude, boundaries, flight path, camera settings, speed, obstacle clearance, finish behavior, and all other mission parameters.

## What it converts

The converter currently reads DJI Pilot 2 **Mapping 2D** KMZ/WPML exports and carries the survey intent into an AMC Area Survey plan, including:

- Survey polygon
- Survey altitude
- Grid direction
- Front overlap
- Side overlap
- AMC survey entry location (`Auto` or explicit `0..3`)
- Turnaround distance
- Camera triggering during turnarounds
- Optional Return-to-Launch on the last converted mission

It creates an AMC-native **Survey ComplexItem** rather than attempting to reproduce every DJI-generated waypoint literally.

## Tested workflow

The current beta has been exercised with real DJI Pilot 2 mapping missions and reviewed in desktop Auterion Mission Control using:

- Freefly Astro
- Sony ILX-LR1
- Sigma 24 mm lens
- DJI Pilot 2 Mapping 2D KMZ exports
- Auterion Mission Control 1.36.x

The destination camera definition is currently forced to:

- Sony ILX-LR1 - 24mm
- 9504 × 6336 pixels
- 35.7 × 23.8 mm sensor
- 24 mm focal length
- 2-second minimum trigger interval

## Installation — Windows

1. Install **Python 3.11 or newer** from python.org if needed. During installation, enable **Add Python to PATH**.
2. Download or clone this repository.
3. Double-click `install_dependencies.bat`.
4. Double-click `run_converter.bat`.

The only third-party Python packages required are:

```text
shapely
pyproj
```

## Use

1. Click **Add KMZ...** and select one or more DJI Pilot 2 mission KMZ files.
2. Verify `AstroTemplate.plan` is selected.
3. Choose an output folder. The default is:

   ```text
   Documents\Auterion Mission Control\Missions
   ```

4. Leave **Entry Location** set to `Auto` initially.
5. Leave **Take photos during turnarounds** checked for the tested Astro/LR1 workflow.
6. If the final selected mission should return to launch, enable **Add Return-to-Launch to LAST selected mission**.
7. Click **CONVERT**.
8. Open each generated `.plan` in AMC.
9. Perform the final mission review and **Save the plan from AMC** before operational use.

### Final AMC review checklist

At minimum, verify:

- Polygon and site location
- Altitude and altitude frame
- Grid direction / flight-line orientation
- Front and side overlap
- Entry side and first flight line
- Turnaround distance
- Camera definition and photo interval
- Estimated photo count
- Flight speed
- **Speed Optimization** setting — the current converter does not explicitly enable this AMC UI option, so review it manually
- Finish behavior / Return-to-Launch
- Obstacle and airspace considerations

AMC may normalize or recalculate parts of the survey after opening or saving the plan. The AMC-saved version should be treated as the operational mission file.

## Current conversion behavior

- DJI Mapping 2D survey polygon is preserved.
- DJI survey height is preserved.
- DJI grid direction is preserved.
- DJI forward/side overlap is preserved.
- Turnaround distance defaults to **5 m**.
- Camera triggering during turnarounds is enabled by default.
- Draft survey speed is calculated as:

  ```text
  min(forward photo spacing / 2 sec, 5.4864 m/s)
  ```

  `5.4864 m/s` is 18 ft/s.

- Output mission filenames remove dashes and most punctuation because AMC does not accept dashes when saving mission names.
- Entry side can be selected automatically or explicitly as AMC `entryLocation` 0–3.
- Optional RTL is added only to the last selected mission.

## Limitations

This is an early beta and is intentionally narrow in scope.

Currently supported:

- DJI Pilot 2 Mapping 2D WPML missions

Not currently intended for:

- Oblique mapping
- Corridor mapping
- Facade missions
- Terrain-following missions
- Arbitrary waypoint/action missions
- Non-LR1 destination camera configurations

The generated transect geometry is a **draft reconstruction**. DJI and AMC can make different decisions around concave polygons, edge lines, transect placement, entry points, and image-count estimates. AMC is the final authority for the mission that will actually be used.

## Recommended workflow

```text
DJI Pilot 2 KMZ
        ↓
      DJI2AMC
        ↓
Draft AMC .plan
        ↓
Desktop AMC review / adjustments
        ↓
Save in AMC
        ↓
Operational .plan
```

## Reporting conversion problems

Useful bug reports include three files when possible:

1. The original DJI `.kmz`
2. The `.plan` generated by DJI2AMC
3. The same mission after review and Save in AMC

That makes it much easier to determine what DJI specified, what the converter generated, and what AMC normalized.

Please remove any mission data you do not want to publish before attaching files to a public issue. Mission files can contain precise geographic coordinates.

## Version

**v0.1 Beta** — initial standalone DJI Pilot 2 Mapping 2D → Astro/LR1 AMC converter.

## Project status

This project is independent and is **not affiliated with, endorsed by, or supported by DJI, Auterion, or Freefly Systems**. Product and company names are used only to describe interoperability.

No open-source license has been selected yet. Until a license is added, normal copyright rules apply to the source code.
