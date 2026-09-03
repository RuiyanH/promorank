import type { Metadata } from "next";
import { AppShell } from "../components/AppShell";
import { ReleaseExperience } from "../components/ReleaseExperience";

export const metadata: Metadata = {
  title: "Demo customers",
  description: "Browse the small, opaque sample of historical demo customers in this MarketRank release.",
};

export default function CustomersPage() {
  return (
    <AppShell currentPath="/customers">
      <ReleaseExperience view="customers" />
    </AppShell>
  );
}
