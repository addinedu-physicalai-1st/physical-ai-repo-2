import type { InjectionKey } from 'vue';
import type { UseCameraPan } from './composables/useCameraPan';

export const CAMERA_PAN_KEY: InjectionKey<UseCameraPan> = Symbol('cameraPan');
