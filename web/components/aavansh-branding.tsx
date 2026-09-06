"use client";

import { useEffect } from "react";

const BRAND_NAME = "Aavansh Trading";
const BRAND_NAME_UPPER = "AAVANSH TRADING";
const LOGO_PATH = "/aavansh-logo.png";

function replaceBrandText(value: string) {
  return value
    .replace(/TRADEMENTOR/g, BRAND_NAME_UPPER)
    .replace(/TradeMentor/g, BRAND_NAME);
}

function brandElement(root: ParentNode) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  let current = walker.nextNode();
  while (current) {
    const parent = current.parentElement;
    if (parent && !["SCRIPT", "STYLE", "TEMPLATE"].includes(parent.tagName)) nodes.push(current as Text);
    current = walker.nextNode();
  }
  for (const node of nodes) {
    const next = replaceBrandText(node.nodeValue || "");
    if (next !== node.nodeValue) node.nodeValue = next;
  }

  for (const element of root.querySelectorAll<HTMLElement>("[aria-label], [title], img[alt]")) {
    for (const attr of ["aria-label", "title", "alt"] as const) {
      const value = element.getAttribute(attr);
      if (value) element.setAttribute(attr, replaceBrandText(value));
    }
  }
  for (const image of root.querySelectorAll<HTMLImageElement>('img[src*="tradementor-logo.png"]')) {
    image.src = LOGO_PATH;
    image.alt = "Aavansh Trading – A New Beginning";
  }
}

export function AavanshBranding() {
  useEffect(() => {
    document.documentElement.classList.add("aavansh-variant");
    document.title = "Aavansh Trading – A New Beginning";
    brandElement(document.body);
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        for (const node of record.addedNodes) {
          if (node instanceof HTMLElement) brandElement(node);
          else if (node.nodeType === Node.TEXT_NODE && node.parentElement) {
            const next = replaceBrandText(node.nodeValue || "");
            if (next !== node.nodeValue) node.nodeValue = next;
          }
        }
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => {
      observer.disconnect();
      document.documentElement.classList.remove("aavansh-variant");
    };
  }, []);
  return null;
}
