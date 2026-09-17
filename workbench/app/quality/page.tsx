import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { ReleaseExperience } from "../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Quality",
  description: "Inspect MarketRank candidate coverage, source diagnostics, definitions, and limitations.",
};

export default async function QualityPage({searchParams}:{searchParams:Promise<{mode?:string}>}) {
  const initialV2=(await searchParams)?.mode==="v2";
  return (
    <AppShell currentPath="/quality" initialV2={initialV2}>
      <ReleaseExperience view="quality" initialV2={initialV2} />
    </AppShell>
  );
}
