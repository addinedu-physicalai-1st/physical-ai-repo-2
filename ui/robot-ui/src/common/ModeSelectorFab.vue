<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { useModeStore } from '@/stores/mode';
import { postModeClick } from '@/composables/useIntentDispatch';
import type { ModeTreeNode, ModeTreeGroup, RobotId } from '@/config/robots';

const mode = useModeStore();
const { robot, currentMode } = storeToRefs(mode);

const PRIMARY: Record<RobotId, string> = {
  eduping:  '#db2777',
  gogoping: '#000000',
  noriarm:  '#3a8fc2',
};
const primary = computed(() => PRIMARY[robot.value.id]);

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
  if (id === currentMode.value) return;
  mode.setMode(id);
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
  <nav class="mode-panel" :style="{ '--primary': primary }">
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
