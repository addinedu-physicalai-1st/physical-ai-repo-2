import type { Plugin, Connect } from 'vite';
import type { IncomingMessage, ServerResponse } from 'node:http';
import robotsData from '../../../shared/robots.json';

type RobotId = 'eduping' | 'gogoping' | 'noriarm';

const ROBOT_MODES: Record<RobotId, string[]> = Object.fromEntries(
  (robotsData.robots as Array<{ id: string; modes: string[] }>).map((r) => [
    r.id,
    r.modes,
  ])
) as Record<RobotId, string[]>;

const STOP_TOKENS = [...(robotsData.stopTokens as string[]), 'stop'];

type IntentResponse =
  | { kind: 'mode_change'; mode: string }
  | { kind: 'sub_command'; action: string }
  | { kind: 'chat'; reply: string; emotion: string }
  | { kind: 'ignored' };

function pickMockEmotion(text: string): string {
  const lower = text.toLowerCase();
  if (/안녕|하이|반가|hello|hi/.test(lower)) return 'hello';
  if (/슬프|속상|울/.test(text)) return 'sad';
  if (/위험|안돼|만지지/.test(text)) return 'angry';
  if (/심심|지루/.test(text)) return 'bored';
  if (/놀이|놀자|재밌/.test(text)) return 'fun';
  if (/좋아|기뻐|행복/.test(text)) return 'happy';
  if (/뭐야|왜|어떻게/.test(text)) return 'interest';
  return 'basic';
}

function classifyIntent(text: string, robot: RobotId): IntentResponse {
  const lower = text.toLowerCase();
  const modes = ROBOT_MODES[robot] ?? [];

  for (const mode of modes) {
    if (text.includes(mode)) {
      return { kind: 'mode_change', mode };
    }
  }
  for (const token of STOP_TOKENS) {
    if (lower.includes(token.toLowerCase())) {
      return { kind: 'sub_command', action: 'stop' };
    }
  }
  return {
    kind: 'chat',
    reply: `"${text}" 말씀이시군요. 선생님께 같이 여쭤볼까요?`,
    emotion: pickMockEmotion(text),
  };
}

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk) => chunks.push(chunk as Buffer));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.end(JSON.stringify(body));
}

export function intentMockPlugin(): Plugin {
  return {
    name: 'intent-mock-plugin',
    configureServer(server) {
      const handler: Connect.NextHandleFunction = async (req, res, next) => {
        const originalUrl = req.originalUrl ?? req.url ?? '';

        if (
          !originalUrl.startsWith('/api/voice/intent') &&
          !originalUrl.startsWith('/api/mode') &&
          !originalUrl.startsWith('/api/noriarm/games/ox-quiz/answer')
        ) {
          next();
          return;
        }
        if (req.method !== 'POST') {
          sendJson(res, 405, { error: 'method not allowed' });
          return;
        }

        try {
          const raw = await readBody(req);
          const body = raw
            ? (JSON.parse(raw) as {
                text?: string;
                robot?: RobotId;
                mode?: string;
                answer?: 'O' | 'X';
              })
            : {};

          if (originalUrl.startsWith('/api/voice/intent')) {
            const text = (body.text ?? '').trim();
            const robot = body.robot ?? 'gogoping';
            sendJson(res, 200, classifyIntent(text, robot));
            return;
          }

          if (originalUrl.startsWith('/api/mode')) {
            const robot = body.robot ?? 'gogoping';
            const mode = body.mode ?? '대기';
            sendJson(res, 200, { ok: true, robot, mode });
            return;
          }

          if (originalUrl.startsWith('/api/noriarm/games/ox-quiz/answer')) {
            // mock 모드 fallback — 실제 OX 트랙 재생은 Control Server (ROS bridge) 가 담당.
            // mock 에서는 UI 흐름만 확인할 수 있도록 OK 만 반환. UrdfViewer 의 SSE 는 연결 실패 후
            // static URDF 표시.
            const answer = body.answer === 'X' ? 'X' : 'O';
            console.log(`[mock] /api/noriarm/games/ox-quiz/answer answer=${answer} (no ROS publish)`);
            sendJson(res, 200, { ok: true, action: 'mock', answer });
            return;
          }
        } catch (err) {
          sendJson(res, 400, { error: (err as Error).message });
        }
      };

      server.middlewares.use(handler);
    },
  };
}
