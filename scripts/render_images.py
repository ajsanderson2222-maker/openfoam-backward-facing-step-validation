#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import os
import re
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case"
IMAGES = ROOT / "images"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render mesh and absolute-pressure images from OpenFOAM files."
    )
    parser.add_argument("--rho", type=float, default=1.225, help="Density in kg/m^3")
    parser.add_argument(
        "--p-ref",
        type=float,
        default=101325.0,
        help="Reference absolute pressure in Pa",
    )
    parser.add_argument("--dpi", type=int, default=180, help="Output image DPI")
    return parser.parse_args()


def latest_numeric_time(case_dir: Path) -> Path:
    times: list[tuple[float, Path]] = []
    for path in case_dir.iterdir():
        if path.is_dir():
            try:
                times.append((float(path.name), path))
            except ValueError:
                pass

    if not times:
        raise SystemExit("No result time directories found. Run ./scripts/run_case.sh first.")

    return max(times, key=lambda item: item[0])[1]


def foam_payload(path: Path) -> str:
    text = path.read_text(errors="replace")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//.*", "", text)
    return text


def parse_points(path: Path) -> list[tuple[float, float]]:
    text = foam_payload(path)
    points: list[tuple[float, float]] = []
    for match in re.finditer(r"\(([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+[-+0-9.eE]+\)", text):
        points.append((float(match.group(1)), float(match.group(2))))
    return points


def parse_faces(path: Path) -> list[list[int]]:
    faces: list[list[int]] = []
    for line in foam_payload(path).splitlines():
        match = re.search(r"\d+\(([^)]+)\)", line)
        if match:
            faces.append([int(item) for item in match.group(1).split()])
    return faces


def parse_labels(path: Path) -> list[int]:
    labels: list[int] = []
    for line in foam_payload(path).splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            labels.append(int(stripped))
    return labels[1:]


def parse_scalar_internal_field(path: Path) -> list[float]:
    text = foam_payload(path)
    uniform = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)", text)
    if uniform:
        return [float(uniform.group(1))]

    match = re.search(r"internalField\s+nonuniform\s+List<scalar>\s+\d+\s*\((.*?)\)", text, re.S)
    if not match:
        raise SystemExit(f"Could not parse internal scalar field from {path}")

    return [float(item) for item in match.group(1).split()]


def cell_polygons(
    points: list[tuple[float, float]],
    faces: list[list[int]],
    owners: list[int],
    neighbours: list[int],
) -> list[list[tuple[float, float]]]:
    n_cells = max(max(owners), max(neighbours, default=0)) + 1
    cell_point_ids: list[set[int]] = [set() for _ in range(n_cells)]

    for face, owner in zip(faces, owners):
        cell_point_ids[owner].update(face)

    for face, neighbour in zip(faces[: len(neighbours)], neighbours):
        cell_point_ids[neighbour].update(face)

    polygons: list[list[tuple[float, float]]] = []
    for ids in cell_point_ids:
        unique_xy = sorted({points[index] for index in ids})
        cx = sum(point[0] for point in unique_xy) / len(unique_xy)
        cy = sum(point[1] for point in unique_xy) / len(unique_xy)
        unique_xy.sort(key=lambda point: math.atan2(point[1] - cy, point[0] - cx))
        polygons.append(unique_xy)

    return polygons


def configure_matplotlib():
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")

    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection, PolyCollection

    return plt, LineCollection, PolyCollection


def render_mesh(points, faces, output: Path, dpi: int) -> None:
    plt, LineCollection, _ = configure_matplotlib()
    lines = []
    for face in faces:
        xy = [points[index] for index in face]
        for start, end in zip(xy, xy[1:] + xy[:1]):
            if start != end:
                lines.append([start, end])

    fig, ax = plt.subplots(figsize=(12, 4), dpi=dpi)
    ax.add_collection(LineCollection(lines, colors="#1f2933", linewidths=0.22))
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.055, 0.305)
    ax.set_ylim(-0.003, 0.033)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title("Backward-facing step mesh")
    ax.grid(True, alpha=0.18)
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def render_pressure(polygons, p_abs, output: Path, dpi: int) -> None:
    plt, _, PolyCollection = configure_matplotlib()
    from matplotlib.ticker import ScalarFormatter

    fig, ax = plt.subplots(figsize=(12, 4), dpi=dpi)
    collection = PolyCollection(polygons, array=p_abs, cmap="coolwarm", edgecolors="none")
    ax.add_collection(collection)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-0.055, 0.305)
    ax.set_ylim(-0.003, 0.033)
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title("Absolute pressure [Pa]")
    colorbar = fig.colorbar(collection, ax=ax, label="p_abs [Pa]", shrink=0.82)
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)
    colorbar.formatter = formatter
    colorbar.update_ticks()
    fig.tight_layout()
    fig.savefig(output)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    IMAGES.mkdir(exist_ok=True)

    mesh_dir = CASE / "constant" / "polyMesh"
    latest_time = latest_numeric_time(CASE)

    points = parse_points(mesh_dir / "points")
    faces = parse_faces(mesh_dir / "faces")
    owners = parse_labels(mesh_dir / "owner")
    neighbours = parse_labels(mesh_dir / "neighbour")
    polygons = cell_polygons(points, faces, owners, neighbours)

    p = parse_scalar_internal_field(latest_time / "p")
    if len(p) == 1:
        p = p * len(polygons)
    if len(p) != len(polygons):
        raise SystemExit(f"Pressure values ({len(p)}) do not match cells ({len(polygons)})")

    p_abs = [args.rho * value + args.p_ref for value in p]

    render_mesh(points, faces, IMAGES / "mesh-overview.png", args.dpi)
    render_pressure(polygons, p_abs, IMAGES / "absolute-pressure.png", args.dpi)

    print(f"Rendered mesh image: {IMAGES / 'mesh-overview.png'}")
    print(f"Rendered absolute pressure image: {IMAGES / 'absolute-pressure.png'}")
    print(f"Used latest result directory: {latest_time.name}")
    print(f"Pressure conversion used: p_abs = {args.rho}*p + {args.p_ref}")


if __name__ == "__main__":
    main()
