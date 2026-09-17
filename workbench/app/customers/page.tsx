import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { ReleaseExperience } from "../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Demo customers",
  description: "Browse the small, opaque sample of historical demo customers in this MarketRank release.",
};

export default async function CustomersPage({searchParams}:{searchParams:Promise<{mode?:string}>}) {
  const initialV2=(await searchParams)?.mode==="v2";
  return (
    <AppShell currentPath="/customers" initialV2={initialV2}>
      <ReleaseExperience view="customers" initialV2={initialV2} />
    </AppShell>
  );
}
