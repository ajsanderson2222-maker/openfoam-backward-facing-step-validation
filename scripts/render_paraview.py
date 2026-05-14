#!/usr/bin/env pvpython
from __future__ import annotations

import argparse
from pathlib import Path

from paraview.simple import (  # type: ignore
    Calculator,
    ColorBy,
    GetActiveViewOrCreate,
    GetColorTransferFunction,
    GetScalarBar,
    Hide,
    OpenFOAMReader,
    Render,
    SaveScreenshot,
    Show,
)

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case"
IMAGES = ROOT / "images"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render OpenFOAM mesh and absolute pressure with ParaView."
    )
    parser.add_argument("--rho", type=float, default=1.225, help="Density in kg/m^3")
    parser.add_argument(
        "--p-ref",
        type=float,
        default=101325.0,
        help="Reference absolute pressure in Pa",
    )
    parser.add_argument("--width", type=int, default=3000, help="Screenshot width")
    parser.add_argument("--height", type=int, default=260, help="Screenshot height")
    parser.add_argument(
        "--x-padding",
        type=float,
        default=0.002,
        help="Left/right physical padding around the mesh in meters",
    )
    parser.add_argument(
        "--y-padding",
        type=float,
        default=0.0005,
        help="Top/bottom minimum physical padding around the mesh in meters",
    )
    parser.add_argument(
        "--pressure-x-padding",
        type=float,
        default=0.006,
        help="Left/right physical padding for the pressure image in meters",
    )
    parser.add_argument(
        "--pressure-y-padding",
        type=float,
        default=0.0015,
        help="Top physical padding for the pressure image in meters",
    )
    parser.add_argument(
        "--pressure-bottom-padding",
        type=float,
        default=0.010,
        help="Bottom physical padding for the pressure image and scalar bar in meters",
    )
    return parser.parse_args()


def latest_numeric_time(case_dir: Path) -> float:
    times = []
    for path in case_dir.iterdir():
        if path.is_dir():
            try:
                times.append(float(path.name))
            except ValueError:
                pass

    if not times:
        raise SystemExit("No result time directories found. Run ./scripts/run_case.sh first.")

    return max(times)


def configure_view(width: int, height: int):
    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [width, height]
    view.Background = [1.0, 1.0, 1.0]
    view.OrientationAxesVisibility = 1
    view.CameraParallelProjection = 1
    return view


def frame_source(
    source,
    view,
    width: int,
    height: int,
    x_padding: float,
    y_padding: float,
    y_bottom_padding: float | None = None,
):
    bounds = source.GetDataInformation().GetBounds()
    x_min, x_max, y_min, y_max, _, _ = bounds
    y_top_padding = y_padding
    if y_bottom_padding is None:
        y_bottom_padding = y_padding

    x_mid = 0.5 * (x_min + x_max)
    y_mid = 0.5 * ((y_min - y_bottom_padding) + (y_max + y_top_padding))
    x_span = x_max - x_min
    y_span = y_max - y_min
    aspect = width / height
    visible_width = x_span + 2.0 * x_padding
    visible_height = y_span + y_top_padding + y_bottom_padding

    view.CameraPosition = [x_mid, y_mid, 0.42]
    view.CameraFocalPoint = [x_mid, y_mid, 0.0]
    view.CameraViewUp = [0.0, 1.0, 0.0]
    view.CameraParallelProjection = 1
    view.CameraParallelScale = max(0.5 * visible_height, 0.5 * visible_width / aspect)
    return bounds, view.CameraParallelScale


def set_proxy_property(proxy, name: str, value) -> bool:
    try:
        setattr(proxy, name, value)
    except AttributeError:
        print(f"Skipping unsupported ParaView property: {name}")
        return False
    return True


def lookup_table_range(lut) -> tuple[float, float]:
    try:
        p_range = lut.GetRange()
        return float(p_range[0]), float(p_range[1])
    except Exception:
        pass

    rgb_points = list(lut.RGBPoints)
    if len(rgb_points) >= 8:
        return float(rgb_points[0]), float(rgb_points[-4])

    raise RuntimeError("Could not determine lookup-table range for custom labels")


def render_mesh(reader, view, output: Path, args: argparse.Namespace) -> None:
    display = Show(reader, view)
    display.Representation = "Wireframe"
    ColorBy(display, None)
    display.AmbientColor = [0.05, 0.05, 0.05]
    display.DiffuseColor = [0.05, 0.05, 0.05]
    display.EdgeColor = [0.05, 0.05, 0.05]
    display.LineWidth = 1.0
    Render(view)
    bounds, scale = frame_source(
        reader, view, args.width, args.height, args.x_padding, args.y_padding
    )
    Render(view)
    SaveScreenshot(str(output), view)
    Hide(reader, view)
    print(f"Mesh camera bounds: {bounds}; parallel scale: {scale:.6g}")


def render_pressure(reader, view, output: Path, args: argparse.Namespace) -> None:
    pressure = Calculator(Input=reader)
    pressure.AttributeType = "Cell Data"
    pressure.ResultArrayName = "p_abs"
    pressure.Function = f"{args.rho}*p+{args.p_ref}"

    display = Show(pressure, view)
    display.Representation = "Surface"
    ColorBy(display, ("CELLS", "p_abs"))

    lut = GetColorTransferFunction("p_abs")
    lut.ApplyPreset("Cool to Warm", True)
    display.RescaleTransferFunctionToDataRange(True, False)
    display.SetScalarBarVisibility(view, True)

    scalar_bar = GetScalarBar(lut, view)
    set_proxy_property(scalar_bar, "Orientation", "Horizontal")
    set_proxy_property(scalar_bar, "WindowLocation", "Any Location")
    set_proxy_property(scalar_bar, "Position", [0.33, 0.02])
    set_proxy_property(scalar_bar, "ScalarBarLength", 0.34)
    set_proxy_property(scalar_bar, "Title", "p_abs [Pa]")
    set_proxy_property(scalar_bar, "ComponentTitle", "")
    set_proxy_property(scalar_bar, "LabelFormat", "%.6g")
    set_proxy_property(scalar_bar, "RangeLabelFormat", "%.6g")
    set_proxy_property(scalar_bar, "AddRangeLabels", 0)
    set_proxy_property(scalar_bar, "TitleColor", [0.0, 0.0, 0.0])
    set_proxy_property(scalar_bar, "LabelColor", [0.0, 0.0, 0.0])
    set_proxy_property(scalar_bar, "TitleBold", 1)
    set_proxy_property(scalar_bar, "LabelBold", 1)
    set_proxy_property(scalar_bar, "TitleFontSize", 24)
    set_proxy_property(scalar_bar, "LabelFontSize", 22)

    p_range = lookup_table_range(lut)
    custom_labels = [p_range[0], 0.5 * (p_range[0] + p_range[1]), p_range[1]]
    if set_proxy_property(scalar_bar, "UseCustomLabels", 1):
        set_proxy_property(scalar_bar, "CustomLabels", custom_labels)

    bounds, scale = frame_source(
        pressure,
        view,
        args.width,
        args.height,
        args.pressure_x_padding,
        args.pressure_y_padding,
        args.pressure_bottom_padding,
    )
    Render(view)
    SaveScreenshot(str(output), view)
    Hide(pressure, view)
    print(f"Pressure camera bounds: {bounds}; parallel scale: {scale:.6g}")


def main() -> None:
    args = parse_args()
    IMAGES.mkdir(exist_ok=True)

    foam_file = CASE / "backward-facing-step.foam"
    foam_file.touch(exist_ok=True)

    reader = OpenFOAMReader(FileName=str(foam_file))
    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = ["U", "p", "k", "omega", "nut"]

    latest_time = latest_numeric_time(CASE)
    reader.UpdatePipeline(time=latest_time)

    view = configure_view(args.width, args.height)
    render_mesh(reader, view, IMAGES / "paraview-mesh-overview.png", args)
    render_pressure(reader, view, IMAGES / "paraview-absolute-pressure.png", args)

    print(f"Rendered ParaView mesh image: {IMAGES / 'paraview-mesh-overview.png'}")
    print(
        "Rendered ParaView absolute pressure image: "
        f"{IMAGES / 'paraview-absolute-pressure.png'}"
    )
    print(f"Used latest result time: {latest_time:g}")
    print(f"Pressure conversion used: p_abs = {args.rho}*p + {args.p_ref}")


if __name__ == "__main__":
    main()
