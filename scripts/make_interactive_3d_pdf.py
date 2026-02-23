import math
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas


Point3 = Tuple[float, float, float]
Point2 = Tuple[float, float]


@dataclass(frozen=True)
class SeqConfig:
    key: str
    label: str
    speed_label: str
    page_duration: float | None
    autoplay: bool


SEQS = [
    SeqConfig("manual", "Manual", "Manual", None, False),
    SeqConfig("slow", "Auto Spin", "Slow", 0.30, True),
    SeqConfig("fast", "Auto Spin", "Fast", 0.10, True),
]

FRAME_COUNT = 48
ZOOMS = [1.0, 1.35]


def ensure_dirs() -> None:
    os.makedirs("output/pdf", exist_ok=True)
    os.makedirs("tmp/pdfs", exist_ok=True)


def dest_name(seq: str, frame: int, zoom_idx: int) -> str:
    return f"{seq}_z{zoom_idx}_f{frame:02d}"


def clamp_index(i: int, n: int) -> int:
    return i % n


def dot(a: Point3, b: Point3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def sub(a: Point3, b: Point3) -> Point3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def cross(a: Point3, b: Point3) -> Point3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def norm(v: Point3) -> Point3:
    mag = math.sqrt(dot(v, v)) or 1.0
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def rotate_xyz(p: Point3, ax: float, ay: float, az: float) -> Point3:
    x, y, z = p
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)

    # X rotation
    y, z = y * cx - z * sx, y * sx + z * cx
    # Y rotation
    x, z = x * cy + z * sy, -x * sy + z * cy
    # Z rotation
    x, y = x * cz - y * sz, x * sz + y * cz
    return (x, y, z)


def project(p: Point3, center: Point2, scale: float, camera_z: float = 6.0) -> Point2:
    x, y, z = p
    depth = camera_z - z
    f = scale / max(1.0, depth)
    return (center[0] + x * f, center[1] + y * f)


def cube_geometry() -> Tuple[List[Point3], List[Tuple[int, int, int, int]], List[Tuple[int, int]]]:
    s = 1.25
    vertices: List[Point3] = [
        (-s, -s, -s),
        (s, -s, -s),
        (s, s, -s),
        (-s, s, -s),
        (-s, -s, s),
        (s, -s, s),
        (s, s, s),
        (-s, s, s),
    ]
    faces = [
        (0, 1, 2, 3),  # back
        (4, 5, 6, 7),  # front
        (0, 1, 5, 4),  # bottom
        (2, 3, 7, 6),  # top
        (1, 2, 6, 5),  # right
        (0, 3, 7, 4),  # left
    ]
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    return vertices, faces, edges


def color_blend(c1: Tuple[int, int, int], c2: Tuple[int, int, int], t: float) -> colors.Color:
    t = max(0.0, min(1.0, t))
    r = int(c1[0] + (c2[0] - c1[0]) * t)
    g = int(c1[1] + (c2[1] - c1[1]) * t)
    b = int(c1[2] + (c2[2] - c1[2]) * t)
    return colors.Color(r / 255, g / 255, b / 255)


def draw_rounded_button(
    c: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    *,
    fill: colors.Color,
    stroke: colors.Color,
    text: colors.Color,
    dest: str | None = None,
    font_size: int = 10,
) -> None:
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(1)
    c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
    c.setFillColor(text)
    c.setFont("Helvetica-Bold", font_size)
    tw = c.stringWidth(label, "Helvetica-Bold", font_size)
    c.drawString(x + (w - tw) / 2, y + (h - font_size) / 2 + 2, label)
    if dest:
        c.linkRect("", destinationname=dest, Rect=(x, y, x + w, y + h), relative=0, thickness=0)


def draw_background(c: canvas.Canvas, width: float, height: float) -> None:
    # Simple banded gradient to keep the file vector-only and small.
    bands = 20
    top = (10, 22, 45)
    bottom = (2, 7, 16)
    for i in range(bands):
        t = i / max(1, bands - 1)
        col = color_blend(top, bottom, t)
        c.setFillColor(col)
        y = height * (1 - (i + 1) / bands)
        c.rect(0, y, width, height / bands + 1, stroke=0, fill=1)

    # Decorative stars (deterministic coordinates).
    c.setFillColor(colors.Color(0.95, 0.98, 1.0))
    stars = [
        (72, 512, 1.4),
        (128, 540, 1.0),
        (216, 486, 1.6),
        (340, 556, 1.1),
        (498, 530, 1.3),
        (620, 502, 1.0),
        (708, 542, 1.7),
    ]
    for x, y, r in stars:
        c.circle(x, y, r, stroke=0, fill=1)


def draw_panel(
    c: canvas.Canvas,
    width: float,
    panel_y: float,
    panel_h: float,
    seq: SeqConfig,
    frame: int | None,
    zoom_idx: int | None,
) -> None:
    c.setFillColor(colors.Color(0.04, 0.08, 0.15))
    c.setStrokeColor(colors.Color(0.20, 0.35, 0.55))
    c.roundRect(24, panel_y, width - 48, panel_h, 10, stroke=1, fill=1)
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(colors.white)
    c.drawString(40, panel_y + panel_h - 20, "Interactive 3D Cube")

    c.setFont("Helvetica", 10)
    info = f"Mode: {seq.label} ({seq.speed_label})"
    if frame is not None and zoom_idx is not None:
        info += f"  |  Frame: {frame + 1}/{FRAME_COUNT}  |  Zoom: {ZOOMS[zoom_idx]:.2f}x"
    c.drawString(40, panel_y + panel_h - 36, info)


def draw_cube_scene(
    c: canvas.Canvas,
    width: float,
    height: float,
    *,
    frame_idx: int,
    zoom_idx: int,
    seq: SeqConfig,
) -> None:
    draw_background(c, width, height)

    panel_h = 92
    panel_y = 18
    scene_bottom = panel_y + panel_h + 8
    scene_top = height - 28
    scene_h = scene_top - scene_bottom
    scene_w = width - 48
    scene_x = 24
    scene_y = scene_bottom

    # Frame window
    c.setFillColor(colors.Color(0.02, 0.04, 0.08))
    c.setStrokeColor(colors.Color(0.18, 0.32, 0.50))
    c.roundRect(scene_x, scene_y, scene_w, scene_h, 12, stroke=1, fill=1)

    # Ground grid
    grid_y = scene_y + scene_h * 0.26
    c.setStrokeColor(colors.Color(0.10, 0.26, 0.40))
    c.setLineWidth(0.6)
    for i in range(11):
        y = grid_y + i * 10
        if y > scene_y + scene_h - 20:
            break
        c.line(scene_x + 30, y, scene_x + scene_w - 30, y)
    for i in range(15):
        x = scene_x + 40 + i * 34
        if x > scene_x + scene_w - 30:
            break
        c.line(x, grid_y, x, min(scene_y + scene_h - 20, grid_y + 110))

    center = (scene_x + scene_w * 0.5, scene_y + scene_h * 0.62)
    scale = 520 * ZOOMS[zoom_idx]

    t = frame_idx / FRAME_COUNT
    ax = 0.55 + math.sin(t * math.tau) * 0.25
    ay = t * math.tau
    az = 0.18 + math.cos(t * math.tau * 2.0) * 0.08

    verts, faces, edges = cube_geometry()
    rverts = [rotate_xyz(v, ax, ay, az) for v in verts]
    pverts = [project(v, center, scale) for v in rverts]

    # Shadow based on footprint.
    shadow_pts = [(center[0] + rv[0] * 38 * ZOOMS[zoom_idx], scene_y + scene_h * 0.35 + rv[2] * 8) for rv in rverts]
    c.setFillColor(colors.Color(0, 0, 0, alpha=0.35))
    c.setStrokeColor(colors.Color(0, 0, 0, alpha=0))
    path = c.beginPath()
    path.moveTo(*shadow_pts[0])
    for x, y in shadow_pts[1:]:
        path.lineTo(x, y)
    path.close()
    c.drawPath(path, fill=1, stroke=0)

    light = norm((1.0, 1.3, 2.0))
    base_dark = (30, 95, 160)
    base_light = (110, 235, 255)

    face_depths = []
    for face in faces:
        pts3 = [rverts[i] for i in face]
        v1 = sub(pts3[1], pts3[0])
        v2 = sub(pts3[2], pts3[0])
        n = norm(cross(v1, v2))
        intensity = (dot(n, light) + 1) / 2
        avg_z = sum(p[2] for p in pts3) / 4
        face_depths.append((avg_z, intensity, face))

    face_depths.sort(key=lambda x: x[0])
    for _, intensity, face in face_depths:
        poly2 = [pverts[i] for i in face]
        fill_col = color_blend(base_dark, base_light, 0.20 + 0.75 * intensity)
        c.setFillColor(fill_col)
        c.setStrokeColor(colors.Color(0.07, 0.20, 0.35))
        c.setLineWidth(1.0)
        path = c.beginPath()
        path.moveTo(*poly2[0])
        for x, y in poly2[1:]:
            path.lineTo(x, y)
        path.close()
        c.drawPath(path, fill=1, stroke=1)

    # Highlight edge overlay
    c.setStrokeColor(colors.Color(0.90, 0.98, 1.0))
    c.setLineWidth(0.9)
    for a, b in edges:
        c.line(pverts[a][0], pverts[a][1], pverts[b][0], pverts[b][1])

    # Glint / halo
    c.setStrokeColor(colors.Color(0.30, 0.95, 1.0))
    c.setLineWidth(1.2)
    c.circle(center[0], center[1], 120 * ZOOMS[zoom_idx], stroke=1, fill=0)
    c.setStrokeColor(colors.Color(0.16, 0.45, 0.65))
    c.setLineWidth(0.6)
    c.circle(center[0], center[1], 165 * ZOOMS[zoom_idx], stroke=1, fill=0)

    draw_panel(c, width, panel_y, panel_h, seq, frame_idx, zoom_idx)


def draw_home_page(c: canvas.Canvas, width: float, height: float) -> None:
    draw_background(c, width, height)
    c.bookmarkPage("home")

    c.setFillColor(colors.Color(0.02, 0.04, 0.08))
    c.setStrokeColor(colors.Color(0.18, 0.32, 0.50))
    c.roundRect(24, 24, width - 48, height - 48, 14, stroke=1, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(44, height - 72, "Interactive 3D Animation PDF")

    c.setFont("Helvetica", 11)
    lines = [
        "This PDF contains a rotating 3D cube animation built as linked frame pages.",
        "Use the buttons below to enter manual mode or autoplay modes.",
        "Controls are embedded as PDF links so they work in many viewers.",
        "Autoplay speed (page timing) works best in Adobe Acrobat / Reader presentation mode.",
    ]
    y = height - 100
    for line in lines:
        c.drawString(44, y, line)
        y -= 16

    # Preview illustration ring
    c.setStrokeColor(colors.Color(0.22, 0.65, 0.95))
    c.setLineWidth(2)
    c.circle(width - 150, height - 150, 74, stroke=1, fill=0)
    c.setStrokeColor(colors.Color(0.10, 0.35, 0.55))
    c.circle(width - 150, height - 150, 98, stroke=1, fill=0)
    c.setFillColor(colors.Color(0.15, 0.80, 0.95))
    c.circle(width - 150, height - 150, 4, stroke=0, fill=1)

    bx = 44
    by = height - 230
    bw = 180
    bh = 28
    gap = 12

    draw_rounded_button(
        c,
        bx,
        by,
        bw,
        bh,
        "Start Manual (1.00x)",
        fill=colors.Color(0.10, 0.24, 0.39),
        stroke=colors.Color(0.27, 0.55, 0.82),
        text=colors.white,
        dest=dest_name("manual", 0, 0),
    )
    draw_rounded_button(
        c,
        bx + bw + gap,
        by,
        bw,
        bh,
        "Start Manual (1.35x)",
        fill=colors.Color(0.10, 0.24, 0.39),
        stroke=colors.Color(0.27, 0.55, 0.82),
        text=colors.white,
        dest=dest_name("manual", 0, 1),
    )
    draw_rounded_button(
        c,
        bx,
        by - 42,
        bw,
        bh,
        "Play Slow",
        fill=colors.Color(0.08, 0.22, 0.18),
        stroke=colors.Color(0.25, 0.72, 0.58),
        text=colors.white,
        dest=dest_name("slow", 0, 0),
    )
    draw_rounded_button(
        c,
        bx + bw + gap,
        by - 42,
        bw,
        bh,
        "Play Fast",
        fill=colors.Color(0.24, 0.16, 0.08),
        stroke=colors.Color(0.93, 0.62, 0.27),
        text=colors.white,
        dest=dest_name("fast", 0, 0),
    )
    draw_rounded_button(
        c,
        bx,
        by - 84,
        bw * 2 + gap,
        bh,
        "Neural Net Agent Simulation Page",
        fill=colors.Color(0.14, 0.10, 0.24),
        stroke=colors.Color(0.52, 0.44, 0.86),
        text=colors.white,
        dest="nn_agent_sim",
    )

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(colors.white)
    c.drawString(44, 204, "How to Control")
    c.setFont("Helvetica", 10)
    help_lines = [
        "Prev / Next: step through frames manually",
        "Zoom +/-: switch between zoom levels",
        "Play Slow / Play Fast: jump into autoplay sequences",
        "Home / Stop: return to the menu or manual mode",
        "Neural Net Agent Simulation Page: view a trained tiny AI controller demo",
    ]
    y = 186
    for line in help_lines:
        c.drawString(52, y, f"- {line}")
        y -= 14

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(0.80, 0.88, 0.95))
    c.drawString(44, 56, "Created programmatically with Python + ReportLab (vector graphics + internal PDF links).")


def control_buttons(
    c: canvas.Canvas,
    seq: SeqConfig,
    frame_idx: int,
    zoom_idx: int,
    width: float,
) -> None:
    panel_y = 18
    y = panel_y + 12
    x = 300
    bw, bh = 78, 22
    gap = 8

    prev_dest = dest_name("manual", clamp_index(frame_idx - 1, FRAME_COUNT), zoom_idx)
    next_dest = dest_name("manual", clamp_index(frame_idx + 1, FRAME_COUNT), zoom_idx)
    stop_dest = dest_name("manual", frame_idx, zoom_idx)

    # Navigation buttons
    draw_rounded_button(
        c, x, y, bw, bh, "Prev",
        fill=colors.Color(0.10, 0.16, 0.24),
        stroke=colors.Color(0.28, 0.40, 0.56),
        text=colors.white,
        dest=prev_dest,
    )
    draw_rounded_button(
        c, x + (bw + gap), y, bw, bh, "Next",
        fill=colors.Color(0.10, 0.16, 0.24),
        stroke=colors.Color(0.28, 0.40, 0.56),
        text=colors.white,
        dest=next_dest,
    )

    home_x = width - 224
    draw_rounded_button(
        c, home_x, y, 64, bh, "Home",
        fill=colors.Color(0.12, 0.16, 0.21),
        stroke=colors.Color(0.35, 0.45, 0.58),
        text=colors.white,
        dest="home",
    )
    draw_rounded_button(
        c, home_x + 72, y, 72, bh, "Stop",
        fill=colors.Color(0.24, 0.10, 0.12),
        stroke=colors.Color(0.76, 0.34, 0.38),
        text=colors.white,
        dest=stop_dest,
    )

    # Zoom buttons (jump to equivalent frame in other zoom states)
    zoom_minus_dest = dest_name("manual", frame_idx, max(0, zoom_idx - 1))
    zoom_plus_dest = dest_name("manual", frame_idx, min(len(ZOOMS) - 1, zoom_idx + 1))
    draw_rounded_button(
        c, 40, y, 78, bh, "Zoom -",
        fill=colors.Color(0.08, 0.18, 0.20),
        stroke=colors.Color(0.20, 0.52, 0.60),
        text=colors.white,
        dest=zoom_minus_dest,
    )
    draw_rounded_button(
        c, 126, y, 78, bh, "Zoom +",
        fill=colors.Color(0.08, 0.18, 0.20),
        stroke=colors.Color(0.20, 0.52, 0.60),
        text=colors.white,
        dest=zoom_plus_dest,
    )

    # Play mode switching
    mode_y = y + 28
    draw_rounded_button(
        c, 40, mode_y, 104, bh, "Play Slow",
        fill=colors.Color(0.08, 0.22, 0.18),
        stroke=colors.Color(0.25, 0.72, 0.58),
        text=colors.white,
        dest=dest_name("slow", frame_idx, 0),
    )
    draw_rounded_button(
        c, 152, mode_y, 104, bh, "Play Fast",
        fill=colors.Color(0.24, 0.16, 0.08),
        stroke=colors.Color(0.93, 0.62, 0.27),
        text=colors.white,
        dest=dest_name("fast", frame_idx, 0),
    )
    draw_rounded_button(
        c, 264, mode_y, 104, bh, "Manual",
        fill=colors.Color(0.12, 0.22, 0.34),
        stroke=colors.Color(0.33, 0.57, 0.85),
        text=colors.white,
        dest=dest_name("manual", frame_idx, zoom_idx),
    )

    if seq.key != "manual":
        alt = "Fast" if seq.key == "slow" else "Slow"
        target = "fast" if seq.key == "slow" else "slow"
        draw_rounded_button(
            c, 376, mode_y, 108, bh, f"Switch {alt}",
            fill=colors.Color(0.13, 0.12, 0.24),
            stroke=colors.Color(0.48, 0.45, 0.82),
            text=colors.white,
            dest=dest_name(target, frame_idx, 0),
        )


def _color_signed_weight(w: float) -> colors.Color:
    mag = min(1.0, abs(w))
    if w >= 0:
        return colors.Color(0.18, 0.75 + 0.20 * mag, 0.95, alpha=0.45 + 0.45 * mag)
    return colors.Color(0.95, 0.35 + 0.20 * (1 - mag), 0.40, alpha=0.45 + 0.45 * mag)


def train_tiny_agent_model(seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)

    target = np.array([0.87, 0.79], dtype=np.float64)
    obstacle = np.array([0.53, 0.50], dtype=np.float64)
    obstacle_r = 0.14

    n = 640
    pos = rng.uniform(0.05, 0.95, size=(n, 2))

    d_goal = target - pos
    d_obs = pos - obstacle
    obs_dist = np.linalg.norm(d_obs, axis=1, keepdims=True) + 1e-6
    d_goal_norm = d_goal / (np.linalg.norm(d_goal, axis=1, keepdims=True) + 1e-6)

    repel_strength = np.clip((obstacle_r * 2.1 - obs_dist) / (obstacle_r * 2.1), 0.0, 1.0)
    repel = (d_obs / obs_dist) * repel_strength * 2.0

    tangent = np.stack([-d_obs[:, 1], d_obs[:, 0]], axis=1)
    tangent = tangent / (np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-6)
    tangent *= repel_strength * 0.6

    desired = d_goal_norm + repel + tangent
    desired = desired / (np.linalg.norm(desired, axis=1, keepdims=True) + 1e-6)

    x = np.hstack([target - pos, obstacle - pos]).astype(np.float64)
    y = desired.astype(np.float64)

    w1 = rng.normal(scale=0.45, size=(4, 8))
    b1 = np.zeros((1, 8), dtype=np.float64)
    w2 = rng.normal(scale=0.35, size=(8, 2))
    b2 = np.zeros((1, 2), dtype=np.float64)

    lr = 0.08
    losses: List[float] = []
    for epoch in range(900):
        z1 = x @ w1 + b1
        a1 = np.tanh(z1)
        y_hat = a1 @ w2 + b2
        err = y_hat - y
        loss = float(np.mean(err * err))
        if epoch % 15 == 0:
            losses.append(loss)

        dy = (2.0 / len(x)) * err
        dw2 = a1.T @ dy
        db2 = dy.sum(axis=0, keepdims=True)
        da1 = dy @ w2.T
        dz1 = da1 * (1.0 - a1 * a1)
        dw1 = x.T @ dz1
        db1 = dz1.sum(axis=0, keepdims=True)

        w2 -= lr * dw2
        b2 -= lr * db2
        w1 -= lr * dw1
        b1 -= lr * db1

        if epoch in (250, 500, 700):
            lr *= 0.65

    def predict(state: np.ndarray) -> np.ndarray:
        h = np.tanh(state @ w1 + b1)
        out = h @ w2 + b2
        return out

    # Simulate the trained agent in a simple 2D world.
    p = np.array([0.10, 0.14], dtype=np.float64)
    trajectory = [p.copy()]
    actions = []
    reached = False

    for _step in range(70):
        state = np.hstack([target - p, obstacle - p])[None, :]
        raw = predict(state)[0]
        mag = float(np.linalg.norm(raw))
        action = raw / (mag + 1e-6)
        actions.append(action.copy())

        q = p + action * 0.035

        vec = q - obstacle
        dist = float(np.linalg.norm(vec))
        min_dist = obstacle_r + 0.025
        if dist < min_dist:
            nvec = vec / (dist + 1e-6)
            tangent2 = np.array([-nvec[1], nvec[0]])
            if float(np.dot(tangent2, target - q)) < 0:
                tangent2 = -tangent2
            q = obstacle + nvec * min_dist + tangent2 * 0.010

        q = np.clip(q, 0.03, 0.97)
        p = q
        trajectory.append(p.copy())

        if float(np.linalg.norm(target - p)) < 0.05:
            reached = True
            break

    final_state = np.hstack([target - p, obstacle - p])[None, :]
    final_pred = predict(final_state)[0]
    final_loss = float(losses[-1]) if losses else 0.0

    return {
        "target": target,
        "obstacle": obstacle,
        "obstacle_r": obstacle_r,
        "trajectory": np.array(trajectory),
        "actions": np.array(actions) if actions else np.zeros((0, 2)),
        "reached": reached,
        "steps": len(trajectory) - 1,
        "w1": w1,
        "b1": b1,
        "w2": w2,
        "b2": b2,
        "losses": losses,
        "final_loss": final_loss,
        "final_pred": final_pred,
    }


def _map_world_to_plot(wx: float, wy: float, x: float, y: float, w: float, h: float) -> Tuple[float, float]:
    return (x + wx * w, y + wy * h)


def _draw_panel_card(c: canvas.Canvas, x: float, y: float, w: float, h: float, title: str) -> None:
    c.setFillColor(colors.Color(0.03, 0.06, 0.11))
    c.setStrokeColor(colors.Color(0.19, 0.33, 0.50))
    c.roundRect(x, y, w, h, 12, stroke=1, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x + 14, y + h - 20, title)


def draw_nn_agent_sim_page(c: canvas.Canvas, width: float, height: float) -> None:
    data = train_tiny_agent_model()

    draw_background(c, width, height)
    c.bookmarkPage("nn_agent_sim")

    c.setFillColor(colors.Color(0.02, 0.04, 0.08))
    c.setStrokeColor(colors.Color(0.18, 0.32, 0.50))
    c.roundRect(18, 18, width - 36, height - 36, 14, stroke=1, fill=1)

    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(34, height - 46, "Basic Trained Neural Network Agent Simulation")
    c.setFont("Helvetica", 10)
    c.setFillColor(colors.Color(0.82, 0.89, 0.96))
    c.drawString(
        34,
        height - 62,
        "Tiny MLP (4 -> 8 -> 2) trained on synthetic steering targets, then simulated in a 2D obstacle-avoidance world.",
    )

    env_x, env_y, env_w, env_h = 30, 112, 435, 440
    net_x, net_y, net_w, net_h = 478, 332, 284, 220
    loss_x, loss_y, loss_w, loss_h = 478, 112, 284, 206
    strip_x, strip_y, strip_w, strip_h = 30, 30, 732, 68

    _draw_panel_card(c, env_x, env_y, env_w, env_h, "Agent World / Rollout")
    _draw_panel_card(c, net_x, net_y, net_w, net_h, "Learned Network Weights")
    _draw_panel_card(c, loss_x, loss_y, loss_w, loss_h, "Training Loss")
    _draw_panel_card(c, strip_x, strip_y, strip_w, strip_h, "Controls / Notes")

    # Environment plot
    plot_x, plot_y = env_x + 18, env_y + 18
    plot_w, plot_h = env_w - 36, env_h - 54
    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.14, 0.26, 0.39))
    c.roundRect(plot_x, plot_y, plot_w, plot_h, 8, stroke=1, fill=1)

    c.setStrokeColor(colors.Color(0.08, 0.24, 0.37))
    c.setLineWidth(0.6)
    for i in range(1, 10):
        gx = plot_x + plot_w * i / 10
        gy = plot_y + plot_h * i / 10
        c.line(gx, plot_y, gx, plot_y + plot_h)
        c.line(plot_x, gy, plot_x + plot_w, gy)

    # Plot world bounds labels
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.Color(0.70, 0.82, 0.92))
    c.drawString(plot_x + 4, plot_y + plot_h + 3, "y")
    c.drawString(plot_x + plot_w + 6, plot_y + 2, "x")

    obstacle = data["obstacle"]
    obstacle_r = data["obstacle_r"]
    target = data["target"]
    traj = data["trajectory"]

    # Obstacle
    ox, oy = _map_world_to_plot(float(obstacle[0]), float(obstacle[1]), plot_x, plot_y, plot_w, plot_h)
    orad = obstacle_r * min(plot_w, plot_h)
    c.setFillColor(colors.Color(0.80, 0.28, 0.20, alpha=0.55))
    c.setStrokeColor(colors.Color(0.95, 0.52, 0.33))
    c.setLineWidth(1.4)
    c.circle(ox, oy, orad, stroke=1, fill=1)
    c.setStrokeColor(colors.Color(0.95, 0.62, 0.42))
    c.setDash(3, 2)
    c.circle(ox, oy, orad * 1.35, stroke=1, fill=0)
    c.setDash()

    # Target
    tx, ty = _map_world_to_plot(float(target[0]), float(target[1]), plot_x, plot_y, plot_w, plot_h)
    c.setStrokeColor(colors.Color(0.30, 0.95, 0.58))
    c.setLineWidth(2.0)
    c.circle(tx, ty, 10, stroke=1, fill=0)
    c.circle(tx, ty, 4, stroke=1, fill=0)
    c.line(tx - 14, ty, tx + 14, ty)
    c.line(tx, ty - 14, tx, ty + 14)

    # Trajectory
    c.setLineWidth(2.2)
    c.setStrokeColor(colors.Color(0.25, 0.86, 1.00))
    path = c.beginPath()
    for i, p in enumerate(traj):
        px, py = _map_world_to_plot(float(p[0]), float(p[1]), plot_x, plot_y, plot_w, plot_h)
        if i == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    c.drawPath(path, stroke=1, fill=0)

    # Snapshot points
    for i, p in enumerate(traj):
        px, py = _map_world_to_plot(float(p[0]), float(p[1]), plot_x, plot_y, plot_w, plot_h)
        t = i / max(1, len(traj) - 1)
        c.setFillColor(color_blend((40, 200, 255), (40, 255, 120), t))
        r = 2.6 if i < len(traj) - 1 else 5.0
        c.circle(px, py, r, stroke=0, fill=1)
        if i % 6 == 0 and i < len(traj) - 1:
            c.setFont("Helvetica", 7)
            c.setFillColor(colors.Color(0.85, 0.93, 0.99))
            c.drawString(px + 4, py + 4, str(i))

    # Start marker
    sx, sy = _map_world_to_plot(float(traj[0][0]), float(traj[0][1]), plot_x, plot_y, plot_w, plot_h)
    c.setStrokeColor(colors.Color(0.95, 0.95, 1.0))
    c.setLineWidth(1.2)
    c.rect(sx - 4, sy - 4, 8, 8, stroke=1, fill=0)

    c.setFillColor(colors.Color(0.82, 0.90, 0.96))
    c.setFont("Helvetica", 9)
    c.drawString(plot_x + 10, plot_y + plot_h - 16, "Start (square), trajectory (cyan -> green), obstacle (orange), target (green)")
    status = "Reached target" if data["reached"] else "Stopped before target"
    c.drawString(plot_x + 10, plot_y + 10, f"Status: {status} in {data['steps']} steps")

    # Network diagram
    inner_x, inner_y = net_x + 14, net_y + 16
    inner_w, inner_h = net_w - 28, net_h - 34
    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.14, 0.26, 0.39))
    c.roundRect(inner_x, inner_y, inner_w, inner_h, 8, stroke=1, fill=1)

    w1 = data["w1"]
    w2 = data["w2"]
    b1 = data["b1"][0]
    b2 = data["b2"][0]

    input_labels = ["dx", "dy", "ox", "oy"]
    output_labels = ["vx", "vy"]
    in_x = inner_x + 28
    hid_x = inner_x + inner_w * 0.50
    out_x = inner_x + inner_w - 34
    top_pad = inner_y + inner_h - 26
    bot_pad = inner_y + 20

    def lane_positions(count: int) -> List[float]:
        if count == 1:
            return [(top_pad + bot_pad) / 2]
        return [top_pad - i * (top_pad - bot_pad) / (count - 1) for i in range(count)]

    in_ys = lane_positions(4)
    hid_ys = lane_positions(8)
    out_ys = lane_positions(2)

    # Draw weighted edges
    max_w1 = float(np.max(np.abs(w1))) + 1e-6
    max_w2 = float(np.max(np.abs(w2))) + 1e-6
    for i, y0 in enumerate(in_ys):
        for j, y1 in enumerate(hid_ys):
            val = float(w1[i, j] / max_w1)
            c.setStrokeColor(_color_signed_weight(val))
            c.setLineWidth(0.3 + 1.1 * min(1.0, abs(val)))
            c.line(in_x, y0, hid_x, y1)
    for j, y0 in enumerate(hid_ys):
        for k, y1 in enumerate(out_ys):
            val = float(w2[j, k] / max_w2)
            c.setStrokeColor(_color_signed_weight(val))
            c.setLineWidth(0.4 + 1.2 * min(1.0, abs(val)))
            c.line(hid_x, y0, out_x, y1)

    c.setLineWidth(1.0)
    # Nodes
    for i, y0 in enumerate(in_ys):
        c.setFillColor(colors.Color(0.15, 0.40, 0.60))
        c.setStrokeColor(colors.Color(0.42, 0.66, 0.86))
        c.circle(in_x, y0, 8, stroke=1, fill=1)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.90, 0.96, 1.0))
        c.drawRightString(in_x - 12, y0 - 2, input_labels[i])

    for j, y0 in enumerate(hid_ys):
        mag = min(1.0, abs(float(b1[j])) / 0.8)
        c.setFillColor(colors.Color(0.18, 0.24 + 0.35 * mag, 0.45 + 0.25 * mag))
        c.setStrokeColor(colors.Color(0.52, 0.73, 0.92))
        c.circle(hid_x, y0, 6, stroke=1, fill=1)

    for k, y0 in enumerate(out_ys):
        c.setFillColor(colors.Color(0.12, 0.45, 0.26))
        c.setStrokeColor(colors.Color(0.40, 0.92, 0.60))
        c.circle(out_x, y0, 8, stroke=1, fill=1)
        c.setFont("Helvetica", 8)
        c.setFillColor(colors.Color(0.90, 0.98, 0.94))
        c.drawString(out_x + 12, y0 - 2, output_labels[k])

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.Color(0.78, 0.87, 0.94))
    c.drawString(inner_x + 8, inner_y + 4, "Blue = positive weight, red = negative weight, thickness = magnitude")

    # Loss plot
    li_x, li_y = loss_x + 14, loss_y + 16
    li_w, li_h = loss_w - 28, loss_h - 34
    c.setFillColor(colors.Color(0.01, 0.03, 0.07))
    c.setStrokeColor(colors.Color(0.14, 0.26, 0.39))
    c.roundRect(li_x, li_y, li_w, li_h, 8, stroke=1, fill=1)

    c.setStrokeColor(colors.Color(0.08, 0.24, 0.37))
    c.setLineWidth(0.5)
    for i in range(1, 5):
        gy = li_y + li_h * i / 5
        c.line(li_x + 26, gy, li_x + li_w - 8, gy)
    for i in range(1, 6):
        gx = li_x + 26 + (li_w - 34) * i / 6
        c.line(gx, li_y + 12, gx, li_y + li_h - 10)

    c.setStrokeColor(colors.Color(0.50, 0.70, 0.90))
    c.setLineWidth(1.0)
    c.line(li_x + 26, li_y + 12, li_x + 26, li_y + li_h - 10)
    c.line(li_x + 26, li_y + 12, li_x + li_w - 8, li_y + 12)

    losses = data["losses"]
    if losses:
        max_loss = max(losses)
        min_loss = min(losses)
        span = max(max_loss - min_loss, 1e-6)
        path = c.beginPath()
        for i, loss in enumerate(losses):
            px = li_x + 26 + (li_w - 34) * (i / max(1, len(losses) - 1))
            py = li_y + 12 + (li_h - 24) * ((loss - min_loss) / span)
            if i == 0:
                path.moveTo(px, py)
            else:
                path.lineTo(px, py)
        c.setStrokeColor(colors.Color(0.22, 0.90, 0.96))
        c.setLineWidth(2.0)
        c.drawPath(path, stroke=1, fill=0)

    c.setFont("Helvetica", 8)
    c.setFillColor(colors.Color(0.80, 0.88, 0.95))
    c.drawString(li_x + 6, li_y + li_h - 8, "loss")
    c.drawString(li_x + li_w - 30, li_y + 2, "epoch")
    c.drawString(li_x + 30, li_y + li_h - 8, f"Final MSE: {data['final_loss']:.5f}")
    c.drawString(li_x + 30, li_y + li_h - 20, f"Output at final state: [{data['final_pred'][0]:+.2f}, {data['final_pred'][1]:+.2f}]")

    # Bottom strip controls / notes
    draw_rounded_button(
        c, strip_x + 16, strip_y + 20, 110, 26, "Back To Home",
        fill=colors.Color(0.12, 0.16, 0.21),
        stroke=colors.Color(0.35, 0.45, 0.58),
        text=colors.white,
        dest="home",
    )
    draw_rounded_button(
        c, strip_x + 136, strip_y + 20, 130, 26, "Open 3D Cube",
        fill=colors.Color(0.12, 0.22, 0.34),
        stroke=colors.Color(0.33, 0.57, 0.85),
        text=colors.white,
        dest=dest_name("manual", 0, 0),
    )
    draw_rounded_button(
        c, strip_x + 276, strip_y + 20, 118, 26, "Play Cube Slow",
        fill=colors.Color(0.08, 0.22, 0.18),
        stroke=colors.Color(0.25, 0.72, 0.58),
        text=colors.white,
        dest=dest_name("slow", 0, 0),
    )

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.Color(0.86, 0.92, 0.97))
    notes_x = strip_x + 410
    c.drawString(notes_x, strip_y + 42, "This page is a rendered simulation snapshot + learned weights (PDF-safe, no live code execution).")
    c.drawString(notes_x, strip_y + 28, "Agent state inputs: dx, dy to target and ox, oy to obstacle center; outputs: vx, vy steering vector.")
    c.drawString(notes_x, strip_y + 14, "Training data was synthetic (teacher controller) to keep the model tiny and deterministic.")


def generate_pdf(path: str) -> None:
    ensure_dirs()

    width, height = landscape(letter)
    c = canvas.Canvas(path, pagesize=(width, height))
    c.setTitle("Interactive 3D Cube + Neural Agent Simulation PDF")
    c.setAuthor("Codex")
    c.setSubject("3D animation with PDF controls and a neural network agent simulation page")

    # Home page
    draw_home_page(c, width, height)
    c.showPage()

    # Animation pages
    for seq in SEQS:
        for zoom_idx, _zoom in enumerate(ZOOMS):
            # Keep autoplay sequences at base zoom to avoid too many pages.
            if seq.autoplay and zoom_idx != 0:
                continue

            for frame_idx in range(FRAME_COUNT):
                c.bookmarkPage(dest_name(seq.key, frame_idx, zoom_idx))
                draw_cube_scene(c, width, height, frame_idx=frame_idx, zoom_idx=zoom_idx, seq=seq)
                control_buttons(c, seq, frame_idx, zoom_idx, width)

                if seq.autoplay:
                    c.setPageDuration(seq.page_duration)
                    c.setPageTransition("Dissolve", duration=1)
                c.showPage()

    # Reset autoplay/transition so the neural agent page stays static.
    c.setPageDuration(None)
    c.setPageTransition()
    draw_nn_agent_sim_page(c, width, height)
    c.showPage()

    c.save()


def main() -> None:
    out_path = os.path.join("output", "pdf", "interactive_3d_cube_controls.pdf")
    generate_pdf(out_path)
    print(f"Created: {out_path}")


if __name__ == "__main__":
    main()
