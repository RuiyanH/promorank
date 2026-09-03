import { AppShell } from "./components/AppShell";
import { ReleaseExperience } from "./components/ReleaseExperience";

export default function Home() {
  return (
    <AppShell currentPath="/">
      <ReleaseExperience view="overview" />
    </AppShell>
  );
}
