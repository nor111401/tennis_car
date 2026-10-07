export function getContainedMediaRect(
  containerWidth,
  containerHeight,
  mediaWidth,
  mediaHeight,
) {
  if (![containerWidth, containerHeight, mediaWidth, mediaHeight].every(
    (value) => Number.isFinite(value) && value > 0,
  )) {
    return { left: 0, top: 0, width: 0, height: 0 };
  }

  const containerAspect = containerWidth / containerHeight;
  const mediaAspect = mediaWidth / mediaHeight;
  if (mediaAspect > containerAspect) {
    const width = containerWidth;
    const height = width / mediaAspect;
    return { left: 0, top: (containerHeight - height) / 2, width, height };
  }

  const height = containerHeight;
  const width = height * mediaAspect;
  return { left: (containerWidth - width) / 2, top: 0, width, height };
}

export function mapNormalizedBoxToPixels(mediaRect, box) {
  return {
    left: mediaRect.left + box.x * mediaRect.width,
    top: mediaRect.top + box.y * mediaRect.height,
    width: box.width * mediaRect.width,
    height: box.height * mediaRect.height,
  };
}
