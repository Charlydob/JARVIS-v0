/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  readonly JARVIS_VAD_SILENCE_SECONDS?: string
  readonly VITE_APP_VERSION?: string
  readonly VITE_BUILD_SHA?: string
}
