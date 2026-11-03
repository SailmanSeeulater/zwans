import { Suspense } from "react";
import { SessionView } from "@/components/SessionView";

export default function SessionPage() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <SessionView />
    </Suspense>
  );
}
