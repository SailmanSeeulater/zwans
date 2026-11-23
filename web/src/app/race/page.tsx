import { Suspense } from "react";
import { RaceView } from "@/components/RaceView";

export default function RacePage() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <RaceView />
    </Suspense>
  );
}
