"use client";

import { useEffect } from "react";

function isChartTarget(target: EventTarget | null) {
  return target instanceof Element && Boolean(target.closest(".chart-canvas"));
}

export function ZoomGuard() {
  useEffect(() => {
    const preventGesture = (event: Event) => {
      if (!isChartTarget(event.target)) event.preventDefault();
    };
    const preventMultiTouch = (event: TouchEvent) => {
      if (event.touches.length > 1 && !isChartTarget(event.target)) event.preventDefault();
    };
    const preventDoubleClick = (event: MouseEvent) => {
      if (!isChartTarget(event.target)) event.preventDefault();
    };

    document.addEventListener("gesturestart", preventGesture, { passive: false });
    document.addEventListener("gesturechange", preventGesture, { passive: false });
    document.addEventListener("touchmove", preventMultiTouch, { passive: false });
    document.addEventListener("dblclick", preventDoubleClick, { passive: false });

    return () => {
      document.removeEventListener("gesturestart", preventGesture);
      document.removeEventListener("gesturechange", preventGesture);
      document.removeEventListener("touchmove", preventMultiTouch);
      document.removeEventListener("dblclick", preventDoubleClick);
    };
  }, []);

  return null;
}
