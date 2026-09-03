import Link from "next/link";
import type { ReactNode } from "react";

const navigation = [
  { href: "/", label: "Overview" },
  { href: "/customers", label: "Demo customers" },
  { href: "/quality", label: "Quality" },
];

export function AppShell({ currentPath, children }: { currentPath: string; children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="site-header">
        <div className="brand-lockup">
          <Link className="brand" href="/" aria-label="MarketRank Workbench home">
            <span className="brand-mark" aria-hidden="true">M</span>
            <span>
              <strong>MarketRank</strong>
              <small>Candidate workbench</small>
            </span>
          </Link>
          <span className="status-pill"><span className="status-dot" aria-hidden="true" /> Historical demo</span>
        </div>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <Link key={item.href} href={item.href} aria-current={currentPath === item.href ? "page" : undefined}>
              {item.label}
            </Link>
          ))}
        </nav>
      </header>
      <section className="warning-bar" aria-label="Release limitation">
        <span className="warning-icon" aria-hidden="true">!</span>
        <p><strong>Candidate-only historical snapshot.</strong> Baseline fusion orders retrieved items; there is no trained ranker, live data, probability, or confidence score.</p>
      </section>
      <main id="main-content">{children}</main>
      <footer>
        <p>Internal evaluation tool · Feedback stays in this browser</p>
        <p>MarketRank v1</p>
      </footer>
    </div>
  );
}
