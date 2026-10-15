"""The panel of perspectives. `lens` is injected into the task prompt.

`default` decides whether the box is ticked on the Review page. Output order follows this list.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Perspective:
    key: str
    name: str
    lens: str
    default: bool = True


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
        "aristotelian",
        "Aristotelian",
        "Virtue ethics (Aristotle's Nicomachean Ethics, MacIntyre). Character is built by repeated "
        "action, so ask which habits the entries are actually building and who the author is "
        "becoming through them. The mean between excess and deficiency; practical wisdom "
        "(phronesis), meaning choosing the right action in the particular situation rather than "
        "following a rule; friendship and community as part of a good life, not a distraction "
        "from it; flourishing as activity, not as a feeling.",
        default=False,
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
        default=False,
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
        default=False,
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
    Perspective(
        "systems",
        "Systems Architect",
        "Behavioral engineering and executive-function mechanics (Fogg's Tiny Habits, Allen's GTD, "
        "Newport, Barkley on self-regulation). Set aside deep emotional motives and look strictly "
        "at activation energy, task granularity, working-memory bottlenecks, environment design "
        "and productive procrastination (building tools or systems instead of doing the work). "
        "Point out when a carried-over todo is really an undecomposed project in disguise, judge "
        "whether the 'first three small steps' and 'next action' answers are actually small and "
        "physical enough to start, and check whether what the author says they do on high-energy "
        "days matches their 1-5 energy data.",
    ),
    Perspective(
        "social",
        "Social Coach",
        "Interpersonal dynamics, active curiosity and social mechanics (Goffman on self-presentation, "
        "Carnegie, Voss on tactical empathy, Adler). Look at how the author prepares for, takes part "
        "in and reflects on interactions. Is the author curious about other people's worlds, or "
        "mostly monitoring themselves? Critique the quality of the conversation prep, the stories "
        "banked for telling, and the follow-through on the open loops they log about other "
        "people. Say whether observations about others are turning into actual contact.",
    ),
]

BY_KEY: dict[str, Perspective] = {p.key: p for p in PERSPECTIVES}
