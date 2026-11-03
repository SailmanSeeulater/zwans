import { Suspense } from "react";
import { CompareView } from "@/components/CompareView";

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <CompareView />
    </Suspense>
  );
}
