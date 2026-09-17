"use client";
import Link from "next/link";
import { useSyncExternalStore, type ReactNode } from "react";
import { replayEnabled, subscribeReplayMode, serverReplayMode } from "@/lib/replay-runtime.mjs";

const navigation = [
  { href: "/", label: "Overview" },
  { href: "/customers", label: "Demo customers" },
  { href: "/quality", label: "Quality" },
];

export function AppShell({ currentPath, children }: { currentPath: string; children: ReactNode }) {
  const v2=useSyncExternalStore(subscribeReplayMode,replayEnabled,serverReplayMode);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header">
        <div className="brand-lockup">
          <Link className="brand" href="/" aria-label="MarketRank Workbench home">
            <span className="brand-mark" aria-hidden="true">M</span>
            <span>
              <strong>MarketRank</strong>
              <small>{v2?"Historical replay":"Candidate workbench"}</small>
            </span>
          </Link>
          <span className="status-pill"><span className="status-dot" aria-hidden="true" /> Historical demo</span>
        </div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <Link key={item.href} href={item.href} aria-current={currentPath === item.href ? "page" : undefined}>
              {v2 && item.href==="/customers"?"Historical customers":item.label}
            </Link>
          ))}
        </nav>
      </header>
      <section className="warning-bar" aria-label="Release limitation">
        <span className="warning-icon" aria-hidden="true">!</span>
        {v2?<p><strong>Historical replay.</strong> Trained ranking orders historical candidates. Scores do not represent purchase probability, current availability, or business uplift.</p>:<p><strong>Candidate-only historical snapshot.</strong> Baseline fusion orders retrieved items; there is no trained ranker, live data, probability, or confidence score.</p>}
      </section>
      <main id="main-content">{children}</main>
      <footer>
        <p>Internal evaluation tool · Feedback stays in this browser</p>
        <p>MarketRank {v2?"v2":"v1"}</p>
      </footer>
    </div>
  );
}
