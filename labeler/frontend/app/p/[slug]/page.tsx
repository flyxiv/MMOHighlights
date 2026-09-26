import { LabelingPage } from "@/components/labeler/labeling-page";

export default async function Page({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <LabelingPage slug={slug} />;
}
