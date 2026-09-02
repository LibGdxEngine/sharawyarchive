export const DISCLAIMER =
  "هذه الإجابة مولّدة آليًا من التفريغ الآلي لخواطر الشيخ الشعراوي رحمه الله، وقد تحتوي على أخطاء في النقل أو الفهم. المرجع هو الاستماع إلى المقاطع المذكورة، ولا تُعدّ الإجابة فتوى ولا قولًا منسوبًا للشيخ إلا بما تُثبته المقاطع.";

export default function SmartDisclaimer() {
  return <p className="mt-8 text-xs leading-relaxed text-[var(--color-ink-faint)]">{DISCLAIMER}</p>;
}
