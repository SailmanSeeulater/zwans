import { Suspense } from "react";
import { RoomView } from "@/components/RoomView";

export default function RoomPage() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense>
      <RoomView />
    </Suspense>
  );
}
