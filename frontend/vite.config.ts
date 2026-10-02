import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";

// Plugin order matters:
//   1. tanstackStart  - must run first; owns the SSR/client pipeline
//   2. nitro          - build only; turns the SSR output into a deploy target
//   3. react/tailwind - normal asset transforms
//   4. tsConfigPaths  - resolves the "@/*" alias from tsconfig.json
export default defineConfig(({ command }) => ({
  plugins: [
    tanstackStart({
      // Fail loudly if server-only modules leak into the client bundle.
      importProtection: {
        behavior: "error",
        client: {
          files: ["**/server/**"],
          specifiers: ["server-only"],
        },
      },
      // Our own entry (src/server.ts) wraps the default one so SSR failures
      // render a readable page instead of a blank 500.
      server: { entry: "server" },
    }),
    ...(command === "build" ? [nitroPlugin()] : []),
    viteReact(),
    tailwindcss(),
    tsConfigPaths(),
  ],
  resolve: {
    // React and TanStack must not be duplicated between the server and
    // client graphs, otherwise hooks/context break at runtime.
    dedupe: ["react", "react-dom", "@tanstack/react-router"],
  },
}));

// `nitro/vite` is only pulled in for builds so the dev server doesn't pay for it.
async function nitroPlugin() {
  const { nitro } = await import("nitro/vite");
  return nitro({
    // Lets Nitro pick the deploy target from the environment: the Vercel
    // preset on Vercel, the Cloudflare preset on Cloudflare, Node locally.
    defaultPreset: "cloudflare-module",
  });
}
