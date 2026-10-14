"""The panel of perspectives. `lens` is injected into the task prompt."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Perspective:
    key: str
    name: str
    lens: str


PERSPECTIVES: list[Perspective] = [
    Perspective(
        "stoic",
        "Stoic",
        "Stoicism (Epictetus, Marcus Aurelius, Seneca). What is and isn't in the author's control; "
        "judgments about events versus the events themselves; whether time and attention go to "
        "things that are up to them; virtue and conduct over outcomes and reputation; "
        "premeditation of setbacks.",
    ),
    Perspective(
        "existentialist",
        "Existentialist",
        "Existentialism (Sartre, Camus, Kierkegaard, de Beauvoir). Authenticity versus bad faith; "
        "freedom and responsibility; choices made by default or drift; excuses presented as "
        "constraints; whether the meaning claimed in the entries matches the life actually being "
        "chosen.",
    ),
    Perspective(
        "cbt",
        "CBT",
        "Cognitive behavioral therapy as a way of reading the entries. Automatic thoughts and "
        "cognitive distortions (all-or-nothing thinking, catastrophizing, mind-reading, emotional "
        "reasoning, discounting the positive, should-statements); the link between thoughts, "
        "mood and behavior; behavioral experiments. Name the specific distortion and the specific "
        "entry. This is a lens, not a diagnosis.",
    ),
    Perspective(
        "act",
        "ACT",
        "Acceptance and commitment therapy as a way of reading the entries. Values versus goals; "
        "experiential avoidance (what is being avoided feeling, and what that costs); cognitive "
        "fusion with thoughts; willingness; committed action that fits stated values.",
    ),
    Perspective(
        "psychodynamic",
        "Psychodynamic",
        "A psychodynamic reading. Recurring relational and emotional patterns; defenses "
        "(intellectualization, avoidance, projection, displacement, humor); what is conspicuously "
        "absent from the entries; repetition across time. Offer hypotheses and label them as "
        "hypotheses, never as conclusions.",
    ),
    Perspective(
        "ifs",
        "IFS",
        "Internal Family Systems as a way of reading the entries. Distinct 'parts' (critic, "
        "perfectionist, avoider, pleaser, taskmaster) and their protective intent; which part "
        "seems to be driving each entry; conflicts between parts; what a calm, curious, "
        "self-led response would look like.",
    ),
    Perspective(
        "skeptic",
        "Skeptic",
        "The devil's advocate. Attack the author's self-narrative. Where do they flatter "
        "themselves, and where are they unfairly harsh? Which claims lack evidence? What "
        "alternative explanations fit the same facts? Look for cherry-picked evidence, convenient "
        "excuses, and gaps between claimed accomplishments and what the entries show.",
    ),
    Perspective(
        "strengths",
        "Strengths Coach",
        "A strengths coach. Identify real strengths that the entries actually evidence, how they "
        "could be used more deliberately, and where a strength is overplayed into a weakness. "
        "Every strength must be backed by cited evidence; praise without a citation is not "
        "allowed. Calibrated, not cheerleading.",
    ),
]

BY_KEY: dict[str, Perspective] = {p.key: p for p in PERSPECTIVES}
