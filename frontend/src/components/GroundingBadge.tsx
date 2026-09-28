export default function GroundingBadge({ grounded }: { grounded?: boolean | null }) {
  if (grounded === true) {
    return (
      <p className="w-fit rounded-full bg-forest px-3 py-1 text-xs font-bold text-cream">
        ✓ 모든 내용이 문서로 확인되었습니다
      </p>
    );
  }
  if (grounded === false) {
    return (
      <p className="w-fit rounded-full bg-mustard px-3 py-1 text-xs font-bold text-ink">
        ! 일부 내용이 문서로 확인되지 않았습니다. 출처를 직접 확인해 주세요.
      </p>
    );
  }
  return null;
}
