import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { ErrorBoundary } from "./ErrorBoundary";
import "./index.css";

function renderBootError(message: string): void {
  const pre = document.createElement("pre");
  pre.style.whiteSpace = "pre-wrap";
  pre.style.margin = "16px";
  pre.style.padding = "12px";
  pre.style.border = "1px solid #fecaca";
  pre.style.borderRadius = "8px";
  pre.style.background = "#fff1f2";
  pre.style.color = "#881337";
  pre.textContent = `Rigovo desktop failed to boot:\n${message}`;
  document.body.replaceChildren();
  document.body.appendChild(pre);
}

window.addEventListener("unhandledrejection", (event) => {
  // eslint-disable-next-line no-console
  console.error("Unhandled promise rejection in desktop UI", event.reason);
  renderBootError(String(event.reason ?? "Unhandled promise rejection"));
});

window.addEventListener("error", (event) => {
  // eslint-disable-next-line no-console
  console.error("Unhandled UI error", event.error || event.message);
  renderBootError(String(event.error?.message ?? event.message ?? "Unhandled UI error"));
});

const rootEl = document.getElementById("root");
if (!rootEl) {
  renderBootError("Missing #root mount element in index.html");
} else {
  try {
    ReactDOM.createRoot(rootEl).render(
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    );
  } catch (err) {
    renderBootError(err instanceof Error ? err.message : String(err));
  }
}
