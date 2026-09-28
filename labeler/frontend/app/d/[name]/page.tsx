import { LabelingPage } from "@/components/labeler/labeling-page";

export default async function Page({ params }: { params: Promise<{ name: string }> }) {
  const { name } = await params;
  return <LabelingPage name={name} />;
}
