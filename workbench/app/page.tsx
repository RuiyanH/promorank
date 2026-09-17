import { AppShell } from "./components/AppShell";
import { ReleaseExperience } from "./components/ReleaseExperience";

export default async function Home({searchParams}:{searchParams:Promise<{mode?:string}>}) {
  const initialV2=(await searchParams)?.mode==="v2";
  return (
    <AppShell currentPath="/" initialV2={initialV2}>
      <ReleaseExperience view="overview" initialV2={initialV2} />
    </AppShell>
  );
}
