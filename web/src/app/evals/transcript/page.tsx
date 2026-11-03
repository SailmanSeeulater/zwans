import { Suspense } from "react";
import { TranscriptView } from "@/components/TranscriptView";

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <TranscriptView />
    </Suspense>
  );
}
