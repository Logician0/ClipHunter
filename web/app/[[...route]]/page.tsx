import Studio from "../studio";
export default async function Page({
  params,
}: {
  params: Promise<{ route?: string[] }>;
}) {
  const { route = [] } = await params;
  return <Studio route={route} />;
}
