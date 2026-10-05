"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import styles from "./pull-to-refresh.module.css";

const TRIGGER_DISTANCE = 72;
const MAX_DISTANCE = 104;

export function PullToRefresh({ onRefresh }: { onRefresh: () => Promise<unknown> | void }) {
  const startY = useRef<number | null>(null);
  const pulling = useRef(false);
  const distanceRef = useRef(0);
  const frameRef = useRef<number | null>(null);
  const [distance, setDistanceState] = useState(0);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const atTop = () => window.scrollY <= 0 && document.documentElement.scrollTop <= 0;
    const commitDistance = (value: number) => {
      distanceRef.current = value;
      if (frameRef.current !== null) return;
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null;
        setDistanceState(distanceRef.current);
      });
    };
    const reset = () => {
      startY.current = null;
      pulling.current = false;
      distanceRef.current = 0;
      if (frameRef.current !== null) {
        window.cancelAnimationFrame(frameRef.current);
        frameRef.current = null;
      }
      setDistanceState(0);
    };
    const touchStart = (event: TouchEvent) => {
      if (refreshing || event.touches.length !== 1 || !atTop()) return;
      startY.current = event.touches[0].clientY;
      pulling.current = true;
    };
    const touchMove = (event: TouchEvent) => {
      if (!pulling.current || startY.current === null || event.touches.length !== 1) return;
      const delta = event.touches[0].clientY - startY.current;
      if (delta <= 0 || !atTop()) {
        reset();
        return;
      }
      commitDistance(Math.min(MAX_DISTANCE, delta * 0.55));
    };
    const touchEnd = async () => {
      if (!pulling.current) return;
      const shouldRefresh = distanceRef.current >= TRIGGER_DISTANCE;
      reset();
      if (!shouldRefresh) return;
      setRefreshing(true);
      try {
        await onRefresh();
      } finally {
        setRefreshing(false);
      }
    };

    // Keep normal vertical swipes on WebKit's native async scrolling path.
    // A global non-passive touchmove listener makes iOS wait for JavaScript
    // on every frame, even when preventDefault() is not called.
    window.addEventListener("touchstart", touchStart, { passive: true });
    window.addEventListener("touchmove", touchMove, { passive: true });
    window.addEventListener("touchend", touchEnd, { passive: true });
    window.addEventListener("touchcancel", reset, { passive: true });

    return () => {
      if (frameRef.current !== null) window.cancelAnimationFrame(frameRef.current);
      window.removeEventListener("touchstart", touchStart);
      window.removeEventListener("touchmove", touchMove);
      window.removeEventListener("touchend", touchEnd);
      window.removeEventListener("touchcancel", reset);
    };
  }, [onRefresh, refreshing]);

  const visible = refreshing || distance > 0;
  const ready = distance >= TRIGGER_DISTANCE;

  return (
    <div
      className={`${styles.indicator} ${visible ? styles.visible : ""} ${refreshing ? styles.refreshing : ""}`}
      style={{ "--pull-distance": `${distance}px` } as CSSProperties}
      role="status"
      aria-live="polite"
      aria-label={refreshing ? "Gegevens worden vernieuwd" : ready ? "Laat los om te vernieuwen" : "Trek verder om te vernieuwen"}
    >
      <span aria-hidden="true">↻</span>
    </div>
  );
}
