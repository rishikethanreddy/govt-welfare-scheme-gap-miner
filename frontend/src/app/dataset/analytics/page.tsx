import type { Metadata } from "next";
import { Suspense } from "react";
import AnalyticsView from "@/components/views/AnalyticsView";
import { LoadingBlock } from "@/components/ui";

export const metadata: Metadata = { title: "Dataset · Analytics" };

export default function Page() {
  return (
    <Suspense fallback={<LoadingBlock rows={6} />}>
      <AnalyticsView scope="dataset" />
    </Suspense>
  );
}
