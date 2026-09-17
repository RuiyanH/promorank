import type { Metadata } from "next";
import { AppShell } from "../../components/AppShell";
import { ReleaseExperience } from "../../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Candidate review",
  description: "Review a demo customer's top 12 historical recommendation candidates and source evidence.",
};

export default async function CustomerPage({ params, searchParams }: { params: Promise<{ customerRef: string }>; searchParams:Promise<{mode?:string}> }) {
  const { customerRef } = await params;
  const initialV2=(await searchParams)?.mode==="v2";
  return (
    <AppShell currentPath="/customers" initialV2={initialV2}>
      <ReleaseExperience view="customer" customerRef={decodeURIComponent(customerRef)} initialV2={initialV2} />
    </AppShell>
  );
}
