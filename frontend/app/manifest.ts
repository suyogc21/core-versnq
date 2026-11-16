import type { MetadataRoute } from "next";

/** The installable app (step C2): "Add to home screen" on Android and iPhone. */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Versnq Core",
    short_name: "Versnq",
    description: "Leads, calls, follow-ups and customers in one place",
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: "#f5f5f7",
    theme_color: "#1d1d1f",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
