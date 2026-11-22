# Learning Log

## 记录规则

每完成一个可测试切片新增一条记录。先由本人填写，再允许 AI 做 L2 审阅；不要让 AI 代写“我学会了什么”。

## Entry 001 — Health endpoint

- Date:
- AI level: L0
- Goal: 让 FastAPI 对 `GET /health` 返回精确 JSON。
- I wrote independently:
- First failure:
- My hypothesis:
- Smallest experiment:
- What fixed it:
- Why the solution works:
- One failure mode:
- Retry without AI date:
- Evidence link or commit:

## Entry 002 — Frontend health status

- Date: 2026-09-15
- AI level: L1 for React state/request learning; L3 for toolchain, tests, proxy and visual styling
- I wrote independently: `App.tsx` connection state and health request after guided explanation
- AI prepared: Vite/Vitest configuration, three state tests, development proxy, semantic presentation markup and `styles.css`
- Verified: 3 Vitest tests passed; TypeScript check passed; production build passed
- Browser QA: desktop and 390×844 CSS viewport checked; no browser console warnings or errors
- I can explain:
  - Why `useState` triggers a new render:
  - Why `useEffect(..., [])` runs after the first render:
  - Why the browser requests `/api/health` instead of port 8000 directly:
  - How connecting, online and offline states are selected:
- Retry without AI date:
- Evidence link or commit:
