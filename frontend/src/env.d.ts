/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_AMAP_WEB_JS_KEY?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module 'ant-design-vue/dist/reset.css'
declare module '*.vue' { import type { DefineComponent } from 'vue'; const component: DefineComponent; export default component; } 
