#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import re
import warnings
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case"
POST = ROOT / "post"
LOG = CASE / "log.simpleFoam"

RESIDUAL_RE = re.compile(
    r"Solving for (?P<field>\w+), Initial residual = (?P<initial>[-+0-9.eE]+), "
    r"Final residual = (?P<final>[-+0-9.eE]+), No Iterations (?P<iterations>\d+)"
)
TIME_RE = re.compile(r"^Time = (?P<time>[-+0-9.eE]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-process OpenFOAM convergence data.")
    parser.add_argument("--rho", type=float, default=1.225, help="Density in kg/m^3")
    parser.add_argument(
        "--p-ref",
        type=float,
        default=101325.0,
        help="Reference absolute pressure in Pa",
    )
    return parser.parse_args()


def parse_residuals(log_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current_time = ""

    for line in log_path.read_text(errors="replace").splitlines():
        time_match = TIME_RE.match(line)
        if time_match:
            current_time = time_match.group("time")
            continue

        residual_match = RESIDUAL_RE.search(line)
        if residual_match:
            rows.append(
                {
                    "time": current_time,
                    "field": residual_match.group("field"),
                    "initial_residual": residual_match.group("initial"),
                    "final_residual": residual_match.group("final"),
                    "linear_iterations": residual_match.group("iterations"),
                }
            )

    return rows


def write_residual_plot(rows: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")

    import matplotlib.pyplot as plt

    by_field: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        by_field.setdefault(row["field"], []).append(
            (float(row["time"]), float(row["initial_residual"]))
        )

    fig, ax = plt.subplots(figsize=(9, 5))
    for field, values in sorted(by_field.items()):
        times = [item[0] for item in values]
        residuals = [item[1] for item in values]
        ax.semilogy(times, residuals, label=field)

    ax.set_xlabel("Iteration")
    ax.set_ylabel("Initial residual")
    ax.set_title("simpleFoam residual history")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def probe_file(field: str) -> Path | None:
    probe_root = CASE / "postProcessing" / "pressureProbes"
    if not probe_root.exists():
        return None

    candidates = sorted(
        probe_root.glob(f"*/{field}"),
        key=lambda path: float(path.parent.name) if path.parent.name.replace(".", "", 1).isdigit() else -1,
    )
    if not candidates:
        return None

    return candidates[0]


def parse_velocity_probes(path: Path) -> dict[str, list[tuple[float, float, float]]]:
    vectors_by_iteration: dict[str, list[tuple[float, float, float]]] = {}
    vector_re = re.compile(r"\(([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\)")

    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split(maxsplit=1)
        if len(parts) != 2:
            continue

        vectors = [
            (float(match.group(1)), float(match.group(2)), float(match.group(3)))
            for match in vector_re.finditer(parts[1])
        ]
        if vectors:
            vectors_by_iteration[f"{float(parts[0]):g}"] = vectors

    return vectors_by_iteration


def mag_sq(vector: tuple[float, float, float]) -> float:
    return vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2


def late_window_limits(values: list[float], window_fraction: float = 0.2, padding: float = 0.1) -> tuple[float, float]:
    if not values:
        return 0.0, 1.0

    start = max(0, int(len(values) * (1.0 - window_fraction)))
    window = values[start:] or values
    mean = sum(window) / len(window)
    half_span = abs(mean) * padding

    if half_span == 0:
        half_span = max(1.0, max(abs(value) for value in window) * padding)

    return mean - half_span, mean + half_span


def parse_pressure_probes(
    path: Path,
    rho: float,
    p_ref: float,
    velocity_by_iteration: dict[str, list[tuple[float, float, float]]] | None = None,
) -> list[dict[str, str]]:
    rows_by_iteration: dict[str, dict[str, str]] = {}

    for line in path.read_text(errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split()
        if len(parts) < 4:
            continue

        iteration = float(parts[0])
        p_upstream = float(parts[1])
        p_outlet = float(parts[2])
        p_step = float(parts[3])
        iteration_key = f"{iteration:g}"
        static_pressure_delta = rho * (p_upstream - p_outlet)
        p_step_abs = rho * p_step + p_ref
        total_pressure_drop = ""

        if velocity_by_iteration and iteration_key in velocity_by_iteration:
            velocities = velocity_by_iteration[iteration_key]
            if len(velocities) >= 2:
                total_upstream = p_upstream + 0.5 * mag_sq(velocities[0])
                total_outlet = p_outlet + 0.5 * mag_sq(velocities[1])
                total_pressure_drop = f"{rho * (total_upstream - total_outlet):.10g}"

        rows_by_iteration[iteration_key] = {
            "iteration": iteration_key,
            "p_upstream_kinematic": f"{p_upstream:.10g}",
            "p_outlet_kinematic": f"{p_outlet:.10g}",
            "p_step_kinematic": f"{p_step:.10g}",
            "static_pressure_delta_pa": f"{static_pressure_delta:.10g}",
            "total_pressure_drop_pa": total_pressure_drop,
            "p_step_abs_pa": f"{p_step_abs:.10g}",
        }

    return list(rows_by_iteration.values())


def write_pressure_monitor_csv(rows: list[dict[str, str]], output: Path) -> None:
    with output.open("w", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "iteration",
                "p_upstream_kinematic",
                "p_outlet_kinematic",
                "p_step_kinematic",
                "static_pressure_delta_pa",
                "total_pressure_drop_pa",
                "p_step_abs_pa",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def write_pressure_monitor_plot(rows: list[dict[str, str]], output: Path) -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    warnings.filterwarnings("ignore", message="Unable to import Axes3D.*")

    import matplotlib.pyplot as plt

    iterations = [float(row["iteration"]) for row in rows]
    pressure_metric_key = (
        "total_pressure_drop_pa"
        if rows and rows[-1].get("total_pressure_drop_pa")
        else "static_pressure_delta_pa"
    )
    pressure_drop = [float(row[pressure_metric_key]) for row in rows]
    p_step_abs = [float(row["p_step_abs_pa"]) for row in rows]

    fig, axes = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

    axes[0].plot(iterations, pressure_drop, color="#1f77b4", linewidth=1.6)
    axes[0].set_ylabel(
        "Total pressure drop [Pa]"
        if pressure_metric_key == "total_pressure_drop_pa"
        else "Static pressure delta [Pa]"
    )
    axes[0].set_title("Pressure convergence monitors")
    axes[0].set_ylim(*late_window_limits(pressure_drop))
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(iterations, p_step_abs, color="#d62728", linewidth=1.6)
    axes[1].set_xlabel("SIMPLE iteration")
    axes[1].set_ylabel("Step-edge p_abs [Pa]")
    axes[1].set_ylim(*late_window_limits(p_step_abs))
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig.savefig(output, dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()
    POST.mkdir(exist_ok=True)

    if not LOG.exists():
        raise SystemExit(f"Missing solver log: {LOG}. Run ./scripts/run_case.sh first.")

    rows = parse_residuals(LOG)
    output = POST / "residuals.csv"

    with output.open("w", newline="") as stream:
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
        writer.writerows(rows)

    plot_output = POST / "residuals.png"
    write_residual_plot(rows, plot_output)

    p_probe_file = probe_file("p")
    u_probe_file = probe_file("U")
    velocity_by_iteration = parse_velocity_probes(u_probe_file) if u_probe_file else None
    if p_probe_file:
        pressure_rows = parse_pressure_probes(
            p_probe_file,
            args.rho,
            args.p_ref,
            velocity_by_iteration,
        )
        pressure_csv = POST / "pressure_monitors.csv"
        pressure_plot = POST / "pressure_monitors.png"
        write_pressure_monitor_csv(pressure_rows, pressure_csv)
        write_pressure_monitor_plot(pressure_rows, pressure_plot)
        print(f"Wrote {len(pressure_rows)} pressure monitor rows to {pressure_csv}")
        print(f"Wrote pressure monitor plot to {pressure_plot}")
    else:
        print("No pressure probe file found; run ./scripts/run_case.sh to generate monitors.")

    print(f"Wrote {len(rows)} residual rows to {output}")
    print(f"Wrote residual plot to {plot_output}")


if __name__ == "__main__":
    main()
