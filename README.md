# OpenFOAM Backward-Facing Step Validation

This project is a compact OpenFOAM validation case for turbulent separated flow over a backward-facing step. It is intended as a portfolio-quality CFD example that demonstrates case setup, meshing, solver control, post-processing, and engineering judgment in OpenFOAM.

The current repository state is a completed baseline case. The next planned stage is a mesh density study using the same geometry, physics, convergence controls, and pressure monitors.

## Case Summary

- Solver: `simpleFoam`
- Flow model: incompressible steady RANS
- Turbulence model: `kOmegaSST`
- Inlet speed: `120 m/s`
- Geometry: 2D backward-facing step generated with `blockMesh`
- Mesh: structured hexahedral baseline, `4200` cells, `checkMesh` clean
- Primary outputs: residual history, pressure field, mesh image, and pressure convergence monitors
- Convergence monitors: pressure drop and step-edge pressure versus SIMPLE iteration

For the full baseline writeup, see [docs/baseline-report.md](docs/baseline-report.md).

For the mesh density study, see [studies/mesh-density/README.md](studies/mesh-density/README.md).

## Repository Layout

```text
case/
  0/          Initial and boundary fields
  constant/   Fluid and turbulence models
  system/     Mesh, solver, schemes, and controls
docs/         Case notes and reporting material
geometry/     Geometry references or CAD exports
images/       Figures for README and GitLab
post/         Generated post-processing output
scripts/      Run, clean, and post-processing helpers
```

## Run

From the repository root:

```bash
./scripts/run_case.sh
```

If your OpenFOAM environment is not already sourced, source it first. Common examples:

```bash
source /opt/openfoam*/etc/bashrc
source /usr/lib/openfoam/openfoam*/etc/bashrc
```

On Debian/Ubuntu package installs where the executable cannot find its global OpenFOAM dictionaries, this project script also falls back to:

```bash
export WM_PROJECT_DIR=/usr/share/openfoam
```

## Post-Process

After the solver finishes:

```bash
python3 scripts/post_process.py
python3 scripts/render_images.py
```

The post-processing scripts extract convergence information from `case/log.simpleFoam`, write plots/tables into `post/`, and generate mesh/pressure images in `images/`.

The solver does not stop immediately when residual targets are first met. `case/system/controlDict` uses `runTimeControl` to detect the residual targets and then run 200 additional SIMPLE iterations before writing the final fields. This keeps the convergence monitors long enough to confirm the pressure quantities have settled.

For true ParaView-rendered screenshots, use:

```bash
./scripts/render_paraview.sh
```

That writes `images/paraview-mesh-overview.png` and `images/paraview-absolute-pressure.png`. The wrapper tries `pvpython --force-offscreen-rendering` first to avoid X11 display warnings, then falls back to plain `pvpython`.

The absolute-pressure image uses the incompressible OpenFOAM pressure field as kinematic pressure:

```text
p_abs = rho*p + p_ref
```

Defaults are `rho = 1.225 kg/m^3` and `p_ref = 101325 Pa`. Override them when rendering if the case assumptions change:

```bash
python3 scripts/render_images.py --rho 1.225 --p-ref 101325
```

## Generated Figures

![Mesh overview](images/mesh-overview.png)

![Absolute pressure](images/absolute-pressure.png)

![Residual history](post/residuals.png)

![Pressure convergence monitors](post/pressure_monitors.png)

## Baseline Result Snapshot

The current baseline run reached the residual trigger at SIMPLE iteration `530`, then continued for 200 additional iterations and stopped at iteration `730`.

| Quantity | Final value |
| --- | --- |
| Total pressure drop | `942.5217573 Pa` |
| Static pressure delta | `-3291.722625 Pa` |
| Step-edge absolute pressure | `97767.56325 Pa` |
| Final iteration | `730` |

## Validation Plan

The first mesh density sweep is now included in `studies/mesh-density/`. It runs two coarser meshes, the baseline mesh, and four finer meshes up to 8.00x linear refinement while tracking total pressure drop and step-edge absolute pressure.

![Mesh density KPI sensitivity](studies/mesh-density/mesh_density_kpis.png)

![Mesh density pressure monitor histories](studies/mesh-density/mesh_density_convergence.png)

The next planned improvements are:

- add section-averaged upstream and outlet pressure/velocity sampling
- sample velocity profiles downstream of the step
- estimate reattachment length from wall shear or near-wall axial velocity
- compare against published backward-facing-step data

## Portfolio Talking Points

- OpenFOAM case structure and dictionary setup
- conversion of STAR-CCM+ CFD judgment into explicit OpenFOAM inputs
- mesh topology for a separated internal flow
- turbulence model selection and boundary condition reasoning
- scripted run/post-processing workflow suitable for design studies
