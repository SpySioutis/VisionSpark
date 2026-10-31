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
