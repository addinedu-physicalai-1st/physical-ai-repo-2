<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { postModeClick } from '@/composables/useIntentDispatch';
import { useEdupingStateWs } from '@/composables/useEdupingStateWs';
import WarningModal from '@/common/WarningModal.vue';
import type { ModeTreeNode, ModeTreeGroup } from '@/config/robots';
import { chromeAccent } from '@/config/colors';
import { usePhoneViewport } from '@/common/usePhoneViewport';

// eduping 의 이 모드들은 leader 디바이스가 필요 — 진입 전 미리 체크.
const EDUPING_LEADER_REQUIRED = new Set(['등하원 인사 설정', '율동 등록']);

const edupingStateWs = useEdupingStateWs();
edupingStateWs.start();

const warningOpen = ref(false);
const warningTitle = ref('');
const warningMessage = ref('');

const mode = useModeStore();
const { robot, currentMode } = storeToRefs(mode);

const primary = computed(() => chromeAccent(robot.value.id));
const isPhone = usePhoneViewport();

/** 모바일: hamburger 토글 상태. 모드 선택 후 자동으로 닫힘. */
const drawerOpen = ref(false);

function toggleDrawer(): void {
  drawerOpen.value = !drawerOpen.value;
}

function closeDrawer(): void {
  drawerOpen.value = false;
}

const expanded = ref(new Set<string>());

function isGroup(node: ModeTreeNode): node is ModeTreeGroup {
  return typeof node === 'object';
}

function nodeId(node: ModeTreeNode): string {
  return typeof node === 'string' ? node : node.id;
}

function containsMode(node: ModeTreeNode, target: string): boolean {
  if (typeof node === 'string') return node === target;
  if (node.id === target) return true;
  return node.children.some((c) => containsMode(c, target));
}

function toggle(id: string): void {
  const next = new Set(expanded.value);
  next.has(id) ? next.delete(id) : next.add(id);
  expanded.value = next;
}

async function select(id: string): Promise<void> {
  if (id === currentMode.value) {
    closeDrawer();
    return;
  }
  // eduping 의 leader-required 모드 — 진입 전 leader 연결 확인.
  if (robot.value.id === 'eduping' && EDUPING_LEADER_REQUIRED.has(id)) {
    if (!edupingStateWs.leaderActive.value) {
      warningTitle.value = '리더 디바이스가 연결되어 있지 않습니다';
      warningMessage.value =
        `'${id}' 모드는 리더 디바이스가 필요합니다.\n\n` +
        '먼저 리더 bringup 을 실행해주세요:\n' +
        '    scripts/device-eduping-leader.sh 3';
      warningOpen.value = true;
      return;
    }
  }
  mode.setMode(id);
  closeDrawer();
  // gogoping 의 '추종' 은 교사 얼굴 인증 게이트가 책임짐 — 인증 성공 후 App.vue 에서 postModeClick 을 호출한다.
  if (robot.value.id === 'gogoping' && id === '추종') return;
  try {
    await postModeClick(id, robot.value.id);
  } catch { /* backend 오류는 UI에 영향 없음 */ }
}

function expandAncestors(nodes: ModeTreeNode[], target: string, acc: Set<string>): boolean {
  for (const node of nodes) {
    if (typeof node === 'string') {
      if (node === target) return true;
    } else {
      if (node.id === target || expandAncestors(node.children, target, acc)) {
        acc.add(node.id);
        return true;
      }
    }
  }
  return false;
}

watch(
  currentMode,
  (newMode) => {
    const next = new Set(expanded.value);
    expandAncestors(robot.value.modeTree, newMode, next);
    expanded.value = next;
  },
  { immediate: true },
);
</script>

<template>
  <!-- 모바일: hamburger 토글 + 슬라이드 인 drawer -->
  <template v-if="isPhone">
    <button
      class="hamburger"
      :class="{ open: drawerOpen }"
      :style="{ '--primary': primary }"
      :aria-expanded="drawerOpen"
      aria-label="모드 메뉴"
      @click="toggleDrawer"
    >
      <span class="bar"></span>
      <span class="bar"></span>
      <span class="bar"></span>
    </button>

    <Transition name="backdrop-fade">
      <div v-if="drawerOpen" class="backdrop" @click="closeDrawer" />
    </Transition>

    <Transition name="drawer-slide">
      <nav
        v-if="drawerOpen"
        class="mode-panel drawer"
        :style="{ '--primary': primary }"
      >
        <div class="drawer-header">
          <span class="drawer-title">모드 선택</span>
          <button class="drawer-close" aria-label="닫기" @click="closeDrawer">✕</button>
        </div>
        <div class="node-list">
          <template v-for="node in robot.modeTree" :key="nodeId(node)">
            <button
              v-if="!isGroup(node)"
              class="mode-btn"
              :class="{ active: node === currentMode }"
              @click="select(node)"
            >
              {{ node }}
            </button>
            <div v-else class="group-section">
              <button
                class="group-btn"
                :class="{ 'has-active': containsMode(node, currentMode) }"
                :aria-expanded="expanded.has(node.id)"
                @click="toggle(node.id)"
              >
                <span>{{ node.id }}</span>
                <span class="chevron" :class="{ open: expanded.has(node.id) }">›</span>
              </button>
              <Transition name="dropdown">
                <div v-show="expanded.has(node.id)" class="sub-list">
                  <button
                    v-if="node.selfSelectable !== false"
                    class="sub-btn self-btn"
                    :class="{ active: node.id === currentMode }"
                    @click="select(node.id)"
                  >
                    {{ node.id }}
                  </button>
                  <template v-for="child in node.children" :key="nodeId(child)">
                    <button
                      v-if="!isGroup(child)"
                      class="sub-btn"
                      :class="{ active: child === currentMode }"
                      @click="select(child)"
                    >
                      {{ child }}
                    </button>
                    <div v-else class="subsub-section">
                      <button
                        class="subsub-group-btn"
                        :class="{ 'has-active': containsMode(child, currentMode) }"
                        :aria-expanded="expanded.has(child.id)"
                        @click="toggle(child.id)"
                      >
                        <span>{{ child.id }}</span>
                        <span class="chevron" :class="{ open: expanded.has(child.id) }">›</span>
                      </button>
                      <Transition name="dropdown">
                        <div v-show="expanded.has(child.id)" class="subsub-list">
                          <button
                            v-if="child.selfSelectable !== false"
                            class="subsub-btn self-btn"
                            :class="{ active: child.id === currentMode }"
                            @click="select(child.id)"
                          >
                            {{ child.id }}
                          </button>
                          <button
                            v-for="sub in child.children"
                            :key="nodeId(sub)"
                            class="subsub-btn"
                            :class="{ active: nodeId(sub) === currentMode }"
                            @click="select(nodeId(sub))"
                          >
                            {{ nodeId(sub) }}
                          </button>
                        </div>
                      </Transition>
                    </div>
                  </template>
                </div>
              </Transition>
            </div>
          </template>
        </div>
      </nav>
    </Transition>
  </template>

  <!-- Desktop: 항상 보이는 우측 트리 패널 -->
  <nav v-else class="mode-panel" :style="{ '--primary': primary }">
    <div class="node-list">
      <template v-for="node in robot.modeTree" :key="nodeId(node)">
        <!-- 리프 모드 -->
        <button
          v-if="!isGroup(node)"
          class="mode-btn"
          :class="{ active: node === currentMode }"
          @click="select(node)"
        >
          {{ node }}
        </button>

        <!-- 그룹 모드 -->
        <div v-else class="group-section">
          <button
            class="group-btn"
            :class="{ 'has-active': containsMode(node, currentMode) }"
            :aria-expanded="expanded.has(node.id)"
            @click="toggle(node.id)"
          >
            <span>{{ node.id }}</span>
            <span class="chevron" :class="{ open: expanded.has(node.id) }">›</span>
          </button>

          <Transition name="dropdown">
          <div v-show="expanded.has(node.id)" class="sub-list">
            <!-- 모드 자체 선택 항목 (selfSelectable: false 이면 숨김) -->
            <button
              v-if="node.selfSelectable !== false"
              class="sub-btn self-btn"
              :class="{ active: node.id === currentMode }"
              @click="select(node.id)"
            >
              {{ node.id }}
            </button>

            <!-- 자식 노드 -->
            <template v-for="child in node.children" :key="nodeId(child)">
              <!-- 리프 태스크 -->
              <button
                v-if="!isGroup(child)"
                class="sub-btn"
                :class="{ active: child === currentMode }"
                @click="select(child)"
              >
                {{ child }}
              </button>

              <!-- 그룹 태스크 (예: 율동, 가게놀이 → 정리정돈) -->
              <div v-else class="subsub-section">
                <button
                  class="subsub-group-btn"
                  :class="{ 'has-active': containsMode(child, currentMode) }"
                  :aria-expanded="expanded.has(child.id)"
                  @click="toggle(child.id)"
                >
                  <span>{{ child.id }}</span>
                  <span class="chevron" :class="{ open: expanded.has(child.id) }">›</span>
                </button>

                <Transition name="dropdown">
                <div v-show="expanded.has(child.id)" class="subsub-list">
                  <button
                    v-if="child.selfSelectable !== false"
                    class="subsub-btn self-btn"
                    :class="{ active: child.id === currentMode }"
                    @click="select(child.id)"
                  >
                    {{ child.id }}
                  </button>
                  <button
                    v-for="sub in child.children"
                    :key="nodeId(sub)"
                    class="subsub-btn"
                    :class="{ active: nodeId(sub) === currentMode }"
                    @click="select(nodeId(sub))"
                  >
                    {{ nodeId(sub) }}
                  </button>
                </div>
                </Transition>
              </div>
            </template>
          </div>
          </Transition>
        </div>
      </template>
    </div>
  </nav>
  <WarningModal
    v-model:open="warningOpen"
    :title="warningTitle"
    :message="warningMessage"
  />
</template>

<style scoped>
.mode-panel {
  position: absolute;
  right: 0;
  top: 0;
  bottom: 0;
  width: 200px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 20px 10px;
  z-index: 20;
  overflow-y: auto;
}

/* 모바일 hamburger 토글 — 우상단 floating action button */
.hamburger {
  position: fixed;
  top: calc(env(safe-area-inset-top, 0px) + 10px);
  right: calc(env(safe-area-inset-right, 0px) + 10px);
  width: 44px;
  height: 44px;
  border-radius: 12px;
  border: none;
  background: rgba(255, 255, 255, 0.92);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  cursor: pointer;
  z-index: 40;
  padding: 0;
  backdrop-filter: blur(6px);
  -webkit-tap-highlight-color: transparent;
}
.hamburger .bar {
  width: 20px;
  height: 2.5px;
  border-radius: 2px;
  background: var(--primary);
  transition: transform 0.22s ease, opacity 0.22s ease;
}
.hamburger.open .bar:nth-child(1) {
  transform: translateY(7.5px) rotate(45deg);
}
.hamburger.open .bar:nth-child(2) {
  opacity: 0;
}
.hamburger.open .bar:nth-child(3) {
  transform: translateY(-7.5px) rotate(-45deg);
}

/* drawer backdrop */
.backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 20, 30, 0.45);
  z-index: 38;
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}
.backdrop-fade-enter-active,
.backdrop-fade-leave-active {
  transition: opacity 0.2s ease;
}
.backdrop-fade-enter-from,
.backdrop-fade-leave-to {
  opacity: 0;
}

/* drawer 자체 — 우측에서 슬라이드 */
.mode-panel.drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(78vw, 320px);
  padding: 12px 10px;
  padding-top: calc(env(safe-area-inset-top, 0px) + 64px); /* hamburger 아래 */
  padding-bottom: calc(env(safe-area-inset-bottom, 0px) + 12px);
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.18);
  z-index: 39;
  overflow-y: auto;
  justify-content: flex-start;
}
.drawer-header {
  position: absolute;
  top: calc(env(safe-area-inset-top, 0px) + 16px);
  left: 14px;
  right: 64px; /* hamburger 자리 비움 */
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.drawer-title {
  font-size: 16px;
  font-weight: 800;
  color: #333;
  letter-spacing: -0.3px;
}
.drawer-close {
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  color: #888;
  font-size: 18px;
  font-weight: 700;
  cursor: pointer;
  border-radius: 8px;
  display: none; /* hamburger 회전 X 로 대체 — 별도 X 버튼 안 보임 */
}

.drawer-slide-enter-active,
.drawer-slide-leave-active {
  transition: transform 0.28s cubic-bezier(0.32, 0.72, 0.24, 1);
}
.drawer-slide-enter-from,
.drawer-slide-leave-to {
  transform: translateX(100%);
}

/* drawer 안 모드 버튼은 폰 사이즈 — 데스크톱 트리 스타일 그대로 두되 조금 더 큰 탭 영역 */
.mode-panel.drawer .mode-btn,
.mode-panel.drawer .group-btn {
  font-size: 15px;
  padding: 13px 14px;
  min-height: 46px;
}
.mode-panel.drawer .sub-btn,
.mode-panel.drawer .subsub-group-btn {
  font-size: 14px;
  padding: 11px 12px;
  min-height: 42px;
}
.mode-panel.drawer .subsub-btn {
  font-size: 13px;
  padding: 10px 11px;
  min-height: 38px;
}

.node-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

/* 공통 버튼 베이스 */
.mode-btn,
.group-btn,
.sub-btn,
.subsub-group-btn,
.subsub-btn {
  width: 100%;
  text-align: left;
  border: none;
  cursor: pointer;
  font-family: inherit;
  border-radius: 10px;
  transition: background 0.12s, color 0.12s;
  word-break: keep-all;
  line-height: 1.35;
}

/* 최상위 모드 버튼 */
.mode-btn {
  background: rgba(255, 255, 255, 0.78);
  color: #555;
  font-size: 15px;
  font-weight: 600;
  padding: 13px 16px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.mode-btn:hover {
  background: rgba(255, 255, 255, 0.95);
}
.mode-btn.active {
  background: var(--primary);
  color: white;
  box-shadow: 0 2px 8px color-mix(in srgb, var(--primary) 45%, transparent);
}

/* 그룹 헤더 */
.group-btn {
  background: rgba(255, 255, 255, 0.78);
  color: #555;
  font-size: 15px;
  font-weight: 600;
  padding: 13px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
}
.group-btn:hover {
  background: rgba(255, 255, 255, 0.95);
}
.group-btn.has-active {
  background: color-mix(in srgb, var(--primary) 14%, transparent);
  color: color-mix(in srgb, var(--primary) 80%, #000);
}

/* 1단계 서브 리스트 */
.sub-list {
  margin-top: 3px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding-left: 10px;
}

.sub-btn {
  background: rgba(255, 255, 255, 0.62);
  color: #666;
  font-size: 14px;
  font-weight: 500;
  padding: 11px 13px;
}
.sub-btn:hover {
  background: rgba(255, 255, 255, 0.88);
}
.sub-btn.active {
  background: var(--primary);
  color: white;
  box-shadow: 0 2px 6px color-mix(in srgb, var(--primary) 40%, transparent);
}
.sub-btn.self-btn {
  opacity: 0.82;
  font-style: italic;
}
.sub-btn.self-btn.active {
  opacity: 1;
  font-style: normal;
}

/* 2단계 서브그룹 */
.subsub-section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.subsub-group-btn {
  background: rgba(255, 255, 255, 0.62);
  color: #666;
  font-size: 14px;
  font-weight: 500;
  padding: 11px 13px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.subsub-group-btn:hover {
  background: rgba(255, 255, 255, 0.88);
}
.subsub-group-btn.has-active {
  background: color-mix(in srgb, var(--primary) 10%, transparent);
  color: color-mix(in srgb, var(--primary) 80%, #000);
}

.subsub-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding-left: 8px;
}

.subsub-btn {
  background: rgba(255, 255, 255, 0.5);
  color: #777;
  font-size: 13px;
  font-weight: 500;
  padding: 9px 11px;
}
.subsub-btn:hover {
  background: rgba(255, 255, 255, 0.82);
}
.subsub-btn.active {
  background: var(--primary);
  color: white;
  box-shadow: 0 1px 5px color-mix(in srgb, var(--primary) 40%, transparent);
}
.subsub-btn.self-btn {
  opacity: 0.8;
  font-style: italic;
}
.subsub-btn.self-btn.active {
  opacity: 1;
  font-style: normal;
}

/* 드롭다운 애니메이션 */
.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
  transform-origin: top center;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: scaleY(0.88) translateY(-4px);
}

/* 체브론 */
.chevron {
  font-size: 16px;
  line-height: 1;
  transition: transform 0.15s;
  display: inline-block;
  flex-shrink: 0;
}
.chevron.open {
  transform: rotate(90deg);
}
</style>
