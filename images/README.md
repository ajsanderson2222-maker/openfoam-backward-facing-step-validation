# Images

Store ParaView screenshots and generated result figures here.

Recommended first figures:

- mesh overview
- velocity magnitude contours
- pressure contours
- streamlines or vectors near the recirculation zone

Generate baseline figures with:

```bash
python3 scripts/render_images.py
```

Generated images:

- `mesh-overview.png`
- `absolute-pressure.png`

ParaView-rendered images:

```bash
./scripts/render_paraview.sh
```

- `paraview-mesh-overview.png`
- `paraview-absolute-pressure.png`
