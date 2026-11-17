import { Suspense } from "react";
import { MatrixView } from "@/components/MatrixView";

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <MatrixView />
    </Suspense>
  );
}
