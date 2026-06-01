// Standalone 진입점 — robot-web 의 다른 component (App.vue, 모드 셀렉터, 음성 컨트롤러,
// wake word, ai-service WS 등) 없이 오로지 DepthViewer 만 마운트. 같은 Vite 프로젝트라
// 의존성·alias·proxy 공유, 대신 runtime 에서 main.ts 와 격리.
import { createApp } from 'vue';
import { createPinia } from 'pinia';
import DepthOnlyApp from './DepthOnlyApp.vue';

const app = createApp(DepthOnlyApp);
app.use(createPinia());
app.mount('#app');
