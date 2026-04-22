import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const apiTarget = env.VITE_API_BASE_URL || 'http://127.0.0.1:8000';

  return {
    server: {
      port: 5173,
      proxy: {
        '/backtest': { target: apiTarget, changeOrigin: true },
        '/config':   { target: apiTarget, changeOrigin: true },
        '/health':   { target: apiTarget, changeOrigin: true },
      },
    },
  };
});
