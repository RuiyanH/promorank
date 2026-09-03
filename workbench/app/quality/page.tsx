import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { ReleaseExperience } from "../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Quality",
  description: "Inspect MarketRank candidate coverage, source diagnostics, definitions, and limitations.",
};

export default function QualityPage() {
  return (
    <AppShell currentPath="/quality">
      <ReleaseExperience view="quality" />
    </AppShell>
  );
}
