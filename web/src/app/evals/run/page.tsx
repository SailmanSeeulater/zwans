import { Suspense } from "react";
import { RunView } from "@/components/RunView";

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <RunView />
    </Suspense>
  );
}
