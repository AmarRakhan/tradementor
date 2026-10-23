"use client";

import { useEffect } from "react";

// iOS Safari / home-screen PWA: after the on-screen keyboard (or the <select>
// picker) closes, WebKit sometimes leaves position:fixed elements anchored to
// the shifted layout viewport. The mobile bottom navigation then floats in the
// middle of the page until the next full relayout. This guard:
//  1. hides the bottom navigation while an editable field is focused on a
//     touch device (it can never float above/behind the keyboard), and
//  2. re-anchors fixed elements as soon as the keyboard closes, the visual
//     viewport returns to full height, or the app comes back to the foreground.
// Display only: no data, settings or trading behaviour is touched.

const KEYBOARD_ATTR = "data-soft-keyboard";
const REANCHOR_ATTR = "data-nav-reanchor";
const NON_TEXT_INPUTS = new Set(["checkbox", "radio", "button", "submit", "reset", "range", "color", "file", "image", "hidden"]);

export function isSoftKeyboardTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target instanceof HTMLInputElement) return !NON_TEXT_INPUTS.has((target.type || "text").toLowerCase()) && !target.readOnly && !target.disabled;
  if (target instanceof HTMLTextAreaElement) return !target.readOnly && !target.disabled;
  if (target instanceof HTMLSelectElement) return !target.disabled;
  return target.isContentEditable;
}

export function BottomNavViewportGuard() {
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia?.("(pointer: coarse)").matches) return;
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let closeTimer: number | null = null;
    let frame: number | null = null;
    let fullHeight = viewport?.height ?? window.innerHeight;
    // Only re-anchor on a viewport resize that follows a keyboard close, never
    // on Safari's toolbar resize during normal scrolling (would stop momentum).
    let awaitingRestore = false;

    const reanchor = () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      root.setAttribute(REANCHOR_ATTR, "true");
      frame = window.requestAnimationFrame(() => {
        // Re-setting the current scroll position makes WebKit recompute the
        // layout viewport, which snaps fixed elements back to the bottom.
        window.scrollTo(window.scrollX, window.scrollY);
        frame = window.requestAnimationFrame(() => {
          frame = null;
          root.removeAttribute(REANCHOR_ATTR);
        });
      });
    };

    const setKeyboardOpen = (open: boolean) => {
      const wasOpen = root.getAttribute(KEYBOARD_ATTR) === "open";
      if (open) root.setAttribute(KEYBOARD_ATTR, "open");
      else root.removeAttribute(KEYBOARD_ATTR);
      if (wasOpen && !open) { awaitingRestore = true; reanchor(); }
    };

    const focusIn = (event: FocusEvent) => {
      if (closeTimer !== null) { window.clearTimeout(closeTimer); closeTimer = null; }
      if (isSoftKeyboardTarget(event.target)) setKeyboardOpen(true);
    };
    const focusOut = () => {
      if (closeTimer !== null) window.clearTimeout(closeTimer);
      // Moving focus from one field to the next fires focusout then focusin;
      // wait briefly so the navigation does not flicker between fields.
      closeTimer = window.setTimeout(() => {
        closeTimer = null;
        if (!isSoftKeyboardTarget(document.activeElement)) setKeyboardOpen(false);
      }, 120);
    };

    const viewportResize = () => {
      const height = viewport?.height ?? window.innerHeight;
      if (root.getAttribute(KEYBOARD_ATTR) !== "open") {
        if (awaitingRestore && height >= fullHeight - 80) { awaitingRestore = false; reanchor(); }
        if (!awaitingRestore) fullHeight = Math.max(fullHeight, height);
      } else if (height >= fullHeight - 80 && !isSoftKeyboardTarget(document.activeElement)) {
        setKeyboardOpen(false);
      }
    };
    const orientationChange = () => {
      window.setTimeout(() => { fullHeight = viewport?.height ?? window.innerHeight; reanchor(); }, 350);
    };
    const visibilityChange = () => { if (document.visibilityState === "visible") reanchor(); };

    document.addEventListener("focusin", focusIn);
    document.addEventListener("focusout", focusOut);
    viewport?.addEventListener("resize", viewportResize, { passive: true });
    window.addEventListener("orientationchange", orientationChange, { passive: true });
    window.addEventListener("pageshow", reanchor, { passive: true });
    document.addEventListener("visibilitychange", visibilityChange);

    return () => {
      if (closeTimer !== null) window.clearTimeout(closeTimer);
      if (frame !== null) window.cancelAnimationFrame(frame);
      document.removeEventListener("focusin", focusIn);
      document.removeEventListener("focusout", focusOut);
      viewport?.removeEventListener("resize", viewportResize);
      window.removeEventListener("orientationchange", orientationChange);
      window.removeEventListener("pageshow", reanchor);
      document.removeEventListener("visibilitychange", visibilityChange);
      root.removeAttribute(KEYBOARD_ATTR);
      root.removeAttribute(REANCHOR_ATTR);
    };
  }, []);

  return null;
}
