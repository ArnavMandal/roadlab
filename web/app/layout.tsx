import "./globals.css";
export const metadata = {
  title: "RoadLab · Offline perception evaluation",
  description: "A local road-segmentation evaluation lab powered by Relay.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
