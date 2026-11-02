// Canvas region crops, shared by the wizard and the Quick-mode zoom view.
//
// Takes the loaded image element, the SAM box (in its own w/h frame), and
// the image's natural size; resolves a JPEG File of the padded region.
// Rejections are message descriptors ({ key }), rendered via msgText().
import { paddedCropRect, scaleBox } from './boxes.js'

export function cropToFile(img, box, naturalSize, index = 0) {
  return new Promise((resolve, reject) => {
    // Failures reject with message descriptors so the caller can store and
    // speak them in the current locale.
    const fail = (message) => reject(message)
    const nw = naturalSize.w
    const nh = naturalSize.h
    if (!img || !nw || !nh) {
      fail({ key: 'cropLoading' })
      return
    }
    const scaled = scaleBox(box, nw, nh)
    if (!scaled || scaled.x2 <= scaled.x1 || scaled.y2 <= scaled.y1) {
      fail({ key: 'cropInvalid' })
      return
    }
    const rect = paddedCropRect(scaled, nw, nh)
    if (!rect) {
      fail({ key: 'cropEmpty' })
      return
    }
    const { cx1, cy1, cx2, cy2 } = rect
    const canvas = document.createElement('canvas')
    canvas.width = cx2 - cx1
    canvas.height = cy2 - cy1
    const ctx = canvas.getContext('2d')
    if (!ctx) {
      fail({ key: 'cropFail' })
      return
    }
    ctx.drawImage(img, cx1, cy1, cx2 - cx1, cy2 - cy1, 0, 0, canvas.width, canvas.height)
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          fail({ key: 'cropFail' })
          return
        }
        resolve(
          new File([blob], `region-${index + 1}.jpg`, { type: 'image/jpeg' }),
        )
      },
      'image/jpeg',
      0.9,
    )
  })
}
