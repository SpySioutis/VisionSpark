// Pure box geometry for the segmentation overlay and region crops.
//
// SAM boxes live in their own w/h frame and must be scaled into
// natural-image pixels before display or cropping.

/**
 * Map a SAM box from its own w/h frame into natural-image pixels so the
 * overlay (viewBox = natural size) and the crop agree. Returns null when
 * the box cannot be scaled.
 */
export function scaleBox(box, nw, nh) {
  if (!box) {
    return null
  }
  const vals = [box.x1, box.y1, box.x2, box.y2, box.w, box.h, nw, nh]
  if (!vals.every((n) => Number.isFinite(n)) || box.w <= 0 || box.h <= 0) {
    return null
  }
  return {
    x1: (box.x1 * nw) / box.w,
    y1: (box.y1 * nh) / box.h,
    x2: (box.x2 * nw) / box.w,
    y2: (box.y2 * nh) / box.h,
  }
}

/**
 * Expand a scaled box by 5% on each side and clamp it to the image bounds.
 * Returns { cx1, cy1, cx2, cy2 } in natural-image pixels, or null when
 * nothing remains after clipping.
 */
export function paddedCropRect(scaled, nw, nh) {
  const padX = (scaled.x2 - scaled.x1) * 0.05
  const padY = (scaled.y2 - scaled.y1) * 0.05
  const cx1 = Math.max(0, Math.round(scaled.x1 - padX))
  const cy1 = Math.max(0, Math.round(scaled.y1 - padY))
  const cx2 = Math.min(nw, Math.round(scaled.x2 + padX))
  const cy2 = Math.min(nh, Math.round(scaled.y2 + padY))
  if (cx2 <= cx1 || cy2 <= cy1) {
    return null
  }
  return { cx1, cy1, cx2, cy2 }
}

/**
 * Describe a box in words for blind users: { position, size }.
 *
 * Position is the box center in a 3x3 grid of the box's own w/h frame;
 * size is the area fraction (>= 0.25 large, >= 0.05 medium, else small).
 * The ids map to locale keys (boxPosTop, boxSizeLarge, ...) in App.vue.
 */
export function describeBox(box) {
  if (!box || !(box.w > 0) || !(box.h > 0)) {
    return { position: 'center', size: 'small' }
  }
  const cx = ((box.x1 + box.x2) / 2 / box.w)
  const cy = ((box.y1 + box.y2) / 2 / box.h)
  const col = cx < 1 / 3 ? 0 : cx < 2 / 3 ? 1 : 2
  const row = cy < 1 / 3 ? 0 : cy < 2 / 3 ? 1 : 2
  const positions = [
    ['topLeft', 'top', 'topRight'],
    ['left', 'center', 'right'],
    ['bottomLeft', 'bottom', 'bottomRight'],
  ]
  const area = ((box.x2 - box.x1) * (box.y2 - box.y1)) / (box.w * box.h)
  const size = area >= 0.25 ? 'large' : area >= 0.05 ? 'medium' : 'small'
  return { position: positions[row][col], size }
}

// Live-guidance geometry: fractions of the frame.
export const LIVE_GUIDE_CENTER_TOLERANCE = 0.15
export const LIVE_GUIDE_MIN_AREA = 0.15
export const LIVE_GUIDE_MAX_AREA = 0.85

/**
 * The best box: highest confidence (missing last), then largest area.
 * Degenerate boxes are skipped. Returns null when none is usable.
 */
export function bestBox(boxes) {
  const usable = (boxes ?? []).filter(
    (box) => box && box.x2 > box.x1 && box.y2 > box.y1 && box.w > 0 && box.h > 0,
  )
  usable.sort((a, b) => {
    const ca = a.c ?? -1
    const cb = b.c ?? -1
    if (ca !== cb) {
      return cb - ca
    }
    return (b.x2 - b.x1) * (b.y2 - b.y1) - (a.x2 - a.x1) * (a.y2 - a.y1)
  })
  return usable[0] ?? null
}

/**
 * Live guidance for the best SAM box, most urgent first: too close beats
 * off-center (centering a full frame is pointless), off-center beats too
 * small (keep it in frame while approaching). Returns 'moveLeft' |
 * 'moveRight' | 'moveUp' | 'moveDown' | 'moveCloser' | 'moveBack' |
 * 'centered'. Stillness is checked separately by the caller.
 */
export function guideForBox(box) {
  const { x1, y1, x2, y2, w, h } = box
  const touchesLeft = x1 <= 0
  const touchesRight = x2 >= w - 1
  const touchesTop = y1 <= 0
  const touchesBottom = y2 >= h - 1
  const area = ((x2 - x1) * (y2 - y1)) / (w * h)
  if (
    (touchesLeft && touchesRight) ||
    (touchesTop && touchesBottom) ||
    area > LIVE_GUIDE_MAX_AREA
  ) {
    return 'moveBack'
  }
  const dx = ((x1 + x2) / 2 / w) - 0.5
  const dy = ((y1 + y2) / 2 / h) - 0.5
  if (
    Math.abs(dx) > LIVE_GUIDE_CENTER_TOLERANCE ||
    Math.abs(dy) > LIVE_GUIDE_CENTER_TOLERANCE
  ) {
    if (Math.abs(dx) >= Math.abs(dy)) {
      return dx < 0 ? 'moveLeft' : 'moveRight'
    }
    return dy < 0 ? 'moveUp' : 'moveDown'
  }
  if (area < LIVE_GUIDE_MIN_AREA) {
    return 'moveCloser'
  }
  return 'centered'
}
