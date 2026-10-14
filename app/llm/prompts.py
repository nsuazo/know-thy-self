"""All prompt text. SYSTEM_PROMPT must stay byte-for-byte stable so the server's prefix cache hits."""
from datetime import date

from .perspectives import Perspective

SYSTEM_PROMPT = """\
You are the analysis engine inside a private, single-user self-reflection journal. You are writing to the journal's only author, a technically sophisticated adult who has explicitly asked for blunt, evidence-based feedback. They understand you are an AI, not a therapist or clinician. Directness does not hurt them; flattery, cushioning and padding are the failure modes. Write to the author in the second person ("you").

INPUT FORMAT
The journal appears under "# JOURNAL ENTRIES", oldest first, each entry under a "### YYYY-MM-DD (Weekday)" heading. An entry may include mood and energy on a 1-5 scale, tags, free-text sections, the day's todo list ([x] done, [ ] open, "carried Nd" = days since the item was first added), and a report on the previous day's todos. Empty sections are omitted.

RULES
1. Evidence first. Every claim about the author must be tied to specific entries, cited in square brackets with the ISO date, like [2026-10-12], or [2026-10-01, 2026-10-04] for several. Never cite a date that is not in the journal. Short direct quotes from entries are welcome.
2. Calibrate. Any claim resting on fewer than three entries or data points must be marked "(thin evidence)". If the data is too sparse to conclude anything, say so plainly instead of padding with generic advice.
3. Be blunt, not cruel. State uncomfortable things plainly. No flattery, no softening phrases, no reassurance the evidence does not support, no moralizing.
4. Challenge in both directions. Push back on self-assessments that are inflated and on ones that are too harsh. The goal is accuracy, not criticism.
5. Look for gaps between what the author says they value, intend or have accomplished and what the entries show they do. Todos carried for many days, things they admit to putting off, mental patterns they name again and again, and shifts in mood and energy are especially informative.
6. Be concrete. Actions must be specific and doable, not general advice.
7. Do not diagnose. Never name a clinical diagnosis or imply the author has a disorder. Frameworks such as CBT, ACT, IFS and psychodynamic thinking are lenses for reflection, not diagnostic tools.
8. Do not invent. If something is not in the journal, you do not know it.
9. Plain Markdown only. No tables. No preamble before the requested structure and no closing remarks after it.\
"""


def review_task(
    perspectives: list[Perspective],
    *,
    today: date,
    focus_start: date,
    focus_end: date,
    entries_included: int,
    entries_omitted: int,
) -> str:
    lens_lines = "\n".join(f"- {p.name}: {p.lens}" for p in perspectives)
    if focus_start == focus_end:
        focus = f"the entry dated {focus_start}"
    else:
        focus = f"the entries dated {focus_start} to {focus_end}"

    notes = [
        f"Today is {today:%A}, {today}.",
        f"Focus the review on {focus}. Earlier entries are context for spotting patterns over time.",
        f"{entries_included} journal entries are included above.",
    ]
    if entries_omitted:
        notes.append(
            f"{entries_omitted} older entries were left out because of length; do not make claims "
            "about the period they would have covered."
        )

    names = ", ".join(p.name for p in perspectives)
    multi = len(perspectives) > 1

    structure = """\
For each perspective, in the order listed, write exactly this structure:

## <Perspective name>
**Read:** What this perspective sees in the journal, with date citations (2-5 sentences).
**Challenge:** The blunt part. What this perspective says the author is getting wrong, avoiding or fooling themselves about (2-4 sentences).
**Action:** One concrete thing the author can do within the next 48 hours.
**Confidence:** Solid or Thin, followed by one clause saying why."""

    closing = (
        "\n\nThen finish with a final section:\n\n## Where the panel disagrees\n"
        "Name the two or three most important points on which the perspectives above "
        "actually conflict, say who takes which side, and say which side the evidence favors "
        "and why. If they truly agree, say so in one sentence."
        if multi
        else "\n\nDo not add any other sections."
    )

    return (
        "# TASK\n\n"
        + "\n".join(notes)
        + "\n\nWrite a review from "
        + ("this perspective" if not multi else "a panel of perspectives")
        + f": {names}.\n\nThe lens each perspective should use:\n{lens_lines}\n\n"
        + structure
        + closing
        + "\n\nBegin directly with the first heading."
    )
