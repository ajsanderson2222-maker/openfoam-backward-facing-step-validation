#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_CASE = ROOT / "case"
STUDY = ROOT / "studies" / "mesh-density"
RUNS = STUDY / "runs"
SUMMARY_CSV = STUDY / "mesh_density_results.csv"
HISTORY_CSV = STUDY / "mesh_density_histories.csv"
PLOT = STUDY / "mesh_density_kpis.png"
CONVERGENCE_PLOT = STUDY / "mesh_density_convergence.png"

RHO = 1.225
P_REF = 101325.0

sys.path.insert(0, str(ROOT / "scripts"))
from post_process import (  # noqa: E402
    late_window_limits,
    parse_pressure_probes,
    parse_residuals,
    parse_velocity_probes,
    write_pressure_monitor_csv,
)


@dataclass(frozen=True)
class MeshVariant:
    name: str
    label: str
    upstream_cells: tuple[int, int, int]
    lower_cells: tuple[int, int, int]
    upper_cells: tuple[int, int, int]

    @property
    def cell_count(self) -> int:
        return (
            self.upstream_cells[0] * self.upstream_cells[1] * self.upstream_cells[2]
            + self.lower_cells[0] * self.lower_cells[1] * self.lower_cells[2]
            + self.upper_cells[0] * self.upper_cells[1] * self.upper_cells[2]
        )


VARIANTS = [
    MeshVariant("coarse_050", "Coarse 0.50x", (15, 10, 1), (60, 5, 1), (60, 10, 1)),
    MeshVariant("coarse_075", "Coarse 0.75x", (22, 15, 1), (90, 8, 1), (90, 15, 1)),
    MeshVariant("baseline_100", "Baseline 1.00x", (30, 20, 1), (120, 10, 1), (120, 20, 1)),
    MeshVariant("fine_150", "Fine 1.50x", (45, 30, 1), (180, 15, 1), (180, 30, 1)),
    MeshVariant("fine_200", "Fine 2.00x", (60, 40, 1), (240, 20, 1), (240, 40, 1)),
    MeshVariant("fine_400", "Fine 4.00x", (120, 80, 1), (480, 40, 1), (480, 80, 1)),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the backward-facing-step mesh density study.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and rebuild existing study run directories.",
    )
    parser.add_argument(
        "--setup-only",
        action="store_true",
        help="Create the study cases without running OpenFOAM.",
    )
    return parser.parse_args()


def tuple_text(values: tuple[int, int, int]) -> str:
    return f"({values[0]} {values[1]} {values[2]})"


def clean_case_output(case_dir: Path) -> None:
    for path in case_dir.iterdir():
        if path.is_dir() and ((path.name[0].isdigit() and path.name != "0") or path.name.startswith("processor")):
            shutil.rmtree(path)

    for path in [
        case_dir / "postProcessing",
        case_dir / "constant" / "polyMesh",
    ]:
        if path.exists():
            shutil.rmtree(path)

    for pattern in ("log.*", "*.foam"):
        for path in case_dir.glob(pattern):
            path.unlink()


def copy_base_case(case_dir: Path, force: bool) -> None:
    if case_dir.exists():
        if not force:
            return
        shutil.rmtree(case_dir)

    ignore = shutil.ignore_patterns(
        "[1-9]*",
        "processor*",
        "postProcessing",
        "polyMesh",
        "log.*",
        "*.foam",
    )
    shutil.copytree(BASE_CASE, case_dir, ignore=ignore)
    clean_case_output(case_dir)


def write_block_mesh(case_dir: Path, variant: MeshVariant) -> None:
    block_mesh = (BASE_CASE / "system" / "blockMeshDict").read_text()
    block_mesh = block_mesh.replace(
        "hex (0 1 3 2 8 9 11 10) (30 20 1) simpleGrading (1 1 1)",
        f"hex (0 1 3 2 8 9 11 10) {tuple_text(variant.upstream_cells)} simpleGrading (1 1 1)",
    )
    block_mesh = block_mesh.replace(
        "hex (4 5 6 1 12 13 14 9) (120 10 1) simpleGrading (1 1 1)",
        f"hex (4 5 6 1 12 13 14 9) {tuple_text(variant.lower_cells)} simpleGrading (1 1 1)",
    )
    block_mesh = block_mesh.replace(
        "hex (1 6 7 3 9 14 15 11) (120 20 1) simpleGrading (1 1 1)",
        f"hex (1 6 7 3 9 14 15 11) {tuple_text(variant.upper_cells)} simpleGrading (1 1 1)",
    )
    (case_dir / "system" / "blockMeshDict").write_text(block_mesh)


def run_command(case_dir: Path, command: list[str], log_name: str) -> None:
    env = os.environ.copy()
    env.setdefault("WM_PROJECT_DIR", "/usr/share/openfoam")

    with (case_dir / log_name).open("w") as log:
        process = subprocess.run(
            command,
            cwd=case_dir,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    if process.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed for {case_dir}; see {case_dir / log_name}")


def run_case(case_dir: Path) -> None:
    run_command(case_dir, ["blockMesh"], "log.blockMesh")
    run_command(case_dir, ["checkMesh"], "log.checkMesh")
    run_command(case_dir, ["simpleFoam"], "log.simpleFoam")
    (case_dir / "backward-facing-step.foam").touch()


def has_completed_run(case_dir: Path) -> bool:
    log_path = case_dir / "log.simpleFoam"
    probe_root = case_dir / "postProcessing" / "pressureProbes"
    if not log_path.exists() or not probe_root.exists():
        return False

    log_tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
    return "End" in log_tail and any(probe_root.glob("*/p")) and any(probe_root.glob("*/U"))


def first_probe_file(case_dir: Path, field: str) -> Path:
    candidates = sorted(
        (case_dir / "postProcessing" / "pressureProbes").glob(f"*/{field}"),
        key=lambda path: float(path.parent.name),
    )
    if not candidates:
        raise RuntimeError(f"No pressure probe file for {field} in {case_dir}")
    return candidates[0]


def final_time_dir(case_dir: Path) -> str:
    times = [
        path.name
        for path in case_dir.iterdir()
        if path.is_dir() and path.name[0].isdigit() and path.name != "0"
    ]
    if not times:
        return ""
    return max(times, key=lambda value: float(value))


def find_trigger_iteration(log_path: Path) -> str:
    lines = log_path.read_text(errors="replace").splitlines()
    current_time = ""
    trigger_time = ""

    for line in lines:
        time_match = re.match(r"^Time = ([-+0-9.eE]+)", line)
        if time_match:
            current_time = f"{float(time_match.group(1)):g}"
            continue
        if "condition satisfied" in line and "equationInitialResidual" in line:
            trigger_time = current_time

    return trigger_time


def parse_check_mesh(log_path: Path) -> dict[str, str]:
    text = log_path.read_text(errors="replace")
    metrics = {
        "max_aspect_ratio": "",
        "max_non_orthogonality": "",
        "max_skewness": "",
        "mesh_ok": "yes" if "Mesh OK" in text else "no",
    }

    aspect = re.search(r"Max aspect ratio = ([^\s]+)", text)
    non_ortho = re.search(r"Mesh non-orthogonality Max: ([^\s]+)", text)
    skew = re.search(r"Max skewness = ([^\s]+)", text)

    if aspect:
        metrics["max_aspect_ratio"] = aspect.group(1)
    if non_ortho:
        metrics["max_non_orthogonality"] = non_ortho.group(1)
    if skew:
        metrics["max_skewness"] = skew.group(1)

    return metrics


def collect_variant_outputs(variant: MeshVariant, case_dir: Path) -> tuple[dict[str, str], list[dict[str, str]]]:
    p_file = first_probe_file(case_dir, "p")
    u_file = first_probe_file(case_dir, "U")
    velocity_by_iteration = parse_velocity_probes(u_file)
    pressure_rows = parse_pressure_probes(p_file, RHO, P_REF, velocity_by_iteration)

    output_dir = STUDY / variant.name
    output_dir.mkdir(parents=True, exist_ok=True)
    write_pressure_monitor_csv(pressure_rows, output_dir / "pressure_monitors.csv")

    residual_rows = parse_residuals(case_dir / "log.simpleFoam")
    with (output_dir / "residuals.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "time",
                "field",
                "initial_residual",
                "final_residual",
                "linear_iterations",
            ],
        )
        writer.writeheader()
        writer.writerows(residual_rows)

    final = pressure_rows[-1]
    mesh_metrics = parse_check_mesh(case_dir / "log.checkMesh")
    residual_trigger_iteration = find_trigger_iteration(case_dir / "log.simpleFoam")
    summary = {
        "variant": variant.name,
        "label": variant.label,
        "cell_count": str(variant.cell_count),
        "upstream_cells": "x".join(str(value) for value in variant.upstream_cells),
        "lower_cells": "x".join(str(value) for value in variant.lower_cells),
        "upper_cells": "x".join(str(value) for value in variant.upper_cells),
        "residual_triggered": "yes" if residual_trigger_iteration else "no",
        "residual_trigger_iteration": residual_trigger_iteration,
        "final_iteration": final["iteration"],
        "final_time_dir": final_time_dir(case_dir),
        "static_pressure_delta_pa": final["static_pressure_delta_pa"],
        "total_pressure_drop_pa": final["total_pressure_drop_pa"],
        "p_step_abs_pa": final["p_step_abs_pa"],
        **mesh_metrics,
    }

    histories = []
    for row in pressure_rows:
        histories.append(
            {
                "variant": variant.name,
                "label": variant.label,
                "cell_count": str(variant.cell_count),
                **row,
            }
        )

    return summary, histories


def write_summary(rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "variant",
        "label",
        "cell_count",
        "upstream_cells",
        "lower_cells",
        "upper_cells",
        "residual_triggered",
        "residual_trigger_iteration",
        "final_iteration",
        "final_time_dir",
        "static_pressure_delta_pa",
        "total_pressure_drop_pa",
        "p_step_abs_pa",
        "max_aspect_ratio",
        "max_non_orthogonality",
        "max_skewness",
        "mesh_ok",
    ]

    with SUMMARY_CSV.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_histories(rows: list[dict[str, str]]) -> None:
    fieldnames = [
        "variant",
        "label",
        "cell_count",
        "iteration",
        "p_upstream_kinematic",
        "p_outlet_kinematic",
        "p_step_kinematic",
        "static_pressure_delta_pa",
        "total_pressure_drop_pa",
        "p_step_abs_pa",
    ]

    with HISTORY_CSV.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def padded_limits(values: list[float], padding: float = 0.1) -> tuple[float, float]:
    lower = min(values)
    upper = max(values)
    span = upper - lower
    if span == 0:
        span = max(abs(lower) * padding, 1.0)
    return lower - span * padding, upper + span * padding


def combined_late_limits(series_values: list[list[float]], padding: float = 0.1) -> tuple[float, float]:
    limits = [late_window_limits(values, padding=padding) for values in series_values if values]
    if not limits:
        return 0.0, 1.0
    return min(limit[0] for limit in limits), max(limit[1] for limit in limits)


def write_plots(summary_rows: list[dict[str, str]], history_rows: list[dict[str, str]]) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")
    import matplotlib.pyplot as plt

    summary = sorted(summary_rows, key=lambda row: int(row["cell_count"]))
    cells = [int(row["cell_count"]) for row in summary]
    labels = [row["label"] for row in summary]
    pressure_drop = [float(row["total_pressure_drop_pa"]) for row in summary]
    step_pressure = [float(row["p_step_abs_pa"]) for row in summary]

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    axes[0].plot(cells, pressure_drop, marker="o", linewidth=1.8, color="#1f77b4")
    axes[0].set_ylabel("Total pressure drop [Pa]")
    axes[0].set_ylim(*padded_limits(pressure_drop))
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(cells, step_pressure, marker="o", linewidth=1.8, color="#d62728")
    axes[1].set_xlabel("Cell count")
    axes[1].set_ylabel("Step-edge p_abs [Pa]")
    axes[1].set_ylim(*padded_limits(step_pressure))
    axes[1].grid(True, alpha=0.3)
    axes[1].set_xticks(cells, labels, rotation=20, ha="right")

    fig.suptitle("Mesh density KPI sensitivity")
    fig.tight_layout()
    fig.savefig(PLOT, dpi=160)
    plt.close(fig)

    by_variant: dict[str, list[dict[str, str]]] = {}
    for row in history_rows:
        by_variant.setdefault(row["variant"], []).append(row)

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)
    drop_series = []
    step_series = []
    for row in summary:
        rows = by_variant[row["variant"]]
        iterations = [float(item["iteration"]) for item in rows]
        drops = [float(item["total_pressure_drop_pa"]) for item in rows]
        steps = [float(item["p_step_abs_pa"]) for item in rows]
        drop_series.append(drops)
        step_series.append(steps)
        axes[0].plot(iterations, drops, linewidth=1.2, label=row["label"])
        axes[1].plot(iterations, steps, linewidth=1.2, label=row["label"])

    axes[0].set_ylabel("Total pressure drop [Pa]")
    axes[0].set_ylim(*combined_late_limits(drop_series))
    axes[0].grid(True, alpha=0.3)
    axes[0].legend(fontsize=8)
    axes[1].set_xlabel("SIMPLE iteration")
    axes[1].set_ylabel("Step-edge p_abs [Pa]")
    axes[1].set_ylim(*combined_late_limits(step_series))
    axes[1].grid(True, alpha=0.3)
    fig.suptitle("Mesh density pressure monitor histories")
    fig.tight_layout()
    fig.savefig(CONVERGENCE_PLOT, dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    STUDY.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, str]] = []
    history_rows: list[dict[str, str]] = []

    for variant in VARIANTS:
        case_dir = RUNS / variant.name / "case"
        print(f"Preparing {variant.label}: {variant.cell_count} cells", flush=True)
        copy_base_case(case_dir, args.force)
        write_block_mesh(case_dir, variant)

        if not args.setup_only:
            if args.force or not has_completed_run(case_dir):
                print(f"Running {variant.label}", flush=True)
                clean_case_output(case_dir)
                run_case(case_dir)
            else:
                print(f"Using completed {variant.label} run", flush=True)
            summary, histories = collect_variant_outputs(variant, case_dir)
            summary_rows.append(summary)
            history_rows.extend(histories)

    if args.setup_only:
        print(f"Study cases written under {RUNS}")
        return

    write_summary(summary_rows)
    write_histories(history_rows)
    write_plots(summary_rows, history_rows)

    print(f"Wrote {SUMMARY_CSV}")
    print(f"Wrote {HISTORY_CSV}")
    print(f"Wrote {PLOT}")
    print(f"Wrote {CONVERGENCE_PLOT}")


if __name__ == "__main__":
    main()
