import type { Metadata } from "next";
import { AppShell } from "../../components/AppShell";
import { ReleaseExperience } from "../../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Candidate review",
  description: "Review a demo customer's top 12 historical recommendation candidates and source evidence.",
};

export default async function CustomerPage({ params }: { params: Promise<{ customerRef: string }> }) {
  const { customerRef } = await params;
  return (
    <AppShell currentPath="/customers">
      <ReleaseExperience view="customer" customerRef={decodeURIComponent(customerRef)} />
    </AppShell>
  );
}
