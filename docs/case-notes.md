# Case Notes

For the portfolio-facing baseline report, see [baseline-report.md](baseline-report.md). This file is kept as a compact engineering note for case assumptions and next-step planning.

## Objective

Demonstrate a reproducible OpenFOAM workflow for separated internal flow using a backward-facing step. The case is small enough to run quickly, but it contains the CFD decisions expected in a production workflow: topology, near-wall treatment, turbulence model choice, convergence review, and result extraction.

## Geometry

- Upstream inlet length: 0.05 m
- Downstream outlet length: 0.30 m
- Step height: 0.01 m
- Upstream channel height: 0.02 m
- Downstream channel height: 0.03 m
- 2D thickness: 0.001 m

The mesh is created directly in `case/system/blockMeshDict` so the project remains portable and easy to review.

## Physics

The baseline uses steady incompressible RANS with `kOmegaSST`. This is a practical starting point for engineering separated flow, though transient or higher-fidelity approaches may be appropriate for deeper validation.

The current inlet speed is 120 m/s. With `nu = 1e-5 m^2/s`, the upstream channel hydraulic Reynolds number is high enough to produce a clearly visible pressure variation in the portfolio pressure image while keeping the case small and fast to run.

## Boundary Conditions

- `inlet`: fixed velocity, estimated turbulent kinetic energy and specific dissipation rate
- `outlet`: fixed reference pressure with zero-gradient velocity
- `walls`: no-slip velocity and wall functions for turbulence quantities
- `frontAndBack`: `empty` to enforce 2D behavior

## Convergence Monitors

The case writes pressure and velocity probes every SIMPLE iteration through `case/system/controlDict`.

- Probe 0: upstream channel centerline, `(-0.045 0.020 0.0005)`
- Probe 1: outlet channel centerline, `(0.295 0.015 0.0005)`
- Probe 2: just downstream of the backward-facing step edge, `(0.001 0.0105 0.0005)`

`scripts/post_process.py` converts these kinematic pressure and velocity probes to engineering values:

- static pressure delta: `rho*(p_upstream - p_outlet)`
- total pressure drop: `rho*((p_upstream + 0.5*|U_upstream|^2) - (p_outlet + 0.5*|U_outlet|^2))`
- step-edge absolute pressure: `rho*p_step + p_ref`

These histories are intended to be used with residuals as convergence criteria for the mesh density study.

Solver termination is handled with `runTimeControl` in `case/system/controlDict`: once `p`, `Ux`, `Uy`, `k`, and `omega` meet the residual targets, the run continues for 200 more SIMPLE iterations. This avoids cutting off the pressure monitor histories at the first residual crossing.

## Next Validation Steps

- Add `sampleDict` for velocity profiles at multiple downstream stations.
- Add wall-shear extraction to estimate reattachment length.
- Run coarse, medium, and fine mesh variants.
- Compare reattachment length and velocity profiles against reference data.
