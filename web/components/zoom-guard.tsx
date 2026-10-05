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
    const preventDoubleClick = (event: MouseEvent) => {
      if (!isChartTarget(event.target)) event.preventDefault();
    };

    // Do not register a document-level non-passive touchmove listener here.
    // The root viewport already disables page zoom and CSS uses touch-action,
    // while a blocking touchmove listener forces iOS Safari off native async
    // scrolling and makes every vertical swipe wait for JavaScript.
    document.addEventListener("gesturestart", preventGesture, { passive: false });
    document.addEventListener("gesturechange", preventGesture, { passive: false });
    document.addEventListener("dblclick", preventDoubleClick, { passive: false });

    return () => {
      document.removeEventListener("gesturestart", preventGesture);
      document.removeEventListener("gesturechange", preventGesture);
      document.removeEventListener("dblclick", preventDoubleClick);
    };
  }, []);

  return null;
}
