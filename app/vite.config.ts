import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 빌드 결과는 파이썬 패키지 안(src/tenure/ui/web)으로. 엔진 서버가 / 에서 index.html 을, /app/ 에서 자산을 준다.
// 개발 중에는 `npm run dev` 가 /api 를 엔진(tenure ui, 기본 8790)으로 넘긴다.
export default defineConfig({
  plugins: [react()],
  base: "/app/",
  build: {
    outDir: "../src/tenure/ui/web",
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    modulePreload: { polyfill: false },
  },
  server: {
    port: 5180,
    proxy: { "/api": "http://127.0.0.1:8790", "/static": "http://127.0.0.1:8790", "/logos": "http://127.0.0.1:8790" },
  },
});
