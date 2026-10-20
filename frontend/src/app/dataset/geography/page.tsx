import type { Metadata } from "next";
import { Suspense } from "react";
import GeographyView from "@/components/views/GeographyView";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Dataset · Geography" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <GeographyView scope="dataset" />
    </Suspense>
  );
}
