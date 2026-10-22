// 엔진의 상태·단계 값 → 한국어 이름

export const STATUS: Record<string, string> = {
  running: "실행 중", done_approved: "승인 완료", done_unapproved: "미승인 종료", done_design: "설계 완료",
  stopped_rate_limit: "한도 도달", stopped_user: "사용자 중지", failed: "실패", broken: "기록 손상",
  stale: "멈춤 (비정상 종료)",
};

export const STEP: Record<string, string> = {
  propose: "설계안", critique: "비판·개정", synthesize: "설계 종합", implement: "구현", fix: "리뷰 반영",
  review: "리뷰", report: "결과 요약", explore: "사전 조사", audit: "감사", arbitrate: "중재", test: "테스트",
  repro: "재현 테스트", testguard: "테스트 변경 감지", dedup: "중복 확인", base: "기준 커밋", stalled: "수렴 안 됨",
  design_only: "설계만", approved: "승인", unapproved: "미승인", route: "경로 선택",
};

export const PHASE: Record<string, string> = {
  init: "준비", explore: "사전 조사", debate: "설계 토론", build: "구현·리뷰", audit: "감사", done: "끝",
};

export const TEST_STATUS: Record<string, string> = { passed: "통과", failed: "실패", error: "실행 불가", timeout: "시간 초과" };

// 실행 활동 상태 (DESIGN.md 36.3.1)
export const ACTIVITY: Record<string, string> = {
  blocked: "나를 기다림", "done-unseen": "끝남 · 안 봄", working: "진행 중", unverifiable: "소식 끊김",
  failed: "실패", idle: "끝",
};

// 단계 결과 (36.3.2)
export const OUTCOME: Record<string, string> = { done: "완료", blocked: "막힘", failed: "실패", unconfirmed: "확인 안 됨" };

export const WORKFLOW_NOTE: Record<string, string> = {
  auto: "과제를 보고 quick 또는 classic 을 고름",
  quick: "혼자 구현 → 짧은 리뷰",
  classic: "설계 토론 → 구현 → 교차 리뷰",
  lean: "혼자 설계 → 구현 → 리뷰 (가벼운 모델)",
  existing: "기존 코드 조사 → 변경 설계 → 구현 → 리뷰",
  secure: "토론 → 구현 → 리뷰 + 보안 리뷰 → 감사",
};
